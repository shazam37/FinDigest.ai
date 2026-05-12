"""
app/routers/dashboard.py — Self-serve web dashboard.

All pages are server-rendered with Jinja2 + HTMX for interactivity.
No separate frontend deploy — everything runs on the same FastAPI instance.

Pages:
  GET /dashboard              — main overview (run history, status, KPIs)
  GET /dashboard/watchlist    — watchlist manager + sentiment charts
  GET /dashboard/preferences  — feedback stats + preference profile viewer
  GET /dashboard/research     — research brief launcher + history
  GET /dashboard/chat         — conversational Q&A interface
  GET /dashboard/runs         — full run history with filtering

HTMX is loaded from cdnjs — no npm, no build step.
Chart.js is loaded from cdnjs for sentiment sparklines.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse

from app.config import settings
from app.graph.runtime_state import runtime_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# ── Shared HTML shell ─────────────────────────────────────────────────────────

def _shell(title: str, content: str, active: str = "") -> str:
    """Wrap page content in the shared nav shell."""
    nav_items = [
        ("Overview", "/dashboard", "overview"),
        ("Watchlist", "/dashboard/watchlist", "watchlist"),
        ("Preferences", "/dashboard/preferences", "preferences"),
        ("Research", "/dashboard/research", "research"),
        ("Q&A", "/dashboard/chat", "chat"),
        ("Runs", "/dashboard/runs", "runs"),
    ]
    nav_html = ""
    for label, href, key in nav_items:
        is_active = "active" if key == active else ""
        nav_html += f'<a href="{href}" class="nav-link {is_active}">{label}</a>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — FinTech Agent</title>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/htmx/1.9.10/htmx.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #0a0a0f; --surface: #13131a; --surface2: #1c1c26;
      --border: #2a2a3a; --text: #e2e2e8; --text2: #94a3b8;
      --accent: #60a5fa; --green: #4ade80; --red: #f87171;
      --amber: #fbbf24; --gold: #c9a96e;
      --radius: 8px; --font-mono: 'Courier New', monospace;
    }}
    html, body {{ height: 100%; background: var(--bg); color: var(--text);
      font-family: Georgia, serif; font-size: 15px; }}
    .layout {{ display: flex; min-height: 100vh; }}
    .sidebar {{ width: 200px; background: var(--surface); border-right: 1px solid var(--border);
      padding: 1.5rem 0; flex-shrink: 0; position: sticky; top: 0; height: 100vh; }}
    .sidebar-logo {{ padding: 0 1.25rem 1.5rem;
      font-family: var(--font-mono); font-size: 11px; letter-spacing: 2px;
      color: var(--gold); text-transform: uppercase; border-bottom: 1px solid var(--border); }}
    .sidebar-logo span {{ display: block; font-size: 16px; color: var(--text);
      font-family: Georgia, serif; margin-top: 4px; font-weight: bold; }}
    .nav-link {{ display: block; padding: .6rem 1.25rem;
      font-family: var(--font-mono); font-size: 12px; letter-spacing: 1px;
      color: var(--text2); text-decoration: none; text-transform: uppercase;
      transition: all .15s; }}
    .nav-link:hover {{ color: var(--text); background: var(--surface2); }}
    .nav-link.active {{ color: var(--accent); background: rgba(96,165,250,.1);
      border-left: 2px solid var(--accent); }}
    .main {{ flex: 1; padding: 2rem; max-width: 1100px; }}
    .page-title {{ font-size: 22px; font-weight: bold; color: var(--text);
      margin-bottom: .25rem; }}
    .page-sub {{ font-family: var(--font-mono); font-size: 11px; color: var(--text2);
      letter-spacing: 1px; text-transform: uppercase; margin-bottom: 2rem; }}
    .card {{ background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 1.25rem; }}
    .card-title {{ font-family: var(--font-mono); font-size: 10px; letter-spacing: 2px;
      text-transform: uppercase; color: var(--gold); margin-bottom: 1rem; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }}
    .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }}
    .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 1rem; }}
    .kpi {{ text-align: center; }}
    .kpi-value {{ font-size: 32px; font-weight: bold; font-family: Georgia, serif; }}
    .kpi-label {{ font-family: var(--font-mono); font-size: 10px; color: var(--text2);
      letter-spacing: 1px; text-transform: uppercase; margin-top: 4px; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 20px;
      font-family: var(--font-mono); font-size: 10px; font-weight: bold; }}
    .badge-green {{ background: rgba(74,222,128,.15); color: var(--green); }}
    .badge-red {{ background: rgba(248,113,113,.15); color: var(--red); }}
    .badge-amber {{ background: rgba(251,191,36,.15); color: var(--amber); }}
    .badge-blue {{ background: rgba(96,165,250,.15); color: var(--accent); }}
    .badge-gold {{ background: rgba(201,169,110,.15); color: var(--gold); }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 8px 12px; border-bottom: 1px solid var(--border);
      font-size: 13px; text-align: left; }}
    th {{ font-family: var(--font-mono); font-size: 10px; letter-spacing: 1px;
      text-transform: uppercase; color: var(--text2); }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: var(--surface2); }}
    .btn {{ display: inline-block; padding: .5rem 1rem; border-radius: var(--radius);
      font-family: var(--font-mono); font-size: 11px; letter-spacing: 1px;
      text-transform: uppercase; cursor: pointer; border: none;
      text-decoration: none; transition: opacity .15s; }}
    .btn:hover {{ opacity: .85; }}
    .btn-primary {{ background: var(--accent); color: #fff; }}
    .btn-outline {{ background: transparent; color: var(--text2);
      border: 1px solid var(--border); }}
    .btn-green {{ background: var(--green); color: #000; }}
    .btn-red {{ background: var(--red); color: #fff; }}
    .input {{ background: var(--surface2); border: 1px solid var(--border);
      border-radius: var(--radius); color: var(--text); padding: .5rem .75rem;
      font-family: var(--font-mono); font-size: 12px; width: 100%; }}
    .input:focus {{ outline: none; border-color: var(--accent); }}
    .status-ok {{ color: var(--green); }}
    .status-err {{ color: var(--red); }}
    .status-warn {{ color: var(--amber); }}
    .mt1 {{ margin-top: .5rem; }} .mt2 {{ margin-top: 1rem; }}
    .mt3 {{ margin-top: 1.5rem; }} .mb1 {{ margin-bottom: .5rem; }}
    .mb2 {{ margin-bottom: 1rem; }} .gap1 {{ gap: .5rem; }}
    .flex {{ display: flex; }} .items-center {{ align-items: center; }}
    .justify-between {{ justify-content: space-between; }}
    .text-mono {{ font-family: var(--font-mono); font-size: 12px; }}
    .text-sm {{ font-size: 13px; }} .text-xs {{ font-size: 11px; }}
    .text-muted {{ color: var(--text2); }}
    .chat-messages {{ max-height: 480px; overflow-y: auto;
      padding: 1rem; background: var(--surface2); border-radius: var(--radius);
      margin-bottom: 1rem; }}
    .chat-msg {{ margin-bottom: 1rem; }}
    .chat-msg.user {{ text-align: right; }}
    .chat-bubble {{ display: inline-block; padding: .5rem .9rem;
      border-radius: 12px; max-width: 85%; font-size: 14px; line-height: 1.55; }}
    .chat-msg.user .chat-bubble {{ background: var(--accent); color: #fff; }}
    .chat-msg.agent .chat-bubble {{ background: var(--surface); border: 1px solid var(--border); }}
    .htmx-indicator {{ display: none; }}
    .htmx-request .htmx-indicator {{ display: inline; }}
    #chat-form {{ display: flex; gap: .5rem; }}
    #chat-input {{ flex: 1; }}
    @media(max-width: 768px) {{
      .grid-4 {{ grid-template-columns: 1fr 1fr; }}
      .grid-3 {{ grid-template-columns: 1fr; }}
      .sidebar {{ display: none; }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <nav class="sidebar">
      <div class="sidebar-logo">
        FinDigest
      </div>
      {nav_html}
    </nav>
    <main class="main">
      {content}
    </main>
  </div>
</body>
</html>"""


