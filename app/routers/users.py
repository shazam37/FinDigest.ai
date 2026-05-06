"""
app/routers/users.py

User management endpoints for multi-user digest dispatch.

Endpoints:
  GET  /users          — list all users
  POST /users          — create a user
  PUT  /users/{id}     — update user role / timezone
  GET  /users/{id}/preferences — get preference profile for a user
  POST /users/run-digest       — trigger digest for ALL active users
"""

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional

from app.database import get_conn, fetch_all_active_users, fetch_preference_profile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])

VALID_ROLES = {"executive", "risk_officer", "product_lead", "investor"}


class UserCreateRequest(BaseModel):
    email: str
    name: Optional[str] = None
    role: str = "executive"
    timezone: str = "Asia/Kolkata"


class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    timezone: Optional[str] = None
    active: Optional[bool] = None


@router.get("")
async def list_users():
    """List all users."""
    users = await fetch_all_active_users()
    return {"users": users, "count": len(users)}


@router.post("")
async def create_user(body: UserCreateRequest):
    """Create a new user for multi-user digest dispatch."""
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{body.role}'. Must be one of: {', '.join(VALID_ROLES)}",
        )

    async with get_conn() as conn:
        # Check for duplicate email
        existing = await (await conn.execute(
            "SELECT id FROM users WHERE email = %s", (body.email,)
        )).fetchone()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"User with email '{body.email}' already exists (id={existing[0]})",
            )

        row = await (await conn.execute(
            """
            INSERT INTO users (email, name, role, timezone)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (body.email, body.name, body.role, body.timezone),
        )).fetchone()
        await conn.commit()

    logger.info(f"[users] Created user {row[0]}: {body.email} ({body.role})")
    return {
        "id": row[0],
        "email": body.email,
        "name": body.name,
        "role": body.role,
        "timezone": body.timezone,
        "message": "User created. They will receive the next daily digest.",
    }


@router.put("/{user_id}")
async def update_user(user_id: int, body: UserUpdateRequest):
    """Update a user's role, timezone, name, or active status."""
    if body.role and body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}",
        )

    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.role is not None:
        updates["role"] = body.role
    if body.timezone is not None:
        updates["timezone"] = body.timezone
    if body.active is not None:
        updates["active"] = body.active

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [user_id]

    async with get_conn() as conn:
        result = await conn.execute(
            f"UPDATE users SET {set_clause} WHERE id = %s", values
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        await conn.commit()

    return {"id": user_id, "updated": updates}


@router.get("/{user_id}/preferences")
async def get_user_preferences(user_id: int):
    """Return the current preference profile for a user."""
    profile = await fetch_preference_profile(user_id)
    if not profile:
        from app.config import settings
        return {
            "user_id": user_id,
            "profile_active": False,
            "message": f"Profile not yet active. Requires {settings.MIN_FEEDBACK_FOR_PROFILE} feedback signals.",
        }
    return {
        "user_id": user_id,
        "profile_active": True,
        "profile": profile,
    }


@router.post("/run-digest")
async def run_digest_all_users(background_tasks: BackgroundTasks):
    """
    Trigger a personalised digest run for ALL active users.
    Each user gets their own LangGraph run with their own preference profile
    and watchlist injected.
    """
    users = await fetch_all_active_users()
    if not users:
        raise HTTPException(status_code=404, detail="No active users found")

    from app.graph.digest_graph import run_fintech_digest

    for user in users:
        background_tasks.add_task(run_fintech_digest, user_id=user["id"])
        logger.info(f"[users] Queued digest run for user {user['id']} ({user['email']})")

    return {
        "message": f"Digest triggered for {len(users)} user(s)",
        "users": [{"id": u["id"], "email": u["email"]} for u in users],
    }