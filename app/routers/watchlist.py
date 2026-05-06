"""
app/routers/watchlist.py

CRUD API for managing a user's watchlist of entities/topics.

Endpoints:
  GET  /watchlist              — list all watched entities
  POST /watchlist              — add an entity
  DELETE /watchlist/{id}       — remove an entity
  GET  /watchlist/sentiment    — sentiment history for all watched entities
  GET  /watchlist/sentiment/{entity} — sentiment trend for a specific entity
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config import settings
from app.database import (
    fetch_watchlist,
    add_watchlist_entity,
    remove_watchlist_entity,
    fetch_sentiment_window,
    get_or_create_default_user,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistAddRequest(BaseModel):
    entity: str
    entity_type: str = "company"   # company | regulator | topic | person


class WatchlistAddResponse(BaseModel):
    id: int
    entity: str
    entity_type: str
    message: str


@router.get("")
async def list_watchlist(user_id: int = Query(default=1)):
    """Return all active watchlist entities for a user."""
    entities = await fetch_watchlist(user_id)
    # Serialise datetimes
    for e in entities:
        if isinstance(e.get("created_at"), datetime):
            e["created_at"] = e["created_at"].isoformat()
    return {"entities": entities, "count": len(entities)}


@router.post("", response_model=WatchlistAddResponse)
async def add_to_watchlist(
    body: WatchlistAddRequest,
    user_id: int = Query(default=1),
):
    """Add an entity to the watchlist."""
    # Validate max entities
    existing = await fetch_watchlist(user_id)
    if len(existing) >= settings.MAX_WATCHLIST_ENTITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Watchlist limit reached ({settings.MAX_WATCHLIST_ENTITIES} entities max). "
                   "Remove an entity first.",
        )

    entity = body.entity.strip()
    if not entity:
        raise HTTPException(status_code=400, detail="Entity name cannot be empty")

    entity_id = await add_watchlist_entity(user_id, entity, body.entity_type)
    logger.info(f"[watchlist] Added '{entity}' ({body.entity_type}) for user {user_id}")

    return WatchlistAddResponse(
        id=entity_id,
        entity=entity,
        entity_type=body.entity_type,
        message=f"'{entity}' added to watchlist. It will appear in your next digest.",
    )


@router.delete("/{entity_id}")
async def remove_from_watchlist(entity_id: int, user_id: int = Query(default=1)):
    """Remove an entity from the watchlist (soft-delete)."""
    await remove_watchlist_entity(user_id, entity_id)
    logger.info(f"[watchlist] Removed entity {entity_id} for user {user_id}")
    return {"message": f"Entity {entity_id} removed from watchlist"}


@router.get("/sentiment")
async def get_all_sentiment(
    user_id: int = Query(default=1),
    days: int = Query(default=30, ge=1, le=90),
):
    """Return sentiment history for all watched entities."""
    entities = await fetch_watchlist(user_id)
    result = {}

    for e in entities:
        entity_name = e["entity"]
        scores = await fetch_sentiment_window(entity_name, days=days)
        if scores:
            avg = sum(s["score"] for s in scores) / len(scores)
            result[entity_name] = {
                "average_score": round(avg, 3),
                "data_points": len(scores),
                "entity_type": e["entity_type"],
                "recent_scores": [
                    {
                        "score": s["score"],
                        "title": s["title"],
                        "scored_at": s["scored_at"].isoformat()
                        if isinstance(s["scored_at"], datetime) else s["scored_at"],
                    }
                    for s in scores[:10]
                ],
            }
        else:
            result[entity_name] = {
                "average_score": None,
                "data_points": 0,
                "entity_type": e["entity_type"],
                "recent_scores": [],
            }

    return {"entities": result, "window_days": days}


@router.get("/sentiment/{entity}")
async def get_entity_sentiment(
    entity: str,
    days: int = Query(default=30, ge=1, le=90),
):
    """Return the full sentiment history for a specific entity."""
    scores = await fetch_sentiment_window(entity, days=days)
    if not scores:
        return {"entity": entity, "scores": [], "average": None, "window_days": days}

    avg = sum(s["score"] for s in scores) / len(scores)

    # Compute 48h average vs full-window baseline for velocity
    recent_48h = [s for s in scores if _is_recent(s["scored_at"], hours=48)]
    recent_avg = sum(s["score"] for s in recent_48h) / len(recent_48h) if recent_48h else None
    delta = round(recent_avg - avg, 3) if recent_avg is not None else None

    return {
        "entity": entity,
        "window_days": days,
        "average_score": round(avg, 3),
        "recent_48h_average": round(recent_avg, 3) if recent_avg is not None else None,
        "velocity_delta": delta,
        "data_points": len(scores),
        "scores": [
            {
                "score": s["score"],
                "title": s["title"],
                "scored_at": s["scored_at"].isoformat()
                if isinstance(s["scored_at"], datetime) else s["scored_at"],
            }
            for s in scores
        ],
    }


def _is_recent(scored_at, hours: int) -> bool:
    """Check if a scored_at timestamp is within the last N hours."""
    from datetime import timezone, timedelta
    if not scored_at:
        return False
    if isinstance(scored_at, str):
        try:
            scored_at = datetime.fromisoformat(scored_at)
        except Exception:
            return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    if scored_at.tzinfo is None:
        scored_at = scored_at.replace(tzinfo=timezone.utc)
    return scored_at >= cutoff