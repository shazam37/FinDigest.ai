"""
delivery_agent — Stage 5 of the digest graph.

Phase 2 additions:
  - Passes run_id and user_id to build_email_html (for feedback links)
  - After successful send, triggers async sentiment scoring for watchlist stories
"""

import logging
from app.graph.state import DigestState
from app.gmail import send_digest_email
from app.memory import save_stories_to_memory
from app.email_builder import build_email_html

logger = logging.getLogger(__name__)


async def delivery_agent(state: DigestState) -> dict:
    """Builds final HTML, sends email, saves to memory, triggers sentiment scoring."""
    logger.info(f"[delivery_agent] run_id={state['run_id']}")

    if state.get("should_abort"):
        logger.info("[delivery_agent] Skipping — upstream abort")
        return {"email_sent": False}

    subject = state.get("email_subject", "FinTech Intelligence Digest")
    curated_stories = state.get("curated_stories", [])
    run_id = state.get("run_id", "")
    user_id = state.get("user_id", 1)

    if not curated_stories:
        return {
            "email_sent": False,
            "should_abort": True,
            "abort_reason": "No curated stories to send",
        }

    # Build HTML here (Phase 2: needs run_id + user_id for feedback links)
    try:
        digest = {
            "subject": subject,
            "stories": curated_stories,
        }
        html = build_email_html(digest, run_id=run_id, user_id=user_id)

        # Cache for /preview endpoint
        from app.state import agent_state
        agent_state["last_email_html"] = html
    except Exception as e:
        logger.error(f"[delivery_agent] HTML build failed: {e}", exc_info=True)
        return {
            "email_sent": False,
            "should_abort": True,
            "abort_reason": f"email build failed: {str(e)[:100]}",
            "errors": [f"delivery_agent html: {str(e)}"],
        }

    # Send email
    try:
        sent = send_digest_email(subject, html)
    except Exception as e:
        logger.error(f"[delivery_agent] Gmail send exception: {e}", exc_info=True)
        return {
            "email_sent": False,
            "errors": [f"delivery_agent send: {str(e)}"],
        }

    if not sent:
        return {
            "email_sent": False,
            "errors": ["delivery_agent: Gmail API returned failure"],
        }

    logger.info(f"[delivery_agent] Email sent: {subject}")

    # Save to memory (non-blocking failure OK)
    try:
        await save_stories_to_memory(curated_stories)
    except Exception as e:
        logger.warning(f"[delivery_agent] Memory save failed (non-critical): {e}")

    # Sentiment scoring for watchlist stories (Phase 2, non-blocking)
    try:
        from app.watchlist import score_and_track_sentiment
        await score_and_track_sentiment(curated_stories, user_id)
    except Exception as e:
        logger.warning(f"[delivery_agent] Sentiment tracking failed (non-critical): {e}")

    return {"email_sent": True}