# ── Overview page ─────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def overview():
    from app.database import fetch_run_history
    runs = await fetch_run_history(limit=30)

    last_status = runtime_state.get("last_status", "—")
    stories = runtime_state.get("stories_found", 0)
    last_run = runtime_state.get("last_run", "Never")

    total = len(runs)
    successes = sum(1 for r in runs if r.get("status") == "success")
    sr = round(successes / total * 100) if total else 0
    sr_class = "status-ok" if sr >= 90 else "status-warn" if sr >= 70 else "status-err"
    avg_stories = round(sum(r.get("stories", 0) for r in runs) / max(successes, 1), 1)
    durations = [r["duration_s"] for r in runs if r.get("duration_s")]
    avg_dur = f"{round(sum(durations)/len(durations), 1)}s" if durations else "—"

    status_class = "status-ok" if "success" in last_status else "status-err"

    rows = ""
    for r in runs[:10]:
        st = r.get("status", "")
        icon = "✅" if st == "success" else "⚠️" if "abort" in st else "❌"
        dur = f"{round(r['duration_s'],1)}s" if r.get("duration_s") else "—"
        ts = r["started_at"].strftime("%-d %b %H:%M") if isinstance(r.get("started_at"), datetime) else str(r.get("started_at",""))[:16]
        badge = f'<span class="badge badge-green">success</span>' if st == "success" else f'<span class="badge badge-red">{st[:30]}</span>'
        rows += f"<tr><td class='text-mono'>{ts}</td><td>{badge}</td><td>{r.get('stories',0)}</td><td class='text-mono'>{dur}</td><td class='text-xs text-muted'>{(r.get('subject') or '')[:50]}</td></tr>"

    content = f"""
    <div class="flex items-center justify-between mb2">
      <div>
        <h1 class="page-title">Overview</h1>
        <p class="page-sub">Agent status and run history</p>
      </div>
      <div class="flex gap1">
        <a href="/run-now" class="btn btn-primary">▶ Run Now</a>
        <a href="/preview" class="btn btn-outline" target="_blank">Preview Email</a>
      </div>
    </div>

    <div class="grid-4">
      <div class="card kpi">
        <div class="kpi-value {sr_class}">{sr}%</div>
        <div class="kpi-label">Success Rate (30d)</div>
      </div>
      <div class="card kpi">
        <div class="kpi-value">{avg_stories}</div>
        <div class="kpi-label">Avg Stories</div>
      </div>
      <div class="card kpi">
        <div class="kpi-value">{total}</div>
        <div class="kpi-label">Total Runs</div>
      </div>
      <div class="card kpi">
        <div class="kpi-value">{avg_dur}</div>
        <div class="kpi-label">Avg Duration</div>
      </div>
    </div>

    <div class="card mb2">
      <div class="flex items-center justify-between mb1">
        <div class="card-title" style="margin:0">Current Status</div>
        <span class="{status_class} text-mono text-xs">{last_status}</span>
      </div>
      <p class="text-sm text-muted">Last run: {last_run} &nbsp;·&nbsp; Stories: {stories} &nbsp;·&nbsp;
        Schedule: 9:00 AM {settings.USER_TIMEZONE} &nbsp;·&nbsp;
        Alerts: every {settings.ALERT_POLL_HOURS}h &nbsp;·&nbsp;
        Synthesis: {settings.SYNTHESIS_DAY_OF_WEEK.upper()} {settings.SYNTHESIS_HOUR}:00 AM
      </p>
    </div>

    <div class="card">
      <div class="card-title">Recent Runs</div>
      <table>
        <thead><tr><th>Time</th><th>Status</th><th>Stories</th><th>Duration</th><th>Subject</th></tr></thead>
        <tbody>{rows if rows else '<tr><td colspan="5" class="text-muted">No runs yet — click Run Now</td></tr>'}</tbody>
      </table>
    </div>"""

    return HTMLResponse(_shell("Overview", content, "overview"))


