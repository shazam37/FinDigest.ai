"""
synthesis_graph.py — Friday weekly narrative synthesis.

Runs every Friday at 8 AM (before the daily digest).
Reads the last 7 days of story_memory from PostgreSQL, calls Groq
to extract 3-5 macro themes as narrative arcs, and sends a
"Week in Review" email.

This is NOT a LangGraph StateGraph — it's a simpler async function
because it has no branching logic or checkpointing requirements.
The weekly synthesis doesn't need fault recovery; if it fails,
it fails silently and the user gets the daily digest anyway.

Narrative arc format:
  "Regulator pressure on BNPL intensified this week, with three major
   enforcement actions in the EU and UK suggesting a coordinated push
   toward stricter consumer lending rules."

NOT:
  "There were 3 stories about BNPL this week."
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from groq import Groq

from app.config import settings
from app.database import get_conn
from app.gmail import send_digest_email
from app.email_builder import build_weekly_synthesis_html

logger = logging.getLogger(__name__)
_groq = Groq(api_key=settings.GROQ_API_KEY)


async def run_weekly_synthesis():
    """Entry point — called by APScheduler every Friday at SYNTHESIS_HOUR."""
    logger.info("=== Weekly synthesis starting ===")

    try:
        stories = await _fetch_weeks_stories()
        if len(stories) < 5:
            logger.info(f"[synthesis] Only {len(stories)} stories this week — skipping")
            return

        synthesis = await _synthesise_themes(stories)
        html = build_weekly_synthesis_html(synthesis)
        subject = synthesis.get("subject", "FinTech Week in Review")
        sent = send_digest_email(f"📋 {subject}", html)

        logger.info(
            f"=== Weekly synthesis complete: sent={sent}, "
            f"{len(synthesis.get('themes', []))} themes from {len(stories)} stories ==="
        )

    except Exception as e:
        logger.exception(f"=== Weekly synthesis CRASHED: {e} ===")


async def _fetch_weeks_stories() -> list[dict]:
    """
    Fetch the last 7 days of stories from story_memory.
    We use story_memory (not run_history) because it contains titles
    which is all we need for synthesis.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    async with get_conn() as conn:
        rows = await (await conn.execute(
            """
            SELECT title, source, url, created_at
            FROM story_memory
            WHERE created_at >= %s
            ORDER BY created_at DESC
            """,
            (cutoff,),
        )).fetchall()
    return [
        {"title": r[0], "source": r[1], "url": r[2], "created_at": r[3]}
        for r in rows
    ]


async def _synthesise_themes(stories: list[dict]) -> dict:
    """
    Ask Groq to extract 3-5 macro narrative themes from the week's stories.
    Returns synthesis dict matching build_weekly_synthesis_html() schema.
    """
    # Build a compact story list for the prompt (titles + sources only)
    story_lines = "\n".join(
        f"  - {s['title']} [{s['source']}]"
        for s in stories[:60]  # Cap at 60 to stay within token limits
    )

    # Date range string for the email header
    oldest = min(stories, key=lambda s: s["created_at"])["created_at"]
    newest = max(stories, key=lambda s: s["created_at"])["created_at"]
    if hasattr(oldest, "strftime"):
        week_range = f"{oldest.strftime('%-d %b')} – {newest.strftime('%-d %b %Y')}"
    else:
        week_range = "This week"

    prompt = f"""You are a senior financial analyst. Below are {len(stories)} fintech news headlines from the past week.

{story_lines}

Your task:
1. Identify 3-5 dominant macro themes or narrative arcs across these stories.
   A theme is NOT a list of events — it is a narrative: what is happening, why it matters,
   and what direction it is moving. Write each theme as a 3-4 sentence narrative paragraph.
2. Give each theme a sharp, specific title (max 8 words).
3. Count approximately how many stories relate to each theme.
4. Generate a subject line (max 12 words) that captures the single most important theme of the week.

Respond ONLY with valid JSON (no markdown):
{{
  "subject": "...",
  "themes": [
    {{
      "title": "...",
      "narrative": "3-4 sentence narrative arc...",
      "story_count": 8
    }}
  ]
}}"""

    try:
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior financial analyst writing a weekly briefing. "
                        "Write like the Economist, not a bullet-point summary. "
                        "Each theme must be a narrative arc with a clear direction."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,   # Slightly higher than daily digest for narrative creativity
            max_tokens=1500,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1].lstrip("json").strip()

        result = json.loads(content)
        result["week_range"] = week_range
        result["story_count_total"] = len(stories)
        return result

    except Exception as e:
        logger.error(f"[synthesis] LLM call failed: {e}", exc_info=True)
        # Minimal fallback
        return {
            "subject": f"FinTech Week in Review — {week_range}",
            "week_range": week_range,
            "story_count_total": len(stories),
            "themes": [
                {
                    "title": "This Week in FinTech",
                    "narrative": f"This week saw {len(stories)} significant developments "
                                 "across banking, regulation, and financial technology. "
                                 "Key themes included regulatory activity, product innovation, "
                                 "and continued investment in digital finance infrastructure.",
                    "story_count": len(stories),
                }
            ],
        }