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
from app.database import fetch_preference_profile, fetch_user_onboarding
from app.preferences import build_preference_prompt_block, build_onboarding_prompt_block

logger = logging.getLogger(__name__)


async def curator_agent(state: DigestState) -> dict:
    logger.info(f"[curator_agent] run_id={state['run_id']}")

    if state.get("should_abort"):
        logger.info("[curator_agent] Skipping — upstream abort")
        return {}

    novel_stories = state.get("novel_stories", [])
    watchlist_stories = state.get("watchlist_stories", [])

    if not novel_stories and not watchlist_stories:
        return {"should_abort": True, "abort_reason": "No novel stories to curate"}

    user_id = state.get("user_id", 1)
    preference_profile = {}
    preference_block = ""

    try:
        # Priority 1: feedback-learned profile
        profile = await fetch_preference_profile(user_id)
        if profile:
            preference_profile = profile
            preference_block = build_preference_prompt_block(profile)
            logger.info(f"[curator_agent] Using feedback profile for user {user_id}")
        else:
            # Priority 2: onboarding profile (cold-start)
            onboarding = await fetch_user_onboarding(user_id)
            if onboarding.get("onboarding_complete"):
                preference_block = build_onboarding_prompt_block(onboarding)
                preference_profile = {"_source": "onboarding", **onboarding}
                logger.info(f"[curator_agent] Using onboarding profile for user {user_id}")
            else:
                logger.info(f"[curator_agent] No profile for user {user_id} — using defaults")
    except Exception as e:
        logger.warning(f"[curator_agent] Profile load failed (non-critical): {e}")

    try:
        digest = process_stories(
            novel_stories,
            preference_block=preference_block,
            watchlist_stories=watchlist_stories,
        )
        curated = digest.get("stories", [])
        subject = digest.get("subject", "FinTech Intelligence Digest")

        logger.info(f"[curator_agent] {len(curated)} stories curated")

        if len(curated) < settings.MIN_STORIES_BEFORE_SEND:
            return {
                "curated_stories": curated,
                "email_subject": subject,
                "preference_profile": preference_profile,
                "should_abort": True,
                "abort_reason": f"Only {len(curated)} stories (minimum {settings.MIN_STORIES_BEFORE_SEND})",
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
            "abort_reason": f"curator_agent: {str(e)[:120]}",
            "errors": [f"curator_agent: {str(e)}"],
        }