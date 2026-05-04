import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from app.agent import run_fintech_digest
from app.config import settings
from app.state import agent_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=pytz.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schedule daily digest at 9:00 AM in user's timezone
    tz = pytz.timezone(settings.USER_TIMEZONE)
    scheduler.add_job(
        run_fintech_digest,
        CronTrigger(hour=9, minute=0, timezone=tz),
        id="daily_digest",
        replace_existing=True,
        misfire_grace_time=3600,  # If server was down, run within 1hr of 9AM
    )
    scheduler.start()
    logger.info(f"Scheduler started. Daily digest at 9:00 AM {settings.USER_TIMEZONE}")
    yield
    scheduler.shutdown()


app = FastAPI(
    title="FinTech Intelligence Agent",
    description="Monitors fintech news and sends daily executive briefings",
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse)
async def root():
    last_run = agent_state.get("last_run", "Never")
    last_status = agent_state.get("last_status", "—")
    stories_found = agent_state.get("stories_found", 0)
    return f"""
    <html><body style="font-family:monospace;padding:2rem;background:#0a0a0a;color:#e0e0e0">
    <h2>🏦 FinTech Intelligence Agent</h2>
    <p>Status: <strong style="color:#4ade80">{last_status}</strong></p>
    <p>Last Run: {last_run}</p>
    <p>Stories in last digest: {stories_found}</p>
    <p>Schedule: Daily at 9:00 AM {settings.USER_TIMEZONE}</p>
    <hr/>
    <p><a href="/run-now" style="color:#60a5fa">▶ Trigger digest now (GET /run-now)</a></p>
    <p><a href="/preview" style="color:#60a5fa">👁 Preview last email (GET /preview)</a></p>
    <p><a href="/health" style="color:#60a5fa">❤ Health check (GET /health)</a></p>
    </body></html>
    """


@app.get("/health")
async def health():
    return {"status": "ok", "scheduler_running": scheduler.running}


@app.get("/run-now")
async def trigger_now(background_tasks: BackgroundTasks):
    """Manually trigger the digest — useful for demos and testing."""
    background_tasks.add_task(run_fintech_digest)
    return {"message": "Digest triggered in background. Check /preview in ~30 seconds."}


@app.get("/preview", response_class=HTMLResponse)
async def preview_last_email():
    """Preview the last generated email in the browser."""
    html = agent_state.get("last_email_html")
    if not html:
        raise HTTPException(status_code=404, detail="No digest generated yet. Hit /run-now first.")
    return html