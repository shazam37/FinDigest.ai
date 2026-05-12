"""
Shared state schema for the FinTech digest LangGraph.

Every node reads from and writes to this TypedDict.
LangGraph merges node outputs into the state automatically using
the reducer functions defined via Annotated[..., reducer].

State lifecycle:
  start → news_agent → memory_agent → curator_agent → builder_agent
        → delivery_agent → calendar_agent → END

The checkpointer snapshots state after each node, so if any node
fails the run can be resumed from that exact point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Optional
from typing_extensions import TypedDict


def _append(existing: list, new: list) -> list:
    """Reducer: append new items to existing list (used for errors log)."""
    return existing + new


def _replace(existing: Any, new: Any) -> Any:
    """Reducer: last-write-wins (default for most fields)."""
    return new


class DigestState(TypedDict):
    # === Identity ===
    run_id: str                   # UUID for this run — used as LangGraph thread_id
    run_type: str                 # "daily_digest" | "breaking_alert"
    started_at: datetime

    # === Stage 1: news_agent ===
    raw_stories: list[dict]       # All stories returned by Tavily
    watchlist_stories: list[dict] # Stories matched from user watchlists (Phase 2)

    # === Stage 2: memory_agent ===
    novel_stories: list[dict]     # After semantic deduplication

    # === Stage 3: curator_agent ===
    curated_stories: list[dict]   # LLM-ranked and summarised
    email_subject: str            # LLM-generated subject line

    # === Phase 2: Personalisation context ===
    # Loaded before curation, injected into the LLM prompt
    user_id: int                  # Default user (or per-user in multi-user runs)
    preference_profile: dict      # Loaded from user_preferences table

    # === Stage 4: builder_agent ===
    email_html: str               # Final rendered HTML

    # === Stage 5: delivery_agent ===
    email_sent: bool

    # === Stage 6: calendar_agent ===
    calendar_logged: bool

    # === Cross-cutting ===
    errors: Annotated[list[str], _append]   # Non-fatal errors accumulate
    should_abort: bool                       # Set True to skip remaining nodes
    abort_reason: str