# ── Watchlist page ────────────────────────────────────────────────────────────

@router.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page():
    from app.database import (
        fetch_watchlist,
        fetch_sentiment_window,
        get_or_create_default_user,
    )

    user_id = await get_or_create_default_user()
    entities = await fetch_watchlist(user_id)

    entity_rows = ""

    for e in entities:
        scores = await fetch_sentiment_window(e["entity"], days=7)

        avg = (
            round(sum(s["score"] for s in scores) / len(scores), 2)
            if scores else None
        )

        if avg is None:
            sent_badge = '<span class="badge badge-blue">No data</span>'
        elif avg >= 0.2:
            sent_badge = f'<span class="badge badge-green">+{avg:.2f}</span>'
        elif avg <= -0.2:
            sent_badge = f'<span class="badge badge-red">{avg:.2f}</span>'
        else:
            sent_badge = f'<span class="badge badge-amber">{avg:.2f}</span>'

        entity_rows += f"""
        <tr>
          <td><strong>{e['entity']}</strong></td>
          <td><span class="badge badge-gold">{e['entity_type']}</span></td>
          <td>{sent_badge}</td>
          <td class="text-mono text-xs">{len(scores)} data points</td>
          <td>
            <button class="btn btn-red text-xs"
              hx-delete="/watchlist/{e['id']}?user_id={user_id}"
              hx-confirm="Remove {e['entity']} from watchlist?"
              hx-target="closest tr"
              hx-swap="outerHTML">
              Remove
            </button>
          </td>
        </tr>
        """

    content = f"""
    <div class="flex items-center justify-between mb2">
      <div>
        <h1 class="page-title">Watchlist</h1>
        <p class="page-sub">Tracked entities and sentiment signals</p>
      </div>
    </div>

    <div class="card mb2">
      <div class="card-title">Add Entity</div>

      <div class="flex gap1">
        <input
          id="entity-input"
          class="input"
          placeholder="e.g. HSBC, Stripe, FCA, BNPL..."
          style="max-width:320px;"
        >

        <select
          id="type-select"
          class="input"
          style="max-width:140px;"
        >
          <option value="company">Company</option>
          <option value="regulator">Regulator</option>
          <option value="topic">Topic</option>
          <option value="person">Person</option>
        </select>

        <button
          class="btn btn-primary"
          onclick="addWatchlistEntity()"
        >
          + Add
        </button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        Watched Entities ({len(entities)})
      </div>

      <table>
        <thead>
          <tr>
            <th>Entity</th>
            <th>Type</th>
            <th>7-Day Sentiment</th>
            <th>Coverage</th>
            <th></th>
          </tr>
        </thead>

        <tbody>
          {entity_rows if entity_rows else '<tr><td colspan="5" class="text-muted">No entities watched yet</td></tr>'}
        </tbody>
      </table>

      <p class="text-xs text-muted mt2">
        Sentiment updates after each digest run.
        Scale: -1.0 (negative) → +1.0 (positive).
      </p>
    </div>

    <script>
    async function addWatchlistEntity() {{
        const entity = document
            .getElementById("entity-input")
            .value
            .trim();

        const entity_type = document
            .getElementById("type-select")
            .value;

        if (!entity) {{
            alert("Please enter an entity");
            return;
        }}

        try {{
            const resp = await fetch(
                "/watchlist?user_id={user_id}",
                {{
                    method: "POST",
                    headers: {{
                        "Content-Type": "application/json"
                    }},
                    body: JSON.stringify({{
                        entity,
                        entity_type
                    }})
                }}
            );

            if (!resp.ok) {{
                const err = await resp.text();
                throw new Error(err);
            }}

            document.getElementById("entity-input").value = "";

            window.location.reload();

        }} catch(err) {{
            console.error(err);
            alert("Failed to add entity");
        }}
    }}
    </script>
    """

    return HTMLResponse(_shell("Watchlist", content, "watchlist"))


