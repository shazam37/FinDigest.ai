"""
Database module.

Manages:
  - psycopg connection pool (shared across the app)
  - Schema creation on startup (idempotent)
  - run_history table (persistent across restarts, unlike in-memory state)
  - story_memory table + pgvector extension (semantic deduplication)

The LangGraph PostgresSaver uses its own internal tables (langgraph_checkpoints)
managed automatically by the library. We don't touch those here.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import psycopg
from psycopg_pool import AsyncConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level pool — initialised in lifespan, used everywhere
_pool: AsyncConnectionPool | None = None


async def init_pool() -> AsyncConnectionPool:
    """Create the async connection pool. Called once at app startup."""
    global _pool
    _pool = AsyncConnectionPool(
        conninfo=settings.DATABASE_URL,
        min_size=2,
        max_size=10,
        open=False,
    )
    await _pool.open()
    logger.info("Database connection pool opened")
    return _pool


async def close_pool():
    """Close the pool. Called at app shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        logger.info("Database connection pool closed")


def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised. Call init_pool() first.")
    return _pool


@asynccontextmanager
async def get_conn() -> AsyncGenerator[psycopg.AsyncConnection, None]:
    """Async context manager: yields a connection from the pool."""
    async with get_pool().connection() as conn:
        yield conn


async def create_schema():
    """
    Idempotent schema creation. Safe to run every startup.
    Creates:
      - pgvector extension
      - story_memory table (stores embeddings for deduplication)
      - run_history table (persistent agent run log)
      - alert_history table (tracks sent breaking alerts to avoid repeats)
    """
    async with get_conn() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS story_memory (
                id          SERIAL PRIMARY KEY,
                url         TEXT UNIQUE NOT NULL,
                title       TEXT NOT NULL,
                source      TEXT,
                embedding   vector(384),          -- all-MiniLM-L6-v2 dimension
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Index for fast cosine similarity search
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS story_memory_embedding_idx
            ON story_memory
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 50)
        """)

        # Index for fast time-based lookups (memory window queries)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS story_memory_created_idx
            ON story_memory (created_at DESC)
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS run_history (
                id          SERIAL PRIMARY KEY,
                run_id      TEXT UNIQUE NOT NULL,
                status      TEXT NOT NULL,
                stories     INTEGER DEFAULT 0,
                subject     TEXT,
                error_msg   TEXT,
                started_at  TIMESTAMPTZ NOT NULL,
                finished_at TIMESTAMPTZ,
                duration_s  FLOAT
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id          SERIAL PRIMARY KEY,
                url         TEXT UNIQUE NOT NULL,
                title       TEXT NOT NULL,
                urgency     INTEGER NOT NULL,
                sent_at     TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.commit()
        logger.info("Database schema ready")


async def upsert_run(
    run_id: str,
    status: str,
    stories: int = 0,
    subject: str | None = None,
    error_msg: str | None = None,
    started_at=None,
    finished_at=None,
    duration_s: float | None = None,
):
    """Insert or update a run_history row."""
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO run_history
                (run_id, status, stories, subject, error_msg, started_at, finished_at, duration_s)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE SET
                status      = EXCLUDED.status,
                stories     = EXCLUDED.stories,
                subject     = EXCLUDED.subject,
                error_msg   = EXCLUDED.error_msg,
                finished_at = EXCLUDED.finished_at,
                duration_s  = EXCLUDED.duration_s
            """,
            (run_id, status, stories, subject, error_msg, started_at, finished_at, duration_s),
        )
        await conn.commit()


async def fetch_run_history(limit: int = 30) -> list[dict]:
    """Return the most recent runs for the dashboard."""
    async with get_conn() as conn:
        rows = await conn.execute(
            "SELECT * FROM run_history ORDER BY started_at DESC LIMIT %s",
            (limit,),
        )
        cols = [d.name for d in rows.description]
        return [dict(zip(cols, row)) for row in await rows.fetchall()]


async def was_alert_sent(url: str) -> bool:
    """Check if a breaking alert for this URL was already sent."""
    async with get_conn() as conn:
        row = await (await conn.execute(
            "SELECT 1 FROM alert_history WHERE url = %s", (url,)
        )).fetchone()
        return row is not None


