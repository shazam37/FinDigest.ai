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

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from app.config import settings
from app.state import agent_state
from app.database import (
    init_pool, close_pool,
    create_schema, create_phase2_schema, create_phase3_schema,
    create_onboarding_schema,
    fetch_run_history, get_or_create_default_user,
)
from app.graph.digest_graph import build_graph, run_fintech_digest
from app.alert_graph import build_alert_graph, run_alert_check
from app.synthesis_graph import run_weekly_synthesis
from app.observability import setup_langsmith, run_health_report
from app.demo import is_demo_mode, get_demo_email_html, DEMO_RUN_HISTORY
from app.routers import feedback, watchlist, users, chat, research, dashboard
from app.routers.subscribe import router as subscribe_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=pytz.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_langsmith()

    await init_pool()
    await create_schema()
    await create_phase2_schema()
    await create_phase3_schema()
    await create_onboarding_schema()

    try:
        default_uid = await get_or_create_default_user()
        logger.info(f"Default user id={default_uid} ({settings.RECIPIENT_EMAIL})")
    except Exception as e:
        logger.error(f"Could not create default user: {e}")

    await build_graph()
    await build_alert_graph()

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
    demo_note = " [DEMO MODE]" if is_demo_mode() else ""
    logger.info(
        f"Startup complete{demo_note} — "
        f"digest 9AM · alerts every {settings.ALERT_POLL_HOURS}h · "
        f"synthesis {settings.SYNTHESIS_DAY_OF_WEEK.upper()} · health MON"
    )

    yield

    scheduler.shutdown()
    await close_pool()


app = FastAPI(
    title="FinTech Intelligence Agent",
    description="LangGraph-powered multi-agent fintech news briefing system",
    lifespan=lifespan,
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(feedback.router)
app.include_router(watchlist.router)
app.include_router(users.router)
app.include_router(chat.router)
app.include_router(research.router)
app.include_router(dashboard.router)
app.include_router(subscribe_router)

# ── Subscribe form POST (FastAPI requires explicit Form() handler) ─────────────
@app.post("/subscribe/submit", response_class=HTMLResponse)
async def subscribe_form(
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    name: str = Form(default=""),
):
    from app.routers.subscribe import subscribe_form_submit
    return await subscribe_form_submit(background_tasks, email=email, name=name)

@app.post("/subscribe", response_class=HTMLResponse)
async def subscribe_post(
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    name: str = Form(default=""),
):
    from app.routers.subscribe import subscribe_form_submit
    return await subscribe_form_submit(background_tasks, email=email, name=name)

@app.post("/subscribe/onboard", response_class=HTMLResponse)
async def onboard_post(
    background_tasks: BackgroundTasks,
    token: str = Form(...),
    role: str = Form(default="executive"),
    sectors: list[str] = Form(default=[]),
    regions: list[str] = Form(default=[]),
):
    from app.routers.subscribe import onboard_submit
    return await onboard_submit(background_tasks, token=token, role=role,
                                sectors=sectors, regions=regions)

# ── Telegram webhook ──────────────────────────────────────────────────────────
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if not settings.TELEGRAM_BOT_TOKEN:
        return {"ok": False}
    try:
        body = await request.json()
        from app.delivery.telegram import handle_webhook
        import asyncio
        asyncio.create_task(handle_webhook(body))
        return {"ok": True}
    except Exception as e:
        logger.error(f"[telegram webhook] {e}")
        return {"ok": False}


# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse(url="/dashboard", status_code=302)


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    from app.graph.digest_graph import _graph
    from app.database import get_pool
    return {
        "status": "ok",
        "phase": "3+",
        "demo_mode": is_demo_mode(),
        "scheduler_running": scheduler.running,
        "graph_ready": _graph is not None,
        "db_pool_open": not get_pool().closed,
        "langsmith_enabled": bool(settings.LANGSMITH_API_KEY),
        "slack_enabled": bool(settings.SLACK_BOT_TOKEN),
        "telegram_enabled": bool(settings.TELEGRAM_BOT_TOKEN),
        "whatsapp_enabled": bool(getattr(settings, "TWILIO_ACCOUNT_SID", None)),
    }


# ── Manual triggers ───────────────────────────────────────────────────────────
@app.get("/run-now")
async def trigger_now(background_tasks: BackgroundTasks):
    if is_demo_mode():
        return {"message": "Demo mode: digest simulated. Check /preview."}
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


# ── Preview ───────────────────────────────────────────────────────────────────
@app.get("/preview", response_class=HTMLResponse)
async def preview_last_email():
    if is_demo_mode():
        return HTMLResponse(get_demo_email_html())
    html = agent_state.get("last_email_html")
    if not html:
        raise HTTPException(status_code=404, detail="No digest yet. Hit /run-now first.")
    return html


# ── Runs ──────────────────────────────────────────────────────────────────────
@app.get("/runs")
async def list_runs(limit: int = 30):
    if is_demo_mode():
        return JSONResponse(content={"runs": DEMO_RUN_HISTORY, "count": len(DEMO_RUN_HISTORY)})
    try:
        rows = await fetch_run_history(limit=limit)
        for r in rows:
            for k, v in r.items():
                if isinstance(v, datetime):
                    r[k] = v.isoformat()
        return JSONResponse(content={"runs": rows, "count": len(rows)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))