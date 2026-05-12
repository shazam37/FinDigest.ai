"""
calendar_agent — Stage 6 (final) of the digest graph.

Two responsibilities:
  1. Create the Google Calendar audit event (non-critical)
  2. Persist the completed run record to run_history in PostgreSQL

This node always runs even after a partial failure — it's the cleanup
and audit node. It reads should_abort to determine what status to log.
"""

import logging
from datetime import datetime, timezone

from app.graph.state import DigestState
from app.gmail import create_calendar_confirmation
from app.database import upsert_run

logger = logging.getLogger(__name__)


async def calendar_agent(state: DigestState) -> dict:
    """Logs the calendar event and persists the run to PostgreSQL."""
    run_id = state["run_id"]
    logger.info(f"[calendar_agent] run_id={run_id}")

    subject = state.get("email_subject", "")
    story_count = len(state.get("curated_stories", []))
    email_sent = state.get("email_sent", False)
    should_abort = state.get("should_abort", False)
    abort_reason = state.get("abort_reason", "")
    errors = state.get("errors", [])
    started_at = state.get("started_at")
    finished_at = datetime.now(timezone.utc)

    duration_s = None
    if started_at:
        duration_s = (finished_at - started_at).total_seconds()

    # Determine final status string
    if email_sent:
        status = "success"
    elif should_abort:
        status = f"aborted: {abort_reason[:80]}"
    elif errors:
        status = f"failed: {errors[-1][:80]}"
    else:
        status = "unknown"

    # --- Persist run to DB ---
    try:
        await upsert_run(
            run_id=run_id,
            status=status,
            stories=story_count,
            subject=subject or None,
            error_msg="; ".join(errors) if errors else None,
            started_at=started_at,
            finished_at=finished_at,
            duration_s=duration_s,
        )
        logger.info(f"[calendar_agent] Run persisted: {status}")
    except Exception as e:
        logger.error(f"[calendar_agent] DB persist failed: {e}")

    # --- Google Calendar (non-critical, only on success) ---
    calendar_logged = False
    if email_sent and subject:
        try:
            calendar_logged = create_calendar_confirmation(subject, story_count)
        except Exception as e:
            logger.warning(f"[calendar_agent] Calendar event failed (non-critical): {e}")

    # --- Update in-memory state for dashboard ---
    from app.graph.runtime_state import runtime_state
    runtime_state["last_run"] = finished_at.strftime("%Y-%m-%d %H:%M UTC")
    runtime_state["last_status"] = (
        "✅ Sent successfully" if email_sent
        else f"⚠️ {abort_reason[:60]}" if should_abort
        else "❌ Failed"
    )
    runtime_state["stories_found"] = story_count
    runtime_state["run_history"].append({
        "timestamp": runtime_state["last_run"],
        "stories": story_count,
        "status": status,
        "run_id": run_id,
        "duration_s": round(duration_s, 1) if duration_s else None,
    })
    runtime_state["run_history"] = runtime_state["run_history"][-30:]

    return {"calendar_logged": calendar_logged}