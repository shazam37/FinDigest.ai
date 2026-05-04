"""
Agent orchestrator — wires together search → LLM → email.

Design principles:
- Each stage is independently logged and can fail gracefully
- The agent never crashes silently; it always updates state with an error
- Runs are logged to state.run_history for trend analysis
"""

import logging
from datetime import datetime, timezone

from app.search import fetch_fintech_news
from app.llm import process_stories
from app.email_builder import build_email_html
from app.gmail import send_digest_email, create_calendar_confirmation
from app.config import settings
from app.state import agent_state

logger = logging.getLogger(__name__)


async def run_fintech_digest():
    """
    Full agent pipeline:
      1. Search → raw stories
      2. LLM → ranked + summarised stories + subject line
      3. Build HTML email
      4. Send via Gmail
      5. Log calendar event
      6. Update state
    """
    run_start = datetime.now(timezone.utc)
    logger.info("=== FinTech Digest starting ===")

    try:
        # --- Stage 1: Fetch news ---
        logger.info("Stage 1: Fetching news...")
        raw_stories = fetch_fintech_news()
        logger.info(f"  → {len(raw_stories)} raw stories fetched")

        if not raw_stories:
            _update_state("⚠️ No stories found", 0, run_start)
            logger.warning("No stories found — skipping email send")
            return

        # --- Stage 2: LLM processing ---
        logger.info("Stage 2: LLM processing...")
        digest = process_stories(raw_stories)
        stories = digest.get("stories", [])
        subject = digest.get("subject", "FinTech Intelligence Digest")
        logger.info(f"  → {len(stories)} stories selected by LLM")

        # Safety check: if LLM returned too few stories, something went wrong
        if len(stories) < settings.MIN_STORIES_BEFORE_SEND:
            logger.warning(
                f"Only {len(stories)} stories returned (min: {settings.MIN_STORIES_BEFORE_SEND}). "
                "Skipping send to avoid sending a near-empty email."
            )
            _update_state(f"⚠️ Too few stories ({len(stories)})", len(stories), run_start)
            return

        # --- Stage 3: Build HTML ---
        logger.info("Stage 3: Building email HTML...")
        html = build_email_html(digest)
        agent_state["last_email_html"] = html  # Save for /preview endpoint

        # --- Stage 4: Send email ---
        logger.info("Stage 4: Sending email...")
        email_sent = send_digest_email(subject, html)

        if not email_sent:
            _update_state("❌ Email send failed", len(stories), run_start)
            return

        # --- Stage 5: Calendar event (non-blocking) ---
        logger.info("Stage 5: Creating calendar event...")
        create_calendar_confirmation(subject, len(stories))

        # --- Done ---
        elapsed = (datetime.now(timezone.utc) - run_start).total_seconds()
        logger.info(f"=== Digest complete in {elapsed:.1f}s — {len(stories)} stories sent ===")
        _update_state("✅ Sent successfully", len(stories), run_start)

    except Exception as e:
        logger.exception(f"Unexpected agent error: {e}")
        _update_state(f"❌ Error: {str(e)[:80]}", 0, run_start)


def _update_state(status: str, story_count: int, run_start: datetime):
    """Update shared state and append to run history."""
    run_time = run_start.strftime("%Y-%m-%d %H:%M UTC")
    agent_state["last_run"] = run_time
    agent_state["last_status"] = status
    agent_state["stories_found"] = story_count

    # Append to history (keep last 30 runs)
    agent_state["run_history"].append({
        "timestamp": run_time,
        "stories": story_count,
        "status": status,
    })
    agent_state["run_history"] = agent_state["run_history"][-30:]