# ── Preferences page ──────────────────────────────────────────────────────────

@router.get("/preferences", response_class=HTMLResponse)
async def preferences_page():
    from app.database import fetch_recent_feedback, fetch_preference_profile, get_or_create_default_user
    user_id = await get_or_create_default_user()
    feedback = await fetch_recent_feedback(user_id, limit=settings.FEEDBACK_WINDOW)
    profile = await fetch_preference_profile(user_id)

    liked = sum(1 for f in feedback if f["signal"] == 1)
    disliked = sum(1 for f in feedback if f["signal"] == -1)
    needed = max(0, settings.MIN_FEEDBACK_FOR_PROFILE - len(feedback))

    profile_html = ""
    if profile:
        liked_topics = ", ".join(profile.get("liked_topics", [])) or "None yet"
        disliked_topics = ", ".join(profile.get("disliked_topics", [])) or "None yet"
        liked_sources = ", ".join(profile.get("liked_sources", [])) or "None yet"
        liked_entities = ", ".join(profile.get("liked_entities", [])) or "None yet"
        summary = profile.get("profile_summary", "")
        profile_html = f"""
        <div class="card mt2">
          <div class="card-title">Active Preference Profile</div>
          <div class="grid-2">
            <div>
              <p class="text-xs text-muted mb1">PREFERRED TOPICS</p>
              <p class="text-sm">{liked_topics}</p>
            </div>
            <div>
              <p class="text-xs text-muted mb1">DEPRIORITISED TOPICS</p>
              <p class="text-sm">{disliked_topics}</p>
            </div>
            <div>
              <p class="text-xs text-muted mb1">PREFERRED SOURCES</p>
              <p class="text-sm">{liked_sources}</p>
            </div>
            <div>
              <p class="text-xs text-muted mb1">TRACKED ENTITIES</p>
              <p class="text-sm">{liked_entities}</p>
            </div>
          </div>
          <div class="mt2" style="padding:12px;background:var(--surface2);border-radius:var(--radius);">
            <p class="text-xs text-muted mb1">PROFILE SUMMARY (injected into LLM curator)</p>
            <p class="text-sm" style="font-style:italic;">{summary}</p>
          </div>
        </div>"""
    else:
        profile_html = f"""
        <div class="card mt2" style="border-color:var(--amber);">
          <p class="text-sm" style="color:var(--amber);">
            ⏳ Profile not yet active. {needed} more feedback signal(s) needed
            ({len(feedback)}/{settings.MIN_FEEDBACK_FOR_PROFILE}).
            Click 👍 / 👎 on stories in your email digest to train the agent.
          </p>
        </div>"""

    feedback_rows = ""
    for f in feedback[:15]:
        icon = "👍" if f["signal"] == 1 else "👎"
        ts = f["created_at"].strftime("%-d %b") if isinstance(f.get("created_at"), datetime) else ""
        feedback_rows += f"""<tr>
          <td>{icon}</td>
          <td class="text-sm">{f['title'][:65]}{"…" if len(f['title'])>65 else ""}</td>
          <td class="text-mono text-xs text-muted">{f.get('source','')}</td>
          <td class="text-mono text-xs text-muted">{ts}</td>
        </tr>"""

    content = f"""
    <h1 class="page-title">Preferences</h1>
    <p class="page-sub">Feedback signals and preference profile</p>

    <div class="grid-3">
      <div class="card kpi">
        <div class="kpi-value">{len(feedback)}</div>
        <div class="kpi-label">Total Signals</div>
      </div>
      <div class="card kpi">
        <div class="kpi-value status-ok">{liked}</div>
        <div class="kpi-label">👍 Liked</div>
      </div>
      <div class="card kpi">
        <div class="kpi-value status-err">{disliked}</div>
        <div class="kpi-label">👎 Disliked</div>
      </div>
    </div>

    {profile_html}

    <div class="card mt2">
      <div class="card-title">Recent Feedback</div>
      <table>
        <thead><tr><th>Signal</th><th>Story</th><th>Source</th><th>Date</th></tr></thead>
        <tbody>{feedback_rows if feedback_rows else '<tr><td colspan="4" class="text-muted">No feedback yet. Click 👍/👎 in your emails.</td></tr>'}</tbody>
      </table>
    </div>"""

    return HTMLResponse(_shell("Preferences", content, "preferences"))


