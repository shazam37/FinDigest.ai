"""
memory_agent — Stage 2 of the digest graph.

Filters raw_stories against the 7-day story memory using pgvector
cosine similarity, producing novel_stories for the curator.

Why this matters:
  - Tavily often returns the same story across multiple query runs
  - News stories get re-indexed by aggregators and resurface days later
  - Without deduplication, users see the same story in consecutive digests

The memory is also updated AFTER delivery (in delivery_agent) so only
stories that were actually sent get recorded.

On failure: memory filter is skipped (graceful degradation), not aborted.
The digest still sends — just without deduplication for this run.
"""

import logging
from app.graph.state import DigestState
from app.memory import filter_seen_stories

logger = logging.getLogger(__name__)


async def memory_agent(state: DigestState) -> dict:
    """
    Runs semantic deduplication. On any DB/model error, passes raw_stories
    through unchanged so the pipeline continues.
    """
    logger.info(f"[memory_agent] run_id={state['run_id']}, "
                f"input={len(state.get('raw_stories', []))} stories")

    if state.get("should_abort"):
        logger.info("[memory_agent] Skipping — upstream abort")
        return {}

    raw_stories = state.get("raw_stories", [])

    try:
        novel = await filter_seen_stories(raw_stories)
        logger.info(f"[memory_agent] {len(raw_stories)} → {len(novel)} novel stories")

        if not novel:
            return {
                "novel_stories": [],
                "should_abort": True,
                "abort_reason": "All fetched stories were already seen in the last 7 days",
            }

        return {"novel_stories": novel}

    except Exception as e:
        # Graceful degradation: log the error but don't abort
        logger.error(f"[memory_agent] Deduplication failed, passing through: {e}", exc_info=True)
        return {
            "novel_stories": raw_stories,  # Fall through without deduplication
            "errors": [f"memory_agent dedup failed (fallback to no-dedup): {str(e)[:120]}"],
        }