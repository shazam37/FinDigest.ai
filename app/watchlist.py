"""
watchlist.py — Custom entity/topic watchlist with sentiment velocity tracking.

Responsibilities:
  1. For each watched entity, generate targeted Tavily search queries
     and return matching stories — these are guaranteed to appear in
     the digest (they bypass the normal LLM ranking gate).

  2. Score each story's sentiment for the mentioned entity using Groq
     (fast, single call for all stories). Persist scores to entity_sentiment.

  3. Detect sentiment velocity shifts: if an entity's average sentiment
     moves by >= SENTIMENT_ALERT_DELTA in the last 48 hours vs the prior
     7-day baseline, trigger a signal alert email.

Sentiment score convention:
  -1.0 = strongly negative (e.g. "bank collapses", "regulator fines")
   0.0 = neutral (informational, no clear valence)
  +1.0 = strongly positive (e.g. "record profits", "licence granted")
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from groq import Groq
from tavily import TavilyClient

from app.config import settings
from app.database import (
    fetch_watchlist,
    record_sentiment,
    fetch_sentiment_window,
    record_alert_sent,
    was_alert_sent,
)
from app.search import is_excluded, _extract_source

logger = logging.getLogger(__name__)
_groq = Groq(api_key=settings.GROQ_API_KEY)


async def fetch_watchlist_stories(user_id: int) -> list[dict]:
    """
    Run targeted Tavily searches for each watchlist entity.
    Returns story dicts tagged with which entity matched them.
    Deduplicates by URL across all entity queries.
    """
    entities = await fetch_watchlist(user_id)
    if not entities:
        return []

    client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    seen_urls: set[str] = set()
    watchlist_stories: list[dict] = []

    for entity_row in entities:
        entity = entity_row["entity"]
        try:
            response = client.search(
                query=f"{entity} fintech banking news",
                search_depth="basic",
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

                watchlist_stories.append({
                    "title": title,
                    "url": url,
                    "source": _extract_source(url),
                    "snippet": snippet[:400],
                    "published_date": r.get("published_date"),
                    "watchlist_entity": entity,    # Badge shown in email
                    "watchlist_match": True,
                })
        except Exception as e:
            logger.warning(f"[watchlist] Search failed for '{entity}': {e}")

    logger.info(f"[watchlist] Found {len(watchlist_stories)} watchlist stories for user {user_id}")
    return watchlist_stories


async def score_and_track_sentiment(stories: list[dict], user_id: int):
    """
    Score sentiment for all stories that match a watchlist entity.
    Persists scores and checks for velocity alerts.
    Runs asynchronously after delivery — non-blocking.
    """
    watchlist_stories = [s for s in stories if s.get("watchlist_match")]
    if not watchlist_stories:
        return

    # Score all watchlist stories in one Groq call
    scores = await _score_sentiment_batch(watchlist_stories)

    # Persist scores
    for story, score in zip(watchlist_stories, scores):
        await record_sentiment(
            entity=story["watchlist_entity"],
            score=score,
            story_url=story["url"],
            story_title=story["title"],
        )

    # Check for velocity alerts per entity
    entities_seen = {s["watchlist_entity"] for s in watchlist_stories}
    for entity in entities_seen:
        await _check_sentiment_velocity(entity, user_id)


async def _score_sentiment_batch(stories: list[dict]) -> list[float]:
    """Score sentiment for a batch of stories in one Groq call."""
    if not stories:
        return []

    items = [{"index": i, "title": s["title"], "snippet": s["snippet"][:200]}
             for i, s in enumerate(stories)]

    prompt = f"""Score the sentiment of each news story toward the financial institution or topic it covers.

Scale: -1.0 (very negative) to 0.0 (neutral) to +1.0 (very positive)

Examples:
  "Bank fined £50M for compliance failures" → -0.8
  "Neobank granted full banking licence" → +0.7
  "Bank announces new API partnership" → +0.3
  "Bank releases Q3 results" → 0.0

Stories:
{json.dumps(items, indent=2)}

Respond ONLY with a JSON array of floats (one per story, same order):
[-0.5, 0.3, ...]"""

    try:
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1].lstrip("json").strip()
        scores = json.loads(content)
        # Clamp to [-1, 1]
        return [max(-1.0, min(1.0, float(s))) for s in scores]
    except Exception as e:
        logger.error(f"[watchlist] Sentiment scoring failed: {e}")
        return [0.0] * len(stories)


async def _check_sentiment_velocity(entity: str, user_id: int):
    """
    Compare recent 48h average sentiment vs 7-day baseline.
    Sends a signal alert if the delta exceeds SENTIMENT_ALERT_DELTA.
    """
    from app.gmail import send_digest_email
    from app.email_builder import build_sentiment_alert_html

    # Recent window (last 48h)
    recent = await fetch_sentiment_window(entity, days=2)
    baseline = await fetch_sentiment_window(entity, days=settings.SENTIMENT_WINDOW_DAYS)

    if len(recent) < 2 or len(baseline) < 4:
        return   # Not enough data for meaningful comparison

    recent_avg = sum(r["score"] for r in recent) / len(recent)
    baseline_avg = sum(r["score"] for r in baseline) / len(baseline)
    delta = recent_avg - baseline_avg

    if abs(delta) < settings.SENTIMENT_ALERT_DELTA:
        return

    # Build a unique URL for this alert to prevent re-sending
    alert_url = f"sentiment-alert:{entity}:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    if await was_alert_sent(alert_url):
        return

    direction = "negative" if delta < 0 else "positive"
    logger.info(
        f"[watchlist] Sentiment velocity alert: {entity} shifted {delta:+.2f} "
        f"({direction}) over 48h vs {settings.SENTIMENT_WINDOW_DAYS}d baseline"
    )

    try:
        html = build_sentiment_alert_html(entity, delta, recent_avg, baseline_avg, recent)
        subject = f"📊 Sentiment Shift: {entity} {'↓' if delta < 0 else '↑'} {abs(delta):.0%} in 48h"
        sent = send_digest_email(subject, html)
        if sent:
            await record_alert_sent(alert_url, f"Sentiment shift for {entity}", 6)
    except Exception as e:
        logger.error(f"[watchlist] Sentiment alert send failed: {e}")