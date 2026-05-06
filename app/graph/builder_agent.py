"""
builder_agent — Stage 4 of the digest graph.

Phase 2 note: HTML rendering has moved to delivery_agent because it needs
run_id and user_id (available in state) to generate per-story feedback links.
This node is now a lightweight pass-through that validates curated_stories
and sets email_html to a sentinel — delivery_agent builds the real HTML.

We keep this node in the graph for:
  1. A clean abort point if curated_stories is somehow empty post-curation
  2. Maintaining the 6-node graph topology for checkpointing granularity
  3. A future hook for multi-format rendering (e.g. Slack, PDF)
"""

import logging
from app.graph.state import DigestState

logger = logging.getLogger(__name__)


def builder_agent(state: DigestState) -> dict:
    """Validates curated stories exist before delivery."""
    logger.info(f"[builder_agent] run_id={state['run_id']}")

    if state.get("should_abort"):
        logger.info("[builder_agent] Skipping — upstream abort")
        return {}

    curated = state.get("curated_stories", [])
    if not curated:
        return {
            "should_abort": True,
            "abort_reason": "builder_agent: curated_stories is empty",
        }

    logger.info(f"[builder_agent] {len(curated)} stories validated — passing to delivery")
    return {"email_html": "__pending__"}   # Actual HTML built in delivery_agent