"""
digest_graph.py — The main LangGraph StateGraph for daily digest runs.

Phase 2 change: initial state now includes user_id (loaded from DB at run start)
and empty watchlist_stories / preference_profile fields.
"""

import logging
import uuid
from datetime import datetime, timezone

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection

from app.graph.state import DigestState
from app.graph.news_agent import news_agent
from app.graph.memory_agent import memory_agent
from app.graph.curator_agent import curator_agent
from app.graph.builder_agent import builder_agent
from app.graph.delivery_agent import delivery_agent
from app.graph.calendar_agent import calendar_agent
from app.config import settings
from app.graph.runtime_state import runtime_state
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# _graph = None

async def build_graph(checkpointer):
    # global _graph

    # async with AsyncPostgresSaver.from_conn_string(
    #     settings.DATABASE_URL
    # ) as checkpointer:

    # await checkpointer.setup()

    graph_builder = StateGraph(DigestState)

    graph_builder.add_node("news_agent", news_agent)
    graph_builder.add_node("memory_agent", memory_agent)
    graph_builder.add_node("curator_agent", curator_agent)
    graph_builder.add_node("builder_agent", builder_agent)
    graph_builder.add_node("delivery_agent", delivery_agent)
    graph_builder.add_node("calendar_agent", calendar_agent)

    graph_builder.add_edge(START, "news_agent")
    graph_builder.add_edge("news_agent", "memory_agent")
    graph_builder.add_edge("memory_agent", "curator_agent")
    graph_builder.add_edge("curator_agent", "builder_agent")
    graph_builder.add_edge("builder_agent", "delivery_agent")
    graph_builder.add_edge("delivery_agent", "calendar_agent")
    graph_builder.add_edge("calendar_agent", END)

    graph = graph_builder.compile(checkpointer=checkpointer)

    logger.info("LangGraph digest graph compiled with PostgresSaver checkpointer")

    return graph


# def get_graph():
#     if _graph is None:
#         raise RuntimeError("Graph not built. Call build_graph() at startup.")
#     return _graph


async def run_fintech_digest(user_id: int | None = None):
    """
    Entry point for the daily digest scheduler job.
    user_id defaults to the system default user if not specified.
    """
    from app.database import get_or_create_default_user

    if user_id is None:
        try:
            user_id = await get_or_create_default_user()
        except Exception as e:
            logger.error(f"Could not resolve default user: {e} — using id=1")
            user_id = 1

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    logger.info(f"=== Starting digest run {run_id} for user {user_id} ===")

    initial_state: DigestState = {
        "run_id": run_id,
        "run_type": "daily_digest",
        "started_at": started_at,
        "raw_stories": [],
        "watchlist_stories": [],
        "novel_stories": [],
        "curated_stories": [],
        "email_subject": "",
        "email_html": "",
        "user_id": user_id,
        "preference_profile": {},
        "email_sent": False,
        "calendar_logged": False,
        "errors": [],
        "should_abort": False,
        "abort_reason": "",
    }

    config = {"configurable": {"thread_id": run_id}}

    try:
        # graph = get_graph()
        conn = await AsyncConnection.connect(
            settings.DATABASE_URL,
            autocommit=True,
            row_factory=dict_row,
        )

        checkpointer = AsyncPostgresSaver(conn)

        graph = await build_graph(checkpointer)

        final_state = await graph.ainvoke(
            initial_state,
            config=config,
        )
        # final_state = await graph.ainvoke(initial_state, config=config)

        runtime_state["last_status"] = "success"
        runtime_state["stories_found"] = len(final_state.get("curated_stories", []))
        runtime_state["last_run"] = datetime.now(timezone.utc).isoformat()
        runtime_state["last_email_html"] = final_state.get("email_html")

        email_sent = final_state.get("email_sent", False)
        errors = final_state.get("errors", [])
        stories = len(final_state.get("curated_stories", []))

        logger.info(
            f"=== Digest run {run_id} complete: "
            f"sent={email_sent}, stories={stories}, errors={len(errors)} ==="
        )
        if errors:
            logger.warning(f"Run {run_id} non-fatal errors: {errors}")

    except Exception as e:
        runtime_state["last_status"] = f"crashed: {str(e)[:120]}"
        runtime_state["last_run"] = datetime.now(timezone.utc).isoformat()
        logger.exception(f"=== Digest run {run_id} CRASHED: {e} ===")
        try:
            from app.database import upsert_run
            await upsert_run(
                run_id=run_id,
                status=f"crashed: {str(e)[:120]}",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )
        except Exception:
            pass