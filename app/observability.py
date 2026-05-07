"""
app/observability.py — LangSmith tracing + agent health report.

Two responsibilities:

1. TRACING SETUP
   If LANGSMITH_API_KEY is set, wraps every LangGraph run with LangSmith
   tracing by setting the required environment variables. LangGraph
   automatically picks these up — no code changes to graph nodes needed.
   Free tier: 5,000 traces/month.

2. WEEKLY HEALTH REPORT (Monday 8 AM)
   Reads the last 7 days of run_history and generates a concise
   "agent health" email covering:
     - Total runs / success rate
     - Average stories per digest
     - Average run duration
     - Search success rate (runs with > 0 stories / total runs)
     - Any recurring error patterns (detected by LLM)
     - Trend: is story quality improving or degrading?

   This means the agent monitors itself — a key differentiator for
   production-readiness.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from groq import Groq
from app.config import settings

logger = logging.getLogger(__name__)


def setup_langsmith():
    """
    Configure LangSmith tracing via environment variables.
    LangGraph reads LANGCHAIN_* env vars automatically — no SDK import needed
    in the graph code itself.
    """
    if not settings.LANGSMITH_API_KEY:
        logger.info("[observability] LangSmith not configured (LANGSMITH_API_KEY not set)")
        return False

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.LANGSMITH_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGSMITH_PROJECT
    logger.info(f"[observability] LangSmith tracing enabled → project: {settings.LANGSMITH_PROJECT}")
    return True


async def run_health_report():
    """
    Generate and send the weekly agent health report.
    Called every Monday at HEALTH_REPORT_HOUR by APScheduler.
    """
    logger.info("=== Agent health report starting ===")
    try:
        stats = await _gather_stats()
        html = await _build_health_report_html(stats)
        subject = f"🔧 Agent Health Report — w/e {datetime.now().strftime('%-d %b %Y')}"

        from app.gmail import send_digest_email
        sent = send_digest_email(subject, html)
        logger.info(f"=== Health report sent={sent} ===")
    except Exception as e:
        logger.exception(f"Health report failed: {e}")


async def _gather_stats() -> dict:
    """Collect run metrics from the last 7 days of run_history."""
    from app.database import get_conn
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    async with get_conn() as conn:
        rows = await (await conn.execute(
            """
            SELECT run_id, status, stories, duration_s, started_at, error_msg
            FROM run_history
            WHERE started_at >= %s
            ORDER BY started_at DESC
            """,
            (cutoff,),
        )).fetchall()

    if not rows:
        return {"empty": True}

    total = len(rows)
    successes = sum(1 for r in rows if r[1] == "success")
    total_stories = sum(r[2] or 0 for r in rows)
    durations = [r[3] for r in rows if r[3]]
    errors = [r[5] for r in rows if r[5]]
    aborts = sum(1 for r in rows if "aborted" in (r[1] or ""))

    return {
        "empty": False,
        "total_runs": total,
        "success_runs": successes,
        "abort_runs": aborts,
        "fail_runs": total - successes - aborts,
        "success_rate": round(successes / total * 100, 1),
        "total_stories_sent": total_stories,
        "avg_stories_per_run": round(total_stories / max(successes, 1), 1),
        "avg_duration_s": round(sum(durations) / len(durations), 1) if durations else None,
        "min_duration_s": round(min(durations), 1) if durations else None,
        "max_duration_s": round(max(durations), 1) if durations else None,
        "error_messages": errors[:10],
        "recent_runs": [
            {
                "run_id": r[0][:8],
                "status": r[1],
                "stories": r[2],
                "duration_s": round(r[3], 1) if r[3] else None,
                "started_at": r[4].strftime("%-d %b %H:%M") if r[4] else "",
            }
            for r in rows[:10]
        ],
    }


async def _build_health_report_html(stats: dict) -> str:
    """Build the health report HTML, using Groq to detect error patterns."""
    from app.email_builder import _format_date
    today = datetime.now().strftime("%A, %d %B %Y")

    if stats.get("empty"):
        return f"""<html><body style="font-family:Georgia,serif;padding:2rem;background:#f5f0e8;">
        <h2>Agent Health Report — {today}</h2>
        <p>No runs recorded in the last 7 days.</p>
        </body></html>"""

    # Ask Groq to summarise any recurring error patterns
    error_summary = "No errors recorded this week."
    if stats["error_messages"]:
        try:
            groq = Groq(api_key=settings.GROQ_API_KEY)
            resp = groq.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[{
                    "role": "user",
                    "content": (
                        f"These are error messages from an automated news agent over the past week:\n"
                        f"{chr(10).join(stats['error_messages'])}\n\n"
                        "Summarise in 1-2 sentences: what is the most common failure pattern "
                        "and what likely causes it? Be specific and technical."
                    ),
                }],
                temperature=0.2,
                max_tokens=150,
            )
            error_summary = resp.choices[0].message.content.strip()
        except Exception:
            error_summary = f"{len(stats['error_messages'])} error(s) recorded — check logs."

    sr = stats["success_rate"]
    sr_colour = "#4ade80" if sr >= 90 else "#fbbf24" if sr >= 70 else "#f87171"

    rows_html = ""
    for r in stats["recent_runs"]:
        icon = "✅" if r["status"] == "success" else "⚠️" if "abort" in r["status"] else "❌"
        dur = f"{r['duration_s']}s" if r["duration_s"] else "—"
        rows_html += f"""
        <tr>
          <td style="font-family:'Courier New',monospace;font-size:11px;color:#8a7355;">
            {r['started_at']}</td>
          <td style="font-family:Georgia,serif;font-size:13px;">{icon} {r['status'][:35]}</td>
          <td style="font-family:'Courier New',monospace;font-size:11px;text-align:center;">
            {r['stories']}</td>
          <td style="font-family:'Courier New',monospace;font-size:11px;text-align:center;">
            {dur}</td>
        </tr>"""

    avg_dur = f"{stats['avg_duration_s']}s" if stats["avg_duration_s"] else "—"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Agent Health Report</title></head>
<body style="margin:0;padding:0;background:#f5f0e8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f0e8;">
    <tr><td align="center" style="padding:32px 16px;">
      <table width="640" cellpadding="0" cellspacing="0"
        style="max-width:640px;background:#fffef9;border:1px solid #e0d8cc;">

        <tr><td style="background:#1a1a2e;padding:24px 40px;">
          <p style="font-family:'Courier New',monospace;font-size:9px;letter-spacing:3px;
            color:#8a7355;text-transform:uppercase;margin:0 0 6px;">
            AGENT SELF-MONITORING</p>
          <p style="font-family:Georgia,serif;font-size:22px;font-weight:bold;
            color:#fffef9;margin:0;">Weekly Health Report</p>
        </td></tr>

        <tr><td style="background:#2d3561;padding:12px 40px;">
          <p style="font-family:Georgia,serif;font-size:12px;font-style:italic;
            color:#c8c0e0;margin:0;">{today} · Last 7 days</p>
        </td></tr>

        <tr><td style="padding:28px 40px;">

          <!-- KPI Row -->
          <table width="100%" cellpadding="0" cellspacing="0"
            style="background:#f0ebe0;border-radius:4px;margin-bottom:24px;">
            <tr>
              <td style="padding:14px;text-align:center;border-right:1px solid #ddd4c0;">
                <p style="font-family:'Courier New',monospace;font-size:9px;letter-spacing:1px;
                  color:#8a7355;text-transform:uppercase;margin:0 0 4px;">SUCCESS RATE</p>
                <p style="font-family:Georgia,serif;font-size:26px;font-weight:bold;
                  color:{sr_colour};margin:0;">{sr}%</p>
              </td>
              <td style="padding:14px;text-align:center;border-right:1px solid #ddd4c0;">
                <p style="font-family:'Courier New',monospace;font-size:9px;letter-spacing:1px;
                  color:#8a7355;text-transform:uppercase;margin:0 0 4px;">AVG STORIES</p>
                <p style="font-family:Georgia,serif;font-size:26px;font-weight:bold;
                  color:#1a1a2e;margin:0;">{stats['avg_stories_per_run']}</p>
              </td>
              <td style="padding:14px;text-align:center;border-right:1px solid #ddd4c0;">
                <p style="font-family:'Courier New',monospace;font-size:9px;letter-spacing:1px;
                  color:#8a7355;text-transform:uppercase;margin:0 0 4px;">TOTAL RUNS</p>
                <p style="font-family:Georgia,serif;font-size:26px;font-weight:bold;
                  color:#1a1a2e;margin:0;">{stats['total_runs']}</p>
              </td>
              <td style="padding:14px;text-align:center;">
                <p style="font-family:'Courier New',monospace;font-size:9px;letter-spacing:1px;
                  color:#8a7355;text-transform:uppercase;margin:0 0 4px;">AVG DURATION</p>
                <p style="font-family:Georgia,serif;font-size:26px;font-weight:bold;
                  color:#1a1a2e;margin:0;">{avg_dur}</p>
              </td>
            </tr>
          </table>

          <!-- Error pattern -->
          <p style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;
            text-transform:uppercase;color:#8a7355;margin:0 0 8px;">ERROR ANALYSIS</p>
          <p style="font-family:Georgia,serif;font-size:14px;color:#2d2d2d;
            line-height:1.65;margin:0 0 24px;padding:12px 16px;
            background:#f0ebe0;border-left:3px solid #8a7355;">
            {error_summary}</p>

          <!-- Recent runs table -->
          <p style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;
            text-transform:uppercase;color:#8a7355;margin:0 0 8px;">RECENT RUNS</p>
          <table width="100%" cellpadding="0" cellspacing="0"
            style="border-collapse:collapse;font-size:12px;">
            <tr style="background:#0f172a;">
              <th style="padding:6px 10px;color:#94a3b8;font-family:'Courier New',monospace;
                font-size:10px;text-align:left;">TIME</th>
              <th style="padding:6px 10px;color:#94a3b8;font-family:'Courier New',monospace;
                font-size:10px;text-align:left;">STATUS</th>
              <th style="padding:6px 10px;color:#94a3b8;font-family:'Courier New',monospace;
                font-size:10px;text-align:center;">STORIES</th>
              <th style="padding:6px 10px;color:#94a3b8;font-family:'Courier New',monospace;
                font-size:10px;text-align:center;">DURATION</th>
            </tr>
            {rows_html}
          </table>

        </td></tr>

        <tr><td style="background:#f0ebe0;padding:16px 40px;border-top:2px solid #1a1a2e;">
          <p style="font-family:'Courier New',monospace;font-size:9px;color:#9a9080;
            margin:0;letter-spacing:1px;text-transform:uppercase;">
            FinTech Intelligence Agent · Self-Monitoring Report · {today}
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""