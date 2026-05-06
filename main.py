"""
app/main.py — FastAPI application with Phase 1 + Phase 2 wiring.

Lifespan:
  1. Open DB connection pool
  2. Create Phase 1 + Phase 2 schema (idempotent)
  3. Ensure default user exists
  4. Build LangGraph digest graph (with PostgresSaver)
  5. Build LangGraph alert graph
  6. Start APScheduler:
       - Daily digest @ 9:00 AM
       - Alert check every ALERT_POLL_HOURS hours
       - Weekly synthesis every Friday @ SYNTHESIS_HOUR AM

Phase 2 new endpoints (via routers):
  /feedback                    — one-click story feedback (from email links)
  /feedback/stats              — feedback statistics for a user
  /watchlist                   — CRUD for entity watchlists
  /watchlist/sentiment         — sentiment history for all watched entities
  /users                       — user management
  /users/run-digest            — trigger digest for all users
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from app.config import settings
from app.state import agent_state
from app.database import (
    init_pool, close_pool,
    create_schema, create_phase2_schema,
    fetch_run_history, get_or_create_default_user,
)
from app.graph.digest_graph import build_graph, run_fintech_digest
from app.alert_graph import build_alert_graph, run_alert_check
from app.synthesis_graph import run_weekly_synthesis
from app.routers import feedback, watchlist, users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=pytz.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 1. Database ────────────────────────────────────────────────────────
    await init_pool()
    await create_schema()           # Phase 1 tables
    await create_phase2_schema()    # Phase 2 tables

    # Ensure default user exists (single-user mode works out of the box)
    try:
        default_uid = await get_or_create_default_user()
        logger.info(f"Default user id={default_uid} ({settings.RECIPIENT_EMAIL})")
    except Exception as e:
        logger.error(f"Could not create default user: {e}")

    # ── 2. LangGraph graphs ────────────────────────────────────────────────
    await build_graph()
    await build_alert_graph()

    # ── 3. Scheduler ────────────────────────────────────────────────────────
    tz = pytz.timezone(settings.USER_TIMEZONE)

    # Daily digest — 9:00 AM
    scheduler.add_job(
        run_fintech_digest,
        CronTrigger(hour=9, minute=0, timezone=tz),
        id="daily_digest",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Breaking alert check — every N hours
    scheduler.add_job(
        run_alert_check,
        IntervalTrigger(hours=settings.ALERT_POLL_HOURS),
        id="alert_check",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Weekly synthesis — Friday at SYNTHESIS_HOUR AM
    scheduler.add_job(
        run_weekly_synthesis,
        CronTrigger(
            day_of_week=settings.SYNTHESIS_DAY_OF_WEEK,
            hour=settings.SYNTHESIS_HOUR,
            minute=0,
            timezone=tz,
        ),
        id="weekly_synthesis",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started — "
        f"daily digest 9:00 AM {settings.USER_TIMEZONE} · "
        f"alerts every {settings.ALERT_POLL_HOURS}h · "
        f"synthesis {settings.SYNTHESIS_DAY_OF_WEEK.upper()} {settings.SYNTHESIS_HOUR}:00 AM"
    )

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────
    scheduler.shutdown()
    await close_pool()


app = FastAPI(
    title="FinTech Intelligence Agent",
    description="LangGraph-powered multi-agent fintech news briefing system",
    lifespan=lifespan,
)

# ── Register Phase 2 routers ─────────────────────────────────────────────────
app.include_router(feedback.router)
app.include_router(watchlist.router)
app.include_router(users.router)


# ── Dashboard ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    last_run = agent_state.get("last_run", "Never")
    last_status = agent_state.get("last_status", "—")
    stories_found = agent_state.get("stories_found", 0)
    history = agent_state.get("run_history", [])[-5:][::-1]

    rows = ""
    for r in history:
        icon = "✅" if "success" in r.get("status", "") else "❌"
        dur = f"{r['duration_s']}s" if r.get("duration_s") else "—"
        rows += (
            f"<tr><td>{r['timestamp']}</td>"
            f"<td>{icon} {r['status'][:40]}</td>"
            f"<td>{r['stories']}</td>"
            f"<td>{dur}</td></tr>"
        )

    return f"""<!DOCTYPE html>
