"""
alert_graph.py — A lighter LangGraph subgraph that runs every ALERT_POLL_HOURS
to scan for breaking fintech news requiring immediate delivery.

Graph topology:

  START
    │
    ▼
  alert_scanner       ← Targeted Tavily search for high-urgency events
    │
    ▼
  urgency_scorer      ← Groq scores each story 1-10 for urgency
    │
    ▼
  alert_dispatcher    ← Sends email for stories >= ALERT_URGENCY_THRESHOLD
    │
    ▼
  END

Stories sent as alerts are also recorded to alert_history so they
won't trigger repeat alerts, and to story_memory so they won't appear
in the next daily digest either.

Urgency scoring criteria (used in the LLM prompt):
  9-10: Bank failure, systemic risk event, major cyber attack on financial infra
  7-8:  Major regulatory action, central bank emergency measure, large fraud event
  5-6:  Significant M&A, large funding round, notable product launch
  1-4:  Routine news, minor updates (filtered out)
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from typing_extensions import TypedDict

from app.config import settings
from app.database import was_alert_sent, record_alert_sent
from app.gmail import send_digest_email
from app.email_builder import build_email_html
from app.memory import save_stories_to_memory
from app.search import is_excluded, _extract_source
from groq import Groq

logger = logging.getLogger(__name__)

# Alert-specific search queries targeting high-urgency event types
ALERT_QUERIES = [
    "bank failure collapse liquidation 2025",
    "financial regulator enforcement action penalty fine",
    "banking cyber attack data breach security incident",
    "central bank emergency rate decision",
    "major fintech fraud scheme exposed",
    "bank acquisition merger deal signed",
]

groq_client = Groq(api_key=settings.GROQ_API_KEY)

# Module-level compiled alert graph
_alert_graph = None
_alert_checkpointer = None


# ── State ────────────────────────────────────────────────────────────────────

class AlertState(TypedDict):
    run_id: str
    started_at: datetime
    candidate_stories: list[dict]   # From scanner
    urgent_stories: list[dict]      # Scored >= threshold
    alerts_sent: int
    errors: list[str]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def alert_scanner(state: AlertState) -> dict:
    """Search for high-urgency fintech events using targeted queries."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    seen_urls: set[str] = set()
    candidates: list[dict] = []

    for query in ALERT_QUERIES:
        try:
            response = client.search(
                query=query,
                search_depth="basic",   # Faster than advanced — alerts need speed
                topic="news",
                days=1,
                max_results=3,
            )
            for r in response.get("results", []):
                url = r.get("url", "")
                title = r.get("title", "").strip()
                snippet = r.get("content", "").strip()

                if url in seen_urls or is_excluded(title, snippet):
                    continue

                seen_urls.add(url)
                candidates.append({
                    "title": title,
                    "url": url,
                    "source": _extract_source(url),
                    "snippet": snippet[:300],
                    "published_date": r.get("published_date"),
                })
        except Exception as e:
            logger.warning(f"[alert_scanner] Query failed '{query}': {e}")

    logger.info(f"[alert_scanner] Found {len(candidates)} candidates")
    return {"candidate_stories": candidates}