async def record_alert_sent(url: str, title: str, urgency: int):
    """Mark a breaking alert as sent so we don't re-send it."""
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO alert_history (url, title, urgency)
            VALUES (%s, %s, %s)
            ON CONFLICT (url) DO NOTHING
            """,
            (url, title, urgency),
        )
        await conn.commit()

async def fetch_run_by_id(run_id: str) -> dict | None:
    """Fetch a single run by run_id (for preview + debugging)."""
    async with get_conn() as conn:
        result = await conn.execute(
            "SELECT * FROM run_history WHERE run_id = %s",
            (run_id,),
        )

        row = await result.fetchone()

        if not row:
            return None

        cols = [d.name for d in result.description]
        return dict(zip(cols, row))

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2 schema additions
# ═══════════════════════════════════════════════════════════════════════════════

async def create_phase2_schema():
    """
    Idempotent Phase 2 table creation. Called from create_schema() on startup.

    New tables:
      - users              : multi-user support with role-based topic preferences
      - story_feedback     : thumbs up/down signals per story per user
      - user_preferences   : materialised preference profile (rebuilt from feedback)
      - watchlist_entities : per-user entity/topic watch targets
      - entity_sentiment   : rolling sentiment scores per watched entity
    """
    async with get_conn() as conn:

        # ── Users ──────────────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id           SERIAL PRIMARY KEY,
                email        TEXT UNIQUE NOT NULL,
                name         TEXT,
                role         TEXT DEFAULT 'executive',
                -- role drives default topic weights:
                -- 'executive'    → balanced across all topics
                -- 'risk_officer' → compliance, fraud, regulation weighted higher
                -- 'product_lead' → innovation, API, product launches weighted higher
                -- 'investor'     → M&A, funding, market entry weighted higher
                timezone     TEXT DEFAULT 'Asia/Kolkata',
                active       BOOLEAN DEFAULT TRUE,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # ── Story feedback ─────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS story_feedback (
                id           SERIAL PRIMARY KEY,
                user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
                story_url    TEXT NOT NULL,
                story_title  TEXT NOT NULL,
                story_source TEXT,
                -- Topics extracted from the story (comma-separated)
                topics       TEXT,
                signal       SMALLINT NOT NULL CHECK (signal IN (1, -1)),
                -- 1 = thumbs up, -1 = thumbs down
                digest_run_id TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, story_url)
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS story_feedback_user_idx
            ON story_feedback (user_id, created_at DESC)
        """)

        # ── User preference profiles ───────────────────────────────────────────
        # Materialised view of what each user likes — rebuilt after each feedback signal
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                -- JSON blob: {"liked_topics": [...], "disliked_topics": [...],
                --             "liked_sources": [...], "disliked_sources": [...],
                --             "profile_summary": "plain text for LLM injection"}
                profile_json    JSONB NOT NULL DEFAULT '{}',
                feedback_count  INTEGER DEFAULT 0,
                last_updated    TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # ── Watchlist entities ─────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist_entities (
                id           SERIAL PRIMARY KEY,
                user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
                entity       TEXT NOT NULL,
                -- entity type: 'company' | 'regulator' | 'topic' | 'person'
                entity_type  TEXT DEFAULT 'company',
                active       BOOLEAN DEFAULT TRUE,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, entity)
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS watchlist_user_idx
            ON watchlist_entities (user_id) WHERE active = TRUE
        """)

        # ── Entity sentiment history ───────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS entity_sentiment (
                id           SERIAL PRIMARY KEY,
                entity       TEXT NOT NULL,
                -- Sentiment score: -1.0 (very negative) → +1.0 (very positive)
                score        FLOAT NOT NULL,
                story_url    TEXT,
                story_title  TEXT,
                scored_at    TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS entity_sentiment_entity_idx
            ON entity_sentiment (entity, scored_at DESC)
        """)

        await conn.commit()
        logger.info("Phase 2 database schema ready")


# ── User helpers ───────────────────────────────────────────────────────────────

async def get_or_create_default_user() -> int:
    """
    Ensure the default user (settings.RECIPIENT_EMAIL) exists.
    Returns the user_id. Called at startup so the system works
    single-user out of the box.
    """
    from app.config import settings
    async with get_conn() as conn:
        row = await (await conn.execute(
            "SELECT id FROM users WHERE email = %s", (settings.RECIPIENT_EMAIL,)
        )).fetchone()
        if row:
            return row[0]
        row = await (await conn.execute(
            "INSERT INTO users (email, name) VALUES (%s, %s) RETURNING id",
            (settings.RECIPIENT_EMAIL, "Default User"),
        )).fetchone()
        await conn.commit()
        return row[0]