<html>
<head><title>FinTech Agent</title>
<style>
  body{{font-family:monospace;padding:2rem;background:#0a0a0a;color:#e0e0e0;max-width:960px;margin:0 auto}}
  h2{{color:#60a5fa}} h3{{color:#94a3b8;font-size:.9rem;margin-top:2rem}}
  a{{color:#60a5fa}} .ok{{color:#4ade80}} .err{{color:#f87171}}
  table{{width:100%;border-collapse:collapse;font-size:.85rem;margin-top:.5rem}}
  td,th{{padding:6px 10px;border:1px solid #1e293b;text-align:left}}
  th{{background:#0f172a;color:#94a3b8}}
  .badge{{background:#1e3a5f;color:#60a5fa;padding:2px 8px;border-radius:12px;font-size:.75rem;margin-right:4px}}
  .badge2{{background:#1a3a2e;color:#4ade80;padding:2px 8px;border-radius:12px;font-size:.75rem}}
</style>
</head>
<body>
<h2>🏦 FinTech Intelligence Agent</h2>
<span class="badge">LangGraph + PostgreSQL</span>
<span class="badge">Phase 1 + Phase 2</span>
<span class="badge2">Preference Learning</span>

<p style="margin-top:1rem">
  Status: <strong class="{'ok' if 'success' in last_status else 'err'}">{last_status}</strong><br>
  Last run: {last_run} &nbsp;·&nbsp; Stories: {stories_found}<br>
  Timezone: {settings.USER_TIMEZONE} &nbsp;·&nbsp;
  Daily digest: 9:00 AM &nbsp;·&nbsp;
  Alerts: every {settings.ALERT_POLL_HOURS}h &nbsp;·&nbsp;
  Synthesis: {settings.SYNTHESIS_DAY_OF_WEEK.upper()} {settings.SYNTHESIS_HOUR}:00 AM
</p>

<h3>DIGEST</h3>
<p>
  <a href="/run-now">▶ Trigger digest now</a> &nbsp;|&nbsp;
  <a href="/preview">👁 Preview last email</a> &nbsp;|&nbsp;
  <a href="/synthesis-now">📋 Trigger weekly synthesis</a>
</p>

<h3>ALERTS</h3>
<p><a href="/alert-now">🚨 Trigger alert check now</a></p>

<h3>PHASE 2 — PERSONALISATION</h3>
<p>
  <a href="/feedback/stats">📊 Feedback stats</a> &nbsp;|&nbsp;
  <a href="/watchlist">👁 Watchlist</a> &nbsp;|&nbsp;
  <a href="/watchlist/sentiment">📈 Sentiment data</a> &nbsp;|&nbsp;
  <a href="/users">👥 Users</a>
</p>

<h3>SYSTEM</h3>
<p>
  <a href="/runs">📋 Run history (JSON)</a> &nbsp;|&nbsp;
  <a href="/health">❤ Health check</a> &nbsp;|&nbsp;
  <a href="/docs">📖 API docs</a>
</p>

<h3>RECENT RUNS</h3>
<table>
  <tr><th>Timestamp</th><th>Status</th><th>Stories</th><th>Duration</th></tr>
  {rows if rows else '<tr><td colspan="4">No runs yet</td></tr>'}
</table>
</body></html>"""


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    from app.graph.digest_graph import _graph
    from app.database import get_pool
    return {
        "status": "ok",
        "scheduler_running": scheduler.running,
        "graph_ready": _graph is not None,
        "db_pool_open": not get_pool().closed,
        "phase": 2,
    }


# ── Manual triggers ──────────────────────────────────────────────────────────

@app.get("/run-now")
async def trigger_now(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_fintech_digest)
    return {"message": "Digest triggered. Check /preview in ~60 seconds."}


@app.get("/alert-now")
async def trigger_alert(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_alert_check)
    return {"message": "Alert check triggered in background."}


@app.get("/synthesis-now")
async def trigger_synthesis(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_weekly_synthesis)
    return {"message": "Weekly synthesis triggered in background."}


# ── Preview ──────────────────────────────────────────────────────────────────

@app.get("/preview", response_class=HTMLResponse)
async def preview_last_email():
    html = agent_state.get("last_email_html")
    if not html:
        raise HTTPException(status_code=404, detail="No digest yet. Hit /run-now first.")
    return html


# ── Run history ──────────────────────────────────────────────────────────────

@app.get("/runs")
async def list_runs(limit: int = 30):
    try:
        rows = await fetch_run_history(limit=limit)
        for r in rows:
            for k, v in r.items():
                if isinstance(v, datetime):
                    r[k] = v.isoformat()
        return JSONResponse(content={"runs": rows, "count": len(rows)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))