async def urgency_scorer(state: AlertState) -> dict:
    """
    Score each candidate story for urgency using Groq.
    Filters out already-alerted stories before scoring.
    """
    candidates = state.get("candidate_stories", [])
    if not candidates:
        return {"urgent_stories": []}

    # Filter already-alerted stories
    fresh = []
    for story in candidates:
        if not await was_alert_sent(story["url"]):
            fresh.append(story)

    if not fresh:
        logger.info("[urgency_scorer] No fresh candidates after alert_history filter")
        return {"urgent_stories": []}

    stories_json = json.dumps(
        [{"title": s["title"], "snippet": s["snippet"]} for s in fresh],
        indent=2,
    )

    prompt = f"""Score each fintech news story for urgency on a scale of 1-10.

Scoring guide:
9-10: Systemic risk event — bank failure, major payment system outage, government seizure
7-8: Significant regulatory action, central bank emergency measure, large-scale fraud exposed
5-6: Notable M&A deal closed, major funding round, significant product launch
1-4: Routine news — not urgent

{stories_json}

Respond ONLY with valid JSON (no markdown):
[
  {{"index": 0, "urgency": 8, "reason": "one sentence"}},
  ...
]"""

    try:
        response = groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1].lstrip("json").strip()

        scores = json.loads(content)
        urgent = []
        for item in scores:
            idx = item.get("index", 0)
            urgency = item.get("urgency", 0)
            if urgency >= settings.ALERT_URGENCY_THRESHOLD and idx < len(fresh):
                story = dict(fresh[idx])
                story["urgency"] = urgency
                story["urgency_reason"] = item.get("reason", "")
                urgent.append(story)
                logger.info(
                    f"[urgency_scorer] URGENT ({urgency}/10): {story['title'][:60]}"
                )

        return {"urgent_stories": urgent}

    except Exception as e:
        logger.error(f"[urgency_scorer] Scoring failed: {e}", exc_info=True)
        return {"urgent_stories": [], "errors": [f"urgency_scorer: {str(e)}"]}


async def alert_dispatcher(state: AlertState) -> dict:
    """Send individual alert emails and record them to prevent re-sending."""
    urgent_stories = state.get("urgent_stories", [])
    if not urgent_stories:
        logger.info("[alert_dispatcher] No urgent stories to send")
        return {"alerts_sent": 0}

    sent_count = 0
    for story in urgent_stories:
        try:
            # Build a minimal single-story alert email
            digest = {
                "subject": f"BREAKING: {story['title'][:70]}",
                "stories": [{
                    "title": story["title"],
                    "synopsis": (
                        f"[URGENCY {story['urgency']}/10] {story['urgency_reason']}\n\n"
                        f"{story['snippet']}"
                    ),
                    "source": story["source"],
                    "url": story["url"],
                    "published_date": story.get("published_date"),
                }],
            }
            html = build_email_html(digest)
            sent = send_digest_email(f"🚨 BREAKING: {story['title'][:60]}", html)

            if sent:
                await record_alert_sent(story["url"], story["title"], story["urgency"])
                # Also add to story_memory so it's excluded from the daily digest
                await save_stories_to_memory([story])
                sent_count += 1
                logger.info(f"[alert_dispatcher] Alert sent: {story['title'][:60]}")

        except Exception as e:
            logger.error(f"[alert_dispatcher] Failed to send alert: {e}")

    return {"alerts_sent": sent_count}


# ── Graph builder ─────────────────────────────────────────────────────────────

async def build_alert_graph(checkpointer):
    """Compile the alert graph using the shared Postgres checkpointer."""
    global _alert_graph

    builder = StateGraph(AlertState)

    builder.add_node("alert_scanner", alert_scanner)
    builder.add_node("urgency_scorer", urgency_scorer)
    builder.add_node("alert_dispatcher", alert_dispatcher)

    builder.add_edge(START, "alert_scanner")
    builder.add_edge("alert_scanner", "urgency_scorer")
    builder.add_edge("urgency_scorer", "alert_dispatcher")
    builder.add_edge("alert_dispatcher", END)

    _alert_graph = builder.compile(checkpointer=checkpointer)

    logger.info("LangGraph alert graph compiled")

    return _alert_graph


async def run_alert_check():
    """Entry point for the APScheduler alert job."""
    run_id = f"alert-{str(uuid.uuid4())}"
    logger.info(f"=== Alert check {run_id} ===")

    initial_state: AlertState = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc),
        "candidate_stories": [],
        "urgent_stories": [],
        "alerts_sent": 0,
        "errors": [],
    }

    config = {"configurable": {"thread_id": run_id}}

    try:
        if _alert_graph is None:
            logger.warning("[alert_check] Alert graph not built yet — skipping")
            return
        final_state = await _alert_graph.ainvoke(initial_state, config=config)
        logger.info(f"=== Alert check complete: {final_state.get('alerts_sent', 0)} alerts sent ===")
    except Exception as e:
        logger.exception(f"=== Alert check {run_id} CRASHED: {e} ===")