async def fetch_all_active_users() -> list[dict]:
    """Return all active users for multi-user digest dispatch."""
    async with get_conn() as conn:
        rows = await (await conn.execute(
            "SELECT id, email, name, role, timezone FROM users WHERE active = TRUE"
        )).fetchall()
        return [
            {"id": r[0], "email": r[1], "name": r[2], "role": r[3], "timezone": r[4]}
            for r in rows
        ]


# ── Feedback helpers ───────────────────────────────────────────────────────────

async def record_feedback(
    user_id: int,
    story_url: str,
    story_title: str,
    story_source: str,
    signal: int,
    topics: str = "",
    digest_run_id: str = "",
):
    """Record a thumbs up (1) or thumbs down (-1) signal."""
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO story_feedback
                (user_id, story_url, story_title, story_source, topics, signal, digest_run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, story_url) DO UPDATE SET
                signal     = EXCLUDED.signal,
                created_at = NOW()
            """,
            (user_id, story_url, story_title, story_source, topics, signal, digest_run_id),
        )
        await conn.commit()


async def fetch_recent_feedback(user_id: int, limit: int = 50) -> list[dict]:
    """Fetch the most recent feedback signals for preference profile building."""
    async with get_conn() as conn:
        rows = await (await conn.execute(
            """
            SELECT story_url, story_title, story_source, topics, signal, created_at
            FROM story_feedback
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )).fetchall()
        return [
            {
                "url": r[0], "title": r[1], "source": r[2],
                "topics": r[3], "signal": r[4], "created_at": r[5],
            }
            for r in rows
        ]


async def upsert_preference_profile(user_id: int, profile: dict, feedback_count: int):
    """Save the computed preference profile JSON for a user."""
    import json
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO user_preferences (user_id, profile_json, feedback_count, last_updated)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                profile_json   = EXCLUDED.profile_json,
                feedback_count = EXCLUDED.feedback_count,
                last_updated   = NOW()
            """,
            (user_id, json.dumps(profile), feedback_count),
        )
        await conn.commit()


async def fetch_preference_profile(user_id: int) -> dict | None:
    """Load the stored preference profile for LLM injection. Returns None if insufficient data."""
    import json
    from app.config import settings
    async with get_conn() as conn:
        row = await (await conn.execute(
            "SELECT profile_json, feedback_count FROM user_preferences WHERE user_id = %s",
            (user_id,),
        )).fetchone()
        if not row:
            return None
        if row[1] < settings.MIN_FEEDBACK_FOR_PROFILE:
            return None   # Not enough signals yet
        return json.loads(row[0])


# ── Watchlist helpers ──────────────────────────────────────────────────────────

async def fetch_watchlist(user_id: int) -> list[dict]:
    """Return active watchlist entities for a user."""
    async with get_conn() as conn:
        rows = await (await conn.execute(
            """
            SELECT id, entity, entity_type, created_at
            FROM watchlist_entities
            WHERE user_id = %s AND active = TRUE
            ORDER BY entity
            """,
            (user_id,),
        )).fetchall()
        return [
            {"id": r[0], "entity": r[1], "entity_type": r[2], "created_at": r[3]}
            for r in rows
        ]


async def add_watchlist_entity(user_id: int, entity: str, entity_type: str = "company") -> int:
    async with get_conn() as conn:
        row = await (await conn.execute(
            """
            INSERT INTO watchlist_entities (user_id, entity, entity_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, entity) DO UPDATE SET active = TRUE
            RETURNING id
            """,
            (user_id, entity.strip(), entity_type),
        )).fetchone()
        await conn.commit()
        return row[0]


async def remove_watchlist_entity(user_id: int, entity_id: int):
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE watchlist_entities SET active = FALSE WHERE id = %s AND user_id = %s",
            (entity_id, user_id),
        )
        await conn.commit()


# ── Sentiment helpers ──────────────────────────────────────────────────────────

async def record_sentiment(entity: str, score: float, story_url: str, story_title: str):
    async with get_conn() as conn:
        await conn.execute(
            "INSERT INTO entity_sentiment (entity, score, story_url, story_title) VALUES (%s,%s,%s,%s)",
            (entity, score, story_url, story_title),
        )
        await conn.commit()


async def fetch_sentiment_window(entity: str, days: int) -> list[dict]:
    """Return recent sentiment scores for an entity."""
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with get_conn() as conn:
        rows = await (await conn.execute(
            """
            SELECT score, story_title, scored_at
            FROM entity_sentiment
            WHERE entity = %s AND scored_at >= %s
            ORDER BY scored_at DESC
            """,
            (entity, cutoff),
        )).fetchall()
        return [{"score": r[0], "title": r[1], "scored_at": r[2]} for r in rows]