"""
app/routers/feedback.py

Handles story feedback clicks from email links.

Each story in the email has two links:
  GET /feedback?signal=1&url=...&title=...&source=...&run_id=...&user_id=...
  GET /feedback?signal=-1&url=...&...

These are GET requests (not POST) so they work directly when clicked in
any email client — no JS, no form submission needed.

On click:
  1. Record the signal in story_feedback table
  2. Asynchronously rebuild the user's preference profile
  3. Return a clean HTML confirmation page (not a JSON response —
     the user lands here after clicking in their email)
"""

import logging
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import HTMLResponse

from app.database import record_feedback
from app.preferences import rebuild_preference_profile

logger = logging.getLogger(__name__)
router = APIRouter()


async def _process_feedback(
    user_id: int,
    story_url: str,
    story_title: str,
    story_source: str,
    signal: int,
    run_id: str,
):
    """Background task: record feedback and rebuild preference profile."""
    try:
        await record_feedback(
            user_id=user_id,
            story_url=story_url,
            story_title=story_title,
            story_source=story_source,
            signal=signal,
            digest_run_id=run_id,
        )
        logger.info(
            f"[feedback] user={user_id} signal={signal:+d} "
            f"story='{story_title[:50]}'"
        )
    except Exception as e:
        logger.error(f"[feedback] record failed: {e}")
        return

    # Rebuild preference profile asynchronously
    try:
        await rebuild_preference_profile(user_id)
    except Exception as e:
        logger.warning(f"[feedback] profile rebuild failed (non-critical): {e}")


@router.get("/feedback", response_class=HTMLResponse)
async def record_story_feedback(
    background_tasks: BackgroundTasks,
    signal: int = Query(..., ge=-1, le=1),
    url: str = Query(...),
    title: str = Query(default=""),
    source: str = Query(default=""),
    run_id: str = Query(default=""),
    user_id: int = Query(default=1),
):
    """
    One-click feedback endpoint linked from email stories.
    Returns a friendly HTML page so the user knows their click registered.
    """
    story_url = unquote(url)
    story_title = unquote(title)
    story_source = unquote(source)

    background_tasks.add_task(
        _process_feedback,
        user_id=user_id,
        story_url=story_url,
        story_title=story_title,
        story_source=story_source,
        signal=signal,
        run_id=run_id,
    )

    emoji = "👍" if signal == 1 else "👎"
    label = "marked as useful" if signal == 1 else "marked as not relevant"
    colour = "#4ade80" if signal == 1 else "#f87171"
    msg = (
        "Your agent will prioritise similar stories in future digests."
        if signal == 1
        else "Your agent will deprioritise similar stories in future digests."
    )

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Feedback Recorded</title>
  <style>
    body{{font-family:Georgia,serif;background:#0a0a0a;color:#e0e0e0;
      display:flex;align-items:center;justify-content:center;
      min-height:100vh;margin:0;}}
    .card{{background:#1a1a2e;border:1px solid #2d3561;border-radius:8px;
      padding:2.5rem 3rem;max-width:480px;text-align:center;}}
    .emoji{{font-size:3rem;margin-bottom:1rem;}}
    h2{{color:{colour};font-size:1.3rem;margin:0 0 .5rem;}}
    p{{color:#94a3b8;font-size:.95rem;line-height:1.6;margin:.5rem 0 0;}}
    .title{{color:#c8c0e0;font-style:italic;font-size:.9rem;margin-top:1rem;
      padding-top:1rem;border-top:1px solid #2d3561;}}
    a{{color:#60a5fa;font-size:.85rem;}}
  </style>
</head>
<body>
  <div class="card">
    <div class="emoji">{emoji}</div>
    <h2>Story {label}</h2>
    <p>{msg}</p>
    <p class="title">"{story_title[:80]}{"..." if len(story_title) > 80 else ""}"</p>
    <p style="margin-top:1.5rem;">
      <a href="javascript:window.close()">Close this tab</a>
    </p>
  </div>
</body>
</html>"""


@router.get("/feedback/stats")
async def feedback_stats(user_id: int = Query(default=1)):
    """Return feedback statistics for a user — useful for the dashboard."""
    from app.database import fetch_recent_feedback, fetch_preference_profile
    from app.config import settings

    feedback = await fetch_recent_feedback(user_id, limit=settings.FEEDBACK_WINDOW)
    profile = await fetch_preference_profile(user_id)

    liked = sum(1 for f in feedback if f["signal"] == 1)
    disliked = sum(1 for f in feedback if f["signal"] == -1)

    return {
        "user_id": user_id,
        "total_signals": len(feedback),
        "liked": liked,
        "disliked": disliked,
        "profile_active": profile is not None,
        "min_for_profile": settings.MIN_FEEDBACK_FOR_PROFILE,
        "profile_summary": profile.get("profile_summary") if profile else None,
        "liked_topics": profile.get("liked_topics", []) if profile else [],
        "disliked_topics": profile.get("disliked_topics", []) if profile else [],
    }