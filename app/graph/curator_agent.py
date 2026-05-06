"""
curator_agent — Stage 3 of the digest graph.

Phase 2 addition:
  - Loads the user's preference profile from PostgreSQL
  - Injects the preference block into the LLM curation prompt
  - Passes watchlist_stories to llm.process_stories for guaranteed inclusion
"""

import logging
from app.graph.state import DigestState
from app.llm import process_stories
from app.config import settings
from app.database import fetch_preference_profile
from app.preferences import build_preference_prompt_block

logger = logging.getLogger(__name__)


async def curator_agent(state: DigestState) -> dict:
    """
    Sends novel stories to Groq for curation with personalisation context.
    """
    logger.info(f"[curator_agent] run_id={state['run_id']}")

    if state.get("should_abort"):
        logger.info("[curator_agent] Skipping — upstream abort")
        return {}

    novel_stories = state.get("novel_stories", [])
    watchlist_stories = state.get("watchlist_stories", [])

    if not novel_stories and not watchlist_stories:
        return {
            "should_abort": True,
            "abort_reason": "No novel stories to curate",
        }

    # Load preference profile for personalisation injection
    user_id = state.get("user_id", 1)
    preference_profile = {}
    preference_block = ""
    try:
        profile = await fetch_preference_profile(user_id)
        if profile:
            preference_profile = profile
            preference_block = build_preference_prompt_block(profile)
            logger.info(f"[curator_agent] Preference profile active for user {user_id}")
        else:
            logger.info(f"[curator_agent] No preference profile yet for user {user_id}")
    except Exception as e:
        logger.warning(f"[curator_agent] Preference load failed (non-critical): {e}")

    try:
        digest = process_stories(
            novel_stories,
            preference_block=preference_block,
            watchlist_stories=watchlist_stories,
        )
        curated = digest.get("stories", [])
        subject = digest.get("subject", "FinTech Intelligence Digest")

        logger.info(f"[curator_agent] {len(curated)} total stories after curation")

        if len(curated) < settings.MIN_STORIES_BEFORE_SEND:
            return {
                "curated_stories": curated,
                "email_subject": subject,
                "preference_profile": preference_profile,
                "should_abort": True,
                "abort_reason": (
                    f"Only {len(curated)} stories curated "
                    f"(minimum is {settings.MIN_STORIES_BEFORE_SEND})"
                ),
            }

        return {
            "curated_stories": curated,
            "email_subject": subject,
            "preference_profile": preference_profile,
        }

    except Exception as e:
        logger.error(f"[curator_agent] Fatal: {e}", exc_info=True)
        return {
            "should_abort": True,
            "abort_reason": f"curator_agent exception: {str(e)[:120]}",
            "errors": [f"curator_agent: {str(e)}"],
        }