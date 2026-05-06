"""
news_agent — Stage 1 of the digest graph.

Phase 2 addition: also fetches watchlist-targeted stories for the user.
Watchlist stories are stored separately in state so builder_agent can
badge them differently in the email.
"""

import logging
from app.graph.state import DigestState
from app.search import fetch_fintech_news
from app.watchlist import fetch_watchlist_stories

logger = logging.getLogger(__name__)


async def news_agent(state: DigestState) -> dict:
    """
    Fetches general fintech news AND watchlist-targeted stories in parallel.
    """
    logger.info(f"[news_agent] run_id={state['run_id']}")

    try:
        # General news (sync — runs Tavily queries)
        raw_stories = fetch_fintech_news()
        logger.info(f"[news_agent] Fetched {len(raw_stories)} general stories")

        # Watchlist stories (async — targeted entity queries)
        user_id = state.get("user_id", 1)
        try:
            watchlist_stories = await fetch_watchlist_stories(user_id)
        except Exception as e:
            logger.warning(f"[news_agent] Watchlist fetch failed (non-critical): {e}")
            watchlist_stories = []

        if not raw_stories and not watchlist_stories:
            return {
                "raw_stories": [],
                "watchlist_stories": [],
                "should_abort": True,
                "abort_reason": "No stories returned from search — Tavily may be rate-limited",
            }

        return {
            "raw_stories": raw_stories,
            "watchlist_stories": watchlist_stories,
        }

    except Exception as e:
        logger.error(f"[news_agent] Fatal: {e}", exc_info=True)
        return {
            "raw_stories": [],
            "watchlist_stories": [],
            "should_abort": True,
            "abort_reason": f"news_agent exception: {str(e)[:120]}",
            "errors": [f"news_agent: {str(e)}"],
        }