# ── Research page ─────────────────────────────────────────────────────────────

@router.get("/research", response_class=HTMLResponse)
async def research_page():
    from app.database import get_or_create_default_user

    user_id = await get_or_create_default_user()

    async with __import__(
        "app.database",
        fromlist=["get_conn"]
    ).get_conn() as conn:

        rows = await (
            await conn.execute(
                """
                SELECT
                    brief_id,
                    topic,
                    status,
                    story_count,
                    created_at
                FROM research_briefs
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 20
                """,
                (user_id,),
            )
        ).fetchall()

    brief_rows = ""

    for r in rows:
        ts = (
            r[4].strftime("%-d %b %H:%M")
            if isinstance(r[4], datetime)
            else str(r[4])[:16]
        )

        st = r[2]

        badge = (
            f'<span class="badge badge-green">{st}</span>'
            if st == "complete"
            else f'<span class="badge badge-amber">{st}</span>'
            if st == "pending"
            else f'<span class="badge badge-red">{st[:25]}</span>'
        )

        pdf_link = (
            f'<a href="/research/{r[0]}/pdf" class="btn btn-outline text-xs" target="_blank">PDF</a>'
            if st == "complete"
            else "—"
        )

        brief_rows += f"""
        <tr>
          <td class="text-mono text-xs">{r[0]}</td>
          <td><strong>{r[1]}</strong></td>
          <td>{badge}</td>
          <td>{r[3]}</td>
          <td class="text-mono text-xs text-muted">{ts}</td>
          <td>{pdf_link}</td>
        </tr>
        """

    content = f"""
    <h1 class="page-title">Research</h1>

    <p class="page-sub">
      Deep-dive briefs on companies, regulators, and topics
    </p>

    <div class="card mb2">
      <div class="card-title">New Research Brief</div>

      <p class="text-sm text-muted mb2">
        Runs {settings.RESEARCH_MAX_SEARCHES} targeted searches
        across 30 days of news.
      </p>

      <div class="flex gap1">
        <input
          id="research-topic"
          class="input"
          placeholder="e.g. Klarna, HSBC open banking..."
          style="max-width:400px;"
        >

        <button
          class="btn btn-primary"
          onclick="generateResearch()"
        >
          Generate Brief
        </button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Past Briefs</div>

      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Topic</th>
            <th>Status</th>
            <th>Sources</th>
            <th>Generated</th>
            <th>PDF</th>
          </tr>
        </thead>

        <tbody>
          {brief_rows if brief_rows else '<tr><td colspan="6" class="text-muted">No briefs yet</td></tr>'}
        </tbody>
      </table>
    </div>

    <script>
    async function generateResearch() {{

        const topic = document
            .getElementById("research-topic")
            .value
            .trim();

        if (!topic) {{
            alert("Please enter a topic");
            return;
        }}

        try {{

            const resp = await fetch(
                "/research?user_id={user_id}",
                {{
                    method: "POST",
                    headers: {{
                        "Content-Type": "application/json"
                    }},
                    body: JSON.stringify({{
                        topic
                    }})
                }}
            );

            if (!resp.ok) {{
                const err = await resp.text();
                throw new Error(err);
            }}

            document.getElementById("research-topic").value = "";

            setTimeout(() => {{
                window.location.reload();
            }}, 2000);

        }} catch(err) {{
            console.error(err);
            alert("Failed to generate research brief");
        }}
    }}
    </script>
    """

    return HTMLResponse(_shell("Research", content, "research"))


