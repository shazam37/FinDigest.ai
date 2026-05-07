"""
app/main.py — FastAPI application — Phase 1 + 2 + 3.

Lifespan startup sequence:
  1. LangSmith tracing (if configured)
  2. DB pool + Phase 1/2/3 schema
  3. Default user
  4. LangGraph digest + alert graphs
  5. APScheduler:
       - Daily digest       9:00 AM (user timezone)
       - Alert check        every ALERT_POLL_HOURS
       - Weekly synthesis   Friday SYNTHESIS_HOUR AM
       - Health report      Monday HEALTH_REPORT_HOUR AM

Phase 3 additions:
  /dashboard/*           — self-serve web dashboard (Jinja2 + HTMX)
  /chat                  — conversational Q&A (RAG)
  /research              — deep-dive research + PDF
  /telegram/webhook      — Telegram bot webhook
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from app.config import settings
from app.state import agent_state
from app.database import (
    init_pool, close_pool,
    create_schema, create_phase2_schema, create_phase3_schema,
    fetch_run_history, get_or_create_default_user,
)
from app.graph.digest_graph import build_graph, run_fintech_digest
from app.alert_graph import build_alert_graph, run_alert_check
from app.synthesis_graph import run_weekly_synthesis
from app.observability import setup_langsmith, run_health_report
from app.routers import feedback, watchlist, users
from app.routers import chat, research, dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=pytz.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 1. Observability ───────────────────────────────────────────────────
    setup_langsmith()

    # ── 2. Database ────────────────────────────────────────────────────────
    await init_pool()
    await create_schema()
    await create_phase2_schema()
    await create_phase3_schema()

    try:
        default_uid = await get_or_create_default_user()
        logger.info(f"Default user id={default_uid} ({settings.RECIPIENT_EMAIL})")
    except Exception as e:
        logger.error(f"Could not create default user: {e}")

    # ── 3. LangGraph ───────────────────────────────────────────────────────
    await build_graph()
    await build_alert_graph()

    # ── 4. Scheduler ───────────────────────────────────────────────────────
    tz = pytz.timezone(settings.USER_TIMEZONE)

    scheduler.add_job(
        run_fintech_digest,
        CronTrigger(hour=9, minute=0, timezone=tz),
        id="daily_digest", replace_existing=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        run_alert_check,
        IntervalTrigger(hours=settings.ALERT_POLL_HOURS),
        id="alert_check", replace_existing=True, misfire_grace_time=300,
    )
    scheduler.add_job(
        run_weekly_synthesis,
        CronTrigger(day_of_week=settings.SYNTHESIS_DAY_OF_WEEK,
                    hour=settings.SYNTHESIS_HOUR, minute=0, timezone=tz),
        id="weekly_synthesis", replace_existing=True, misfire_grace_time=1800,
    )
    scheduler.add_job(
        run_health_report,
        CronTrigger(day_of_week="mon",
                    hour=settings.HEALTH_REPORT_HOUR, minute=0, timezone=tz),
        id="health_report", replace_existing=True, misfire_grace_time=1800,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started — digest 9AM · alerts every {settings.ALERT_POLL_HOURS}h · "
        f"synthesis {settings.SYNTHESIS_DAY_OF_WEEK.upper()} · health report MON"
    )

    yield

    scheduler.shutdown()
    await close_pool()


app = FastAPI(
    title="FinTech Intelligence Agent",
    description="LangGraph-powered multi-agent fintech news briefing system — Phase 1+2+3",
    lifespan=lifespan,
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(feedback.router)
app.include_router(watchlist.router)
app.include_router(users.router)
app.include_router(chat.router)
app.include_router(research.router)
app.include_router(dashboard.router)


# ── Telegram webhook ──────────────────────────────────────────────────────────

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """
    Receives updates from the Telegram Bot API.
    Register this URL with: python scripts/setup_telegram.py
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        return {"ok": False, "reason": "Telegram not configured"}
    try:
        body = await request.json()
        from app.delivery.telegram import handle_webhook
        import asyncio
        asyncio.create_task(handle_webhook(body))
        return {"ok": True}
    except Exception as e:
        logger.error(f"[telegram webhook] Error: {e}")
        return {"ok": False}


# ── Root (legacy monospace dashboard) ────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirect to the Phase 3 web dashboard."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard", status_code=302)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    from app.graph.digest_graph import _graph
    from app.database import get_pool
    from app.config import settings as s
    return {
        "status": "ok",
        "phase": 3,
        "scheduler_running": scheduler.running,
        "graph_ready": _graph is not None,
        "db_pool_open": not get_pool().closed,
        "langsmith_enabled": bool(s.LANGSMITH_API_KEY),
        "slack_enabled": bool(s.SLACK_BOT_TOKEN),
        "telegram_enabled": bool(s.TELEGRAM_BOT_TOKEN),
    }


# ── Manual triggers ───────────────────────────────────────────────────────────

@app.get("/run-now")
async def trigger_now(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_fintech_digest)
    return {"message": "Digest triggered. Check /preview in ~60 seconds."}


@app.get("/alert-now")
async def trigger_alert(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_alert_check)
    return {"message": "Alert check triggered."}


@app.get("/synthesis-now")
async def trigger_synthesis(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_weekly_synthesis)
    return {"message": "Weekly synthesis triggered."}


@app.get("/health-report-now")
async def trigger_health_report(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_health_report)
    return {"message": "Health report triggered."}


# ── Preview / runs (kept for backwards compat) ────────────────────────────────

@app.get("/preview", response_class=HTMLResponse)
async def preview_last_email():
    html = agent_state.get("last_email_html")
    if not html:
        raise HTTPException(status_code=404, detail="No digest yet. Hit /run-now first.")
    return html


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