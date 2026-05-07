"""
Run this ONCE before deploying to Render (or let the app auto-run it on startup).
Creates all Phase 1 and Phase 2 tables idempotently.

Usage:
    DATABASE_URL=postgresql://... python scripts/setup_database.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


async def main():
    from app.database import (
        init_pool, close_pool,
        create_schema, create_phase2_schema,
        get_or_create_default_user,
    )

    print("Connecting to database...")
    await init_pool()

    print("Creating Phase 1 schema...")
    await create_schema()

    print("Creating Phase 2 schema...")
    await create_phase2_schema()

    print("Ensuring default user exists...")
    uid = await get_or_create_default_user()
    print(f"  Default user id={uid}")

    print("\n✅ Database ready. Tables created:")
    print("  Phase 1:")
    print("    - story_memory        (pgvector embeddings for deduplication)")
    print("    - run_history         (persistent agent run log)")
    print("    - alert_history       (sent breaking alerts — prevents re-sending)")
    print("  Phase 2:")
    print("    - users               (multi-user support with role-based preferences)")
    print("    - story_feedback      (thumbs up/down signals per story per user)")
    print("    - user_preferences    (materialised preference profile)")
    print("    - watchlist_entities  (per-user entity/topic watch targets)")
    print("    - entity_sentiment    (rolling sentiment scores per watched entity)")
    print("\n  LangGraph will create its own checkpoint tables on first graph run.")

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())