# ── Chat / Q&A page ───────────────────────────────────────────────────────────

@router.get("/chat", response_class=HTMLResponse)
async def chat_page():
    content = """
    <h1 class="page-title">Q&amp;A</h1>
    <p class="page-sub">Ask questions about recent fintech news</p>

    <div class="card">
      <div class="card-title">Story Archive Search</div>
      <p class="text-sm text-muted mb2">
        Ask anything about stories in the last 14 days. Uses semantic search over
        the story archive + Groq for answer synthesis with citations.
      </p>

      <div class="chat-messages" id="chat-messages">
        <div class="chat-msg agent">
          <div class="chat-bubble">
            👋 Ask me anything about recent fintech news.
            For example: <em>"What happened with open banking this week?"</em>
            or <em>"Any news about HSBC?"</em>
          </div>
        </div>
      </div>

      <form id="chat-form" onsubmit="sendChat(event)">
        <input id="chat-input" class="input" placeholder="Ask about recent fintech news…" autocomplete="off">
        <button type="submit" class="btn btn-primary">Ask</button>
      </form>
    </div>

    <script>
    async function sendChat(e) {
      e.preventDefault();
      const input = document.getElementById('chat-input');
      const msgs = document.getElementById('chat-messages');
      const query = input.value.trim();
      if (!query) return;

      // Show user message
      msgs.innerHTML += `<div class="chat-msg user"><div class="chat-bubble">${query}</div></div>`;
      input.value = '';

      // Show typing indicator
      const typingId = 'typing-' + Date.now();
      msgs.innerHTML += `<div class="chat-msg agent" id="${typingId}"><div class="chat-bubble text-muted">Searching stories…</div></div>`;
      msgs.scrollTop = msgs.scrollHeight;

      try {
        const resp = await fetch('/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({query, user_id: 1})
        });
        const data = await resp.json();
        document.getElementById(typingId).remove();

        const sourcesHtml = data.sources && data.sources.length
          ? '<div style="margin-top:.5rem;font-size:11px;opacity:.7">' +
            data.sources.slice(0,3).map(s => `<a href="${s.url}" target="_blank" style="color:inherit;display:block;">[${s.source}] ${s.title.substring(0,60)}…</a>`).join('') +
            '</div>'
          : '';

        msgs.innerHTML += `<div class="chat-msg agent"><div class="chat-bubble">${data.answer.replace(/\\n/g,'<br>')}${sourcesHtml}</div></div>`;
      } catch(err) {
        document.getElementById(typingId).remove();
        msgs.innerHTML += `<div class="chat-msg agent"><div class="chat-bubble status-err">Error: ${err.message}</div></div>`;
      }
      msgs.scrollTop = msgs.scrollHeight;
    }
    </script>"""

    return HTMLResponse(_shell("Q&A Chat", content, "chat"))


# ── Runs page ─────────────────────────────────────────────────────────────────

@router.get("/runs", response_class=HTMLResponse)
async def runs_page():
    from app.database import fetch_run_history
    runs = await fetch_run_history(limit=50)

    rows = ""
    for r in runs:
        st = r.get("status", "")
        badge = (f'<span class="badge badge-green">success</span>' if st == "success"
                 else f'<span class="badge badge-amber">{st[:25]}</span>' if "abort" in st
                 else f'<span class="badge badge-red">{st[:25]}</span>')
        ts = r["started_at"].strftime("%-d %b %Y %H:%M") if isinstance(r.get("started_at"), datetime) else str(r.get("started_at",""))[:16]
        dur = f"{round(r['duration_s'],1)}s" if r.get("duration_s") else "—"
        err = r.get("error_msg", "") or ""
        rows += f"""<tr>
          <td class="text-mono text-xs">{r.get('run_id','')[:8]}</td>
          <td class="text-mono text-xs">{ts}</td>
          <td>{badge}</td>
          <td>{r.get('stories',0)}</td>
          <td class="text-mono text-xs">{dur}</td>
          <td class="text-xs text-muted" style="max-width:200px;overflow:hidden;">{(r.get('subject') or '')[:45]}</td>
          <td class="text-xs status-err" style="max-width:160px;">{err[:50]}</td>
        </tr>"""

    content = f"""
    <div class="flex items-center justify-between mb2">
      <div>
        <h1 class="page-title">Run History</h1>
        <p class="page-sub">All agent runs — persisted in PostgreSQL</p>
      </div>
      <a href="/run-now" class="btn btn-primary">▶ Run Now</a>
    </div>

    <div class="card">
      <table>
        <thead><tr><th>Run ID</th><th>Started</th><th>Status</th><th>Stories</th><th>Duration</th><th>Subject</th><th>Error</th></tr></thead>
        <tbody>{rows if rows else '<tr><td colspan="7" class="text-muted">No runs yet</td></tr>'}</tbody>
      </table>
    </div>"""

    return HTMLResponse(_shell("Runs", content, "runs"))