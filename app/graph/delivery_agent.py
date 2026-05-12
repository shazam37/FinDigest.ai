"""
delivery_agent — Stage 5 of the digest graph.
Responsibilities:
    - Build the email HTML using email_builder
    - Send the email via Gmail API
    - Fan out to other channels (Slack, Telegram) via channels.py
    - Save sent stories to memory (for future deduplication)
    - Score and track sentiment for watchlist entities (Phase 2)    
"""

import logging
from app.graph.state import DigestState
from app.gmail import send_digest_email
from app.memory import save_stories_to_memory
from app.email_builder import build_email_html

logger = logging.getLogger(__name__)


async def delivery_agent(state: DigestState) -> dict:
    """Builds HTML, sends email, fans out to other channels, saves to memory."""
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

    # Build HTML
    try:
        digest = {"subject": subject, "stories": curated_stories}
        html = build_email_html(digest, run_id=run_id, user_id=user_id)
        from app.graph.runtime_state import runtime_state
        runtime_state["last_email_html"] = html
    except Exception as e:
        logger.error(f"[delivery_agent] HTML build failed: {e}", exc_info=True)
        return {
            "email_sent": False,
            "should_abort": True,
            "abort_reason": f"email build failed: {str(e)[:100]}",
            "errors": [f"delivery_agent html: {str(e)}"],
        }

    # Send primary email
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

    # Phase 3: Multi-channel fan-out (non-blocking)
    try:
        from app.delivery.channels import fan_out_digest
        channel_results = await fan_out_digest(subject, curated_stories)
        logger.info(f"[delivery_agent] Channel fan-out: {channel_results}")
    except Exception as e:
        logger.warning(f"[delivery_agent] Channel fan-out failed (non-critical): {e}")

    # Save to story memory
    try:
        await save_stories_to_memory(curated_stories)
    except Exception as e:
        logger.warning(f"[delivery_agent] Memory save failed (non-critical): {e}")

    # Phase 2: Sentiment tracking
    try:
        from app.watchlist import score_and_track_sentiment
        await score_and_track_sentiment(curated_stories, user_id)
    except Exception as e:
        logger.warning(f"[delivery_agent] Sentiment tracking failed (non-critical): {e}")

    return {"email_sent": True}