# FinTech Intelligence Agent

A production-grade, self-improving AI agent that monitors fintech news and delivers personalised daily briefings to busy executives — without them having to ask.

Built on **FastAPI + LangGraph + PostgreSQL + Groq**, deployable on Render's free tier in under 30 minutes.

---

## What It Does

Every morning at 9 AM, the agent:

1. Runs 8 parallel news searches across banks, regulators, and fintech companies
2. Filters out share price movements, conference coverage, and general market commentary
3. Removes stories already seen in the last 7 days using semantic similarity (pgvector)
4. Applies your personal preference profile — learned from your 👍 / 👎 clicks
5. Sends a beautifully formatted email with 6–8 stories, each with a 2–3 sentence executive synopsis, publication name, and link
6. Fans out to Slack and Telegram if configured
7. Tracks sentiment for your watchlist entities and alerts you when something shifts

It also runs a breaking news check every 2 hours, sends a narrative "Week in Review" every Friday, and emails itself a health report every Monday.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    APScheduler                          │
│  9AM digest · 2h alerts · Fri synthesis · Mon health   │
└────────────────┬────────────────────────────────────────┘
                 │
        ┌────────▼────────┐
        │   LangGraph     │  PostgreSQL checkpoint (fault-tolerant)
        │  StateGraph     │  Resumes from last node if server restarts
        └────────┬────────┘
                 │
    ┌────────────┼────────────┐
    │            │            │
┌───▼───┐  ┌────▼────┐  ┌────▼────┐
│ news  │  │ memory  │  │curator  │
│ agent │  │ agent   │  │ agent   │
│Tavily │  │pgvector │  │  Groq   │
└───┬───┘  └────┬────┘  └────┬────┘
    │            │            │
    └────────────┼────────────┘
                 │
        ┌────────▼────────┐
        │delivery agent   │
        │ Gmail · Slack   │
        │  Telegram       │
        └────────┬────────┘
                 │
        ┌────────▼────────┐
        │ calendar agent  │
        │ DB run log      │
        └─────────────────┘
```

### Tech Stack

| Layer | Technology | Why |
|---|---|---|
| API framework | FastAPI | Async, fast, familiar |
| Agent orchestration | LangGraph 0.2 | Supervisor + specialist nodes, fault-tolerant checkpointing |
| LLM | Groq (Llama 3.3 70B) | Free tier, GPT-4 class, ~1s latency |
| News search | Tavily | Purpose-built for AI agents, structured results |
| Database | PostgreSQL + pgvector | Checkpointing, story memory, user data |
| Embeddings | all-MiniLM-L6-v2 | 80MB, runs offline, 384-dim sentence embeddings |
| Email | Gmail API (OAuth2) | Free, reliable, proper deliverability |
| Calendar | Google Calendar API | Audit trail of sent digests |
| Slack | slack-sdk | Free for personal/small team use |
| Telegram | Bot API (webhook) | Free, interactive commands |
| PDF | reportlab | Bundled, no external service |
| Observability | LangSmith | Free tier, 5,000 traces/month |
| Scheduler | APScheduler | Already in your FastAPI process |
| Deploy | Render | Free tier, Docker, PostgreSQL included |

---

## Project Structure

```
fintech-agent/
├── app/
│   ├── main.py                  # FastAPI app, lifespan, scheduler, all routers
│   ├── config.py                # All settings via pydantic-settings + .env
│   ├── database.py              # psycopg3 pool, all schema, all DB helpers
│   ├── memory.py                # Embedding + pgvector semantic deduplication
│   ├── preferences.py           # Feedback learning + preference profile builder
│   ├── watchlist.py             # Entity tracking + sentiment scoring + velocity alerts
│   ├── llm.py                   # Groq curation prompt with preference injection
│   ├── search.py                # Tavily search queries + exclusion filters
│   ├── email_builder.py         # HTML email templates (digest, alert, synthesis, health)
│   ├── gmail.py                 # Gmail API OAuth2 sender + Calendar event logger
│   ├── observability.py         # LangSmith setup + Monday health report
│   ├── alert_graph.py           # Breaking news LangGraph (separate from digest graph)
│   ├── synthesis_graph.py       # Friday narrative synthesis
│   ├── agent.py                 # Backwards-compat shim → digest_graph
│   ├── state.py                 # In-memory dashboard state
│   ├── graph/
│   │   ├── state.py             # DigestState TypedDict (shared across all nodes)
│   │   ├── digest_graph.py      # Compiles StateGraph with AsyncPostgresSaver
│   │   ├── news_agent.py        # Node 1: Tavily search + watchlist queries
│   │   ├── memory_agent.py      # Node 2: pgvector semantic deduplication
│   │   ├── curator_agent.py     # Node 3: Groq ranking + synopsis + preference inject
│   │   ├── builder_agent.py     # Node 4: validation gate
│   │   ├── delivery_agent.py    # Node 5: Gmail + channel fan-out + memory save
│   │   └── calendar_agent.py    # Node 6: Calendar event + DB run persist
│   ├── delivery/
│   │   ├── channels.py          # Multi-channel fan-out coordinator
│   │   ├── slack.py             # Slack WebClient delivery
│   │   └── telegram.py          # Telegram Bot API + webhook command handler
│   └── routers/
│       ├── feedback.py          # GET /feedback — one-click email feedback
│       ├── watchlist.py         # CRUD /watchlist + sentiment endpoints
│       ├── users.py             # /users — multi-user management
│       ├── chat.py              # POST /chat — RAG Q&A over story archive
│       ├── research.py          # POST /research — deep-dive brief + PDF
│       └── dashboard.py         # GET /dashboard/* — full web UI (HTMX)
├── scripts/
│   ├── authorize_google.py      # One-time Google OAuth token generation
│   ├── setup_database.py        # One-time DB schema creation
│   └── setup_telegram.py        # One-time Telegram webhook registration
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Prerequisites

Before you start, create free accounts at:

| Service | URL | What you need |
|---|---|---|
| Groq | console.groq.com | API key |
| Tavily | app.tavily.com | API key (1,000 searches/month free) |
| Google Cloud | console.cloud.google.com | OAuth2 credentials (Gmail + Calendar APIs) |
| Render | render.com | Account for deployment |
| LangSmith *(optional)* | smith.langchain.com | API key |
| Slack *(optional)* | api.slack.com/apps | Bot token + channel ID |
| Telegram *(optional)* | t.me/BotFather | Bot token + your chat ID |

---

## Local Setup

### 1. Clone and install

```bash
git clone <your-repo-url>
cd fintech-agent
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in at minimum:

```env
GROQ_API_KEY=gsk_...
TAVILY_API_KEY=tvly_...
RECIPIENT_EMAIL=you@example.com
SENDER_EMAIL=your_gmail@gmail.com
DATABASE_URL=postgresql://user:password@localhost:5432/fintech_agent
APP_BASE_URL=http://localhost:8000
```

### 3. Set up Google OAuth

This authorises the app to send Gmail and create Calendar events on your behalf.

**Step 1 — Enable APIs in Google Cloud Console:**
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. Navigate to **APIs & Services → Library**
4. Enable **Gmail API**
5. Enable **Google Calendar API**

**Step 2 — Create OAuth2 credentials:**
1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. Application type: **Desktop app**
4. Download the JSON file
5. Save it as `credentials/google_credentials.json`

**Step 3 — Authorise and generate token:**
```bash
python scripts/authorize_google.py
```
This opens a browser window. Sign in with your Gmail account and grant the requested permissions. A `credentials/token.json` file is created — keep this safe.

### 4. Set up PostgreSQL

Install PostgreSQL locally if you don't have it, then:

```bash
createdb fintech_agent
python scripts/setup_database.py
```

This creates all 8 tables and enables the pgvector extension.

### 5. Run locally

```bash
uvicorn app.main:app --reload --port 8000
```

Open [http://localhost:8000/dashboard](http://localhost:8000/dashboard) — you should see the web dashboard.

To trigger your first digest immediately:

```bash
curl http://localhost:8000/run-now
# Wait ~60 seconds, then:
open http://localhost:8000/preview
```

---

## Deploying to Render

### 1. Create a PostgreSQL database

In your Render dashboard:
1. Click **New → PostgreSQL**
2. Choose the free tier
3. Copy the **Internal Database URL** (used inside Render's network)

### 2. Enable pgvector on Render Postgres

Connect to your Render database using the external connection string:

```bash
psql <your-external-database-url>
```

Then run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
\q
```

### 3. Create a Web Service

1. Click **New → Web Service**
2. Connect your GitHub repo
3. Choose **Docker** as the environment
4. Set the following environment variables:

**Required:**

| Variable | Value |
|---|---|
| `GROQ_API_KEY` | Your Groq API key |
| `TAVILY_API_KEY` | Your Tavily API key |
| `RECIPIENT_EMAIL` | Email address to receive digests |
| `SENDER_EMAIL` | Your Gmail address |
| `DATABASE_URL` | Render internal PostgreSQL URL |
| `APP_BASE_URL` | `https://your-app-name.onrender.com` |
| `GOOGLE_CREDENTIALS_JSON` | Paste full contents of `credentials/google_credentials.json` |
| `GOOGLE_TOKEN_JSON` | Paste full contents of `credentials/token.json` |

> **Important:** The `token.json` content is printed to your terminal when you run `scripts/authorize_google.py`. Copy that exact JSON string.

**Optional but recommended:**

| Variable | Value |
|---|---|
| `USER_TIMEZONE` | e.g. `Asia/Kolkata`, `Europe/London`, `America/New_York` |
| `SLACK_BOT_TOKEN` | `xoxb-...` from your Slack app |
| `SLACK_CHANNEL_ID` | Channel ID beginning with `C` |
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | Your personal Telegram chat ID |
| `LANGSMITH_API_KEY` | From smith.langchain.com |

4. Click **Deploy**. The first build takes 5–8 minutes (it downloads the 80MB embedding model into the Docker image).

### 4. Register the Telegram webhook (if using Telegram)

After your first successful deploy:

```bash
TELEGRAM_BOT_TOKEN=xxx APP_BASE_URL=https://your-app.onrender.com \
  python scripts/setup_telegram.py
```

This registers your deployed URL with Telegram's Bot API.

### 5. Verify the deployment

```
GET https://your-app.onrender.com/health
```

Expected response:
```json
{
  "status": "ok",
  "phase": 3,
  "scheduler_running": true,
  "graph_ready": true,
  "db_pool_open": true,
  "langsmith_enabled": true,
  "slack_enabled": true,
  "telegram_enabled": true
}
```

Visit `https://your-app.onrender.com/dashboard` to see the web UI.

---

## Features

### Daily Digest (9:00 AM)

The core feature. Every morning at 9 AM in your timezone, the LangGraph pipeline runs:

- **8 parallel Tavily searches** across fintech verticals (regulation, open banking, fraud, M&A, CBDC, neobanks, etc.)
- **Keyword exclusion filter** removes share prices, conference coverage, and general market commentary before they reach the LLM
- **Semantic deduplication** — stories similar to those sent in the last 7 days are filtered using cosine similarity on sentence embeddings stored in pgvector
- **Groq curation** — Llama 3.3 70B selects the best 6–8 stories, writes 2–3 sentence executive synopses, and generates a sharp subject line
- **Preference injection** — if you have 5+ feedback signals, your preference profile is injected into the curation prompt
- **Multi-channel delivery** — Gmail (primary), Slack thread, Telegram messages
- **Google Calendar event** created as an audit trail of the send
- **PostgreSQL checkpoint** — if the server restarts mid-run, the graph resumes from the last completed node

### Breaking News Alerts

Every 2 hours, a lighter LangGraph subgraph scans for high-urgency stories using 6 targeted queries (bank failures, regulatory enforcement actions, cyber incidents, etc.). Groq scores each story 1–10 for urgency. Stories scoring **8 or above** trigger an immediate email and Telegram message — no waiting for 9 AM.

Alert history is persisted in PostgreSQL so the same story never triggers a repeat alert.

### Feedback Learning

Every story in the email has a one-click 👍 / 👎 link. Clicking opens a confirmation page in your browser and records the signal. After 5 signals, the agent builds a preference profile:

- Topics you like (e.g. "regulation", "CBDC", "open banking")
- Topics to deprioritise (e.g. "startup funding rounds")
- Preferred sources (e.g. "Financial Times", "Reuters")
- Entities that appear frequently in your liked stories

This profile is injected into the Groq curation prompt on every subsequent run. **The agent gets smarter with every click.**

View your current profile at `/dashboard/preferences` or via `GET /feedback/stats`.

### Watchlist

Track specific companies, regulators, topics, or people. Watched entities get dedicated Tavily searches on every digest run — their stories are **guaranteed to appear** in the digest, bypassing the normal LLM ranking gate.

Managed via:
- The `/dashboard/watchlist` web UI
- `POST /watchlist` API
- `/add <entity>` Telegram command

Sentiment is scored for each watchlist story (-1.0 to +1.0) using Groq. If an entity's average sentiment shifts by 0.3 or more in 48 hours versus its 30-day baseline, you receive an immediate **Sentiment Velocity Alert** email.

### Weekly Narrative Synthesis (Friday 8 AM)

Every Friday morning, the synthesis agent reads all stories sent during the week (from `story_memory`) and asks Groq to extract 3–5 macro narrative themes — not a list of events, but actual arcs:

> *"Regulator pressure on BNPL intensified this week, with three major enforcement actions in the EU and UK suggesting a coordinated push toward stricter consumer lending rules."*

Delivered as a "Week in Review" email before the regular Friday digest.

### Deep-Dive Research Briefs

On demand, request a structured research brief on any topic:

```bash
POST /research
{ "topic": "Klarna", "send_email": true }
```

The research agent runs up to 15 targeted searches across a 30-day window, then synthesises the results into:

- **Executive summary** (3–4 sentences)
- **Key developments** (5–10 items, most recent first, with dates)
- **Strategic implications** (2–4 analytical themes)
- **Outlook**
- **Source list**

Delivered as an HTML email and a professionally formatted **PDF** (downloadable from `/research/{id}/pdf`). Typically ready in 30–60 seconds. View and manage all briefs at `/dashboard/research`.

### Conversational Q&A

Ask natural language questions about recent stories directly from the dashboard or Telegram:

> *"What happened with HSBC this week?"*
> *"Any news about open banking regulation?"*
> *"Summarise everything about Stripe from the last two weeks"*

Answers are generated using RAG:
1. Your query is embedded with the same model used for story storage
2. pgvector cosine similarity retrieves the most relevant stories from the archive
3. Groq synthesises an answer with `[n]` citations linking back to sources

Available at `/dashboard/chat`, `POST /chat` API, or via any Telegram message.

### Telegram Bot

If configured, the Telegram bot provides real-time interaction:

| Command | What it does |
|---|---|
| `/start` | Welcome message and command list |
| `/digest` | Trigger a digest run immediately |
| `/status` | Last run status and story count |
| `/watchlist` | View your current watchlist |
| `/add <entity>` | Add an entity to your watchlist |
| `/remove <n>` | Remove watchlist item by number |
| `/ask <question>` | Ask the Q&A agent |
| *(any message)* | Treated as a Q&A query |

Breaking news alerts and digest stories are also pushed to your Telegram chat automatically.

### Multi-User Support

The system supports multiple recipients with different role-based preferences:

```bash
POST /users
{
  "email": "risk@company.com",
  "name": "Risk Officer",
  "role": "risk_officer",
  "timezone": "Europe/London"
}
```

Available roles: `executive` (balanced), `risk_officer` (compliance/fraud weighted), `product_lead` (innovation/API weighted), `investor` (M&A/funding weighted).

Trigger personalised digests for all active users:
```bash
POST /users/run-digest
```

Each user gets their own LangGraph run with their own preference profile and watchlist injected.

### Web Dashboard

A full self-serve web UI at `/dashboard`, built with HTMX + Chart.js — no separate frontend deploy, no npm, no build step.

| Page | URL | What it shows |
|---|---|---|
| Overview | `/dashboard` | KPIs, current status, recent run history |
| Watchlist | `/dashboard/watchlist` | Entity manager, 7-day sentiment badges, add/remove |
| Preferences | `/dashboard/preferences` | Feedback signals, active profile, liked/disliked topics |
| Research | `/dashboard/research` | Brief launcher, past briefs, PDF links |
| Q&A | `/dashboard/chat` | Chat interface with inline source citations |
| Run History | `/dashboard/runs` | Full run log with status, duration, errors |

### Agent Self-Monitoring

Every Monday at 8 AM, the agent emails itself a **health report** covering the last 7 days:

- Success rate, total runs, failed/aborted breakdown
- Average stories per digest, average run duration
- Error pattern analysis — Groq reads the error messages and identifies the most likely root cause in plain English
- Table of the 10 most recent runs

Also available on demand: `GET /health-report-now`

LangSmith tracing is enabled automatically when `LANGSMITH_API_KEY` is set. Every LangGraph node execution is traced — inputs, outputs, latency — at [smith.langchain.com](https://smith.langchain.com).

---

## API Reference

All endpoints are documented interactively at `/docs` (Swagger UI).

### Core triggers

| Method | URL | Description |
|---|---|---|
| `GET` | `/run-now` | Trigger daily digest immediately |
| `GET` | `/alert-now` | Trigger breaking news check |
| `GET` | `/synthesis-now` | Trigger weekly synthesis |
| `GET` | `/health-report-now` | Trigger agent health report |
| `GET` | `/preview` | View last generated email in browser |
| `GET` | `/health` | Service health check |
| `GET` | `/runs` | Run history (JSON, `?limit=30`) |

### Feedback

| Method | URL | Description |
|---|---|---|
| `GET` | `/feedback?signal=1&url=...` | Record thumbs up (linked from email) |
| `GET` | `/feedback?signal=-1&url=...` | Record thumbs down (linked from email) |
| `GET` | `/feedback/stats?user_id=1` | Feedback stats + active profile summary |

### Watchlist

| Method | URL | Description |
|---|---|---|
| `GET` | `/watchlist` | List all watched entities |
| `POST` | `/watchlist` | Add entity `{"entity": "HSBC", "entity_type": "company"}` |
| `DELETE` | `/watchlist/{id}` | Remove entity |
| `GET` | `/watchlist/sentiment` | Sentiment history for all entities |
| `GET` | `/watchlist/sentiment/{entity}` | Sentiment trend + velocity delta for one entity |

### Users

| Method | URL | Description |
|---|---|---|
| `GET` | `/users` | List all active users |
| `POST` | `/users` | Create user `{"email", "role", "timezone"}` |
| `PUT` | `/users/{id}` | Update user role/timezone/active status |
| `GET` | `/users/{id}/preferences` | Get preference profile |
| `POST` | `/users/run-digest` | Trigger digest for all active users |

### Chat (Q&A)

| Method | URL | Description |
|---|---|---|
| `POST` | `/chat` | `{"query": "...", "user_id": 1, "lookback_days": 14}` |
| `GET` | `/chat/history` | Last N exchanges for a user |

### Research

| Method | URL | Description |
|---|---|---|
| `POST` | `/research` | `{"topic": "Klarna", "send_email": true}` → returns `brief_id` |
| `GET` | `/research` | List past briefs |
| `GET` | `/research/{id}` | Full brief JSON |
| `GET` | `/research/{id}/pdf` | Download PDF |

---

## Environment Variables Reference

| Variable | Default | Required | Description |
|---|---|---|---|
| `GROQ_API_KEY` | — | ✅ | Groq API key |
| `TAVILY_API_KEY` | — | ✅ | Tavily search API key |
| `RECIPIENT_EMAIL` | — | ✅ | Digest delivery address |
| `SENDER_EMAIL` | — | ✅ | Gmail account used to send |
| `DATABASE_URL` | — | ✅ | PostgreSQL connection string |
| `APP_BASE_URL` | `http://localhost:8000` | ✅ | Deployed URL (for feedback links) |
| `GOOGLE_CREDENTIALS_PATH` | `credentials/google_credentials.json` | ✅ local | Path to OAuth credentials |
| `GOOGLE_CREDENTIALS_JSON` | — | ✅ prod | Credentials JSON as env var (Render) |
| `GOOGLE_TOKEN_JSON` | — | ✅ prod | Token JSON as env var (Render) |
| `USER_TIMEZONE` | `Asia/Kolkata` | — | Digest send timezone |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | — | Groq model ID |
| `MAX_STORIES` | `8` | — | Max stories per digest |
| `LOOKBACK_HOURS` | `24` | — | Search window (hours) |
| `MIN_STORIES_BEFORE_SEND` | `3` | — | Abort if fewer stories found |
| `ALERT_URGENCY_THRESHOLD` | `8` | — | Min urgency score (1–10) for alerts |
| `ALERT_POLL_HOURS` | `2` | — | Alert check frequency (hours) |
| `SIMILARITY_THRESHOLD` | `0.85` | — | Cosine similarity for deduplication |
| `MEMORY_LOOKBACK_DAYS` | `7` | — | Days to check for duplicates |
| `MIN_FEEDBACK_FOR_PROFILE` | `5` | — | Signals needed before profile activates |
| `FEEDBACK_WINDOW` | `50` | — | Recent signals used for profile |
| `MAX_WATCHLIST_ENTITIES` | `20` | — | Per-user watchlist limit |
| `SYNTHESIS_DAY_OF_WEEK` | `fri` | — | Weekly synthesis day |
| `SYNTHESIS_HOUR` | `8` | — | Weekly synthesis hour |
| `SENTIMENT_WINDOW_DAYS` | `30` | — | Sentiment baseline window |
| `SENTIMENT_ALERT_DELTA` | `0.3` | — | Shift threshold for velocity alerts |
| `SLACK_BOT_TOKEN` | — | — | Slack bot OAuth token |
| `SLACK_CHANNEL_ID` | — | — | Slack channel ID |
| `TELEGRAM_BOT_TOKEN` | — | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | — | Your Telegram chat ID |
| `LANGSMITH_API_KEY` | — | — | LangSmith API key |
| `LANGSMITH_PROJECT` | `fintech-agent` | — | LangSmith project name |
| `HEALTH_REPORT_HOUR` | `8` | — | Health report send hour |
| `RESEARCH_MAX_SEARCHES` | `15` | — | Max searches per research brief |
| `RESEARCH_MAX_STORIES` | `25` | — | Max stories per research brief |

---

## Database Schema

8 tables, all created automatically on first startup.

| Table | Purpose |
|---|---|
| `story_memory` | Stores pgvector embeddings of sent stories for deduplication |
| `run_history` | Persistent log of every agent run (status, duration, story count) |
| `alert_history` | Sent breaking alerts — prevents re-sending the same story |
| `users` | Multi-user support with roles and timezone preferences |
| `story_feedback` | Per-user thumbs up/down signals |
| `user_preferences` | Materialised preference profile rebuilt after each feedback signal |
| `watchlist_entities` | Per-user entity tracking targets |
| `entity_sentiment` | Rolling sentiment scores per entity per story |
| `chat_history` | Q&A conversation log |
| `research_briefs` | Research brief metadata and JSON content |

LangGraph also creates its own `langgraph_checkpoints` table automatically on first graph run.

---

## Fault Tolerance

The system is designed to never fail silently:

- **LangGraph checkpointing** — every node's state is snapshotted to PostgreSQL. If the Render instance restarts or crashes mid-run, the graph resumes from the last completed node on the next trigger.
- **Misfire grace period** — if the scheduler fires while the server is restarting, APScheduler will catch up within 1 hour (digest) or 5 minutes (alerts).
- **Graceful degradation** — if the memory deduplication fails, the pipeline continues without it. If Groq fails, the email sends with raw snippets as synopses. If Slack fails, Gmail still delivers. No silent drops.
- **Minimum story guard** — if fewer than `MIN_STORIES_BEFORE_SEND` stories are curated, the send is skipped and the reason is logged. The agent never sends a near-empty email.
- **Non-fatal error accumulation** — each LangGraph node appends errors to `state.errors` rather than raising exceptions. The `calendar_agent` (last node) always runs and persists the full error log to `run_history`.

---

## Troubleshooting

**Google token expired after a few days**

OAuth2 tokens expire. The app auto-refreshes them, but if the refresh token itself expires (after 7 days for apps in test mode), you need to re-run:

```bash
python scripts/authorize_google.py
```

Then update `GOOGLE_TOKEN_JSON` in your Render env vars.

To avoid this on production, publish your Google Cloud app (move it out of "Testing" status in the OAuth consent screen). Published apps have tokens that don't expire.

**"No stories returned" on first run**

Tavily's free tier sometimes rate-limits on the first few requests. Wait a few minutes and retry `GET /run-now`. If the problem persists, check your `TAVILY_API_KEY`.

**pgvector extension not found**

If you see `extension "vector" does not exist`, connect to your database and run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

On Render, use the external connection string (not the internal one) for this one-time command.

**Render free tier server sleeping**

Render's free web services spin down after 15 minutes of inactivity. This means the 9 AM scheduler may not fire if nothing has hit the service recently. Two solutions:

1. Use a free uptime monitor (e.g. UptimeRobot) to ping `GET /health` every 10 minutes
2. Add a Render Cron Job (`GET /run-now`) as a backup trigger at 9:05 AM

**Telegram bot not receiving messages**

Check the webhook is registered:
```bash
curl https://api.telegram.org/bot{TOKEN}/getWebhookInfo
```

If the URL is wrong or empty, re-run `python scripts/setup_telegram.py`.

---

## Cost

Everything runs on free tiers:

| Service | Free Allowance | Typical Usage |
|---|---|---|
| Groq | 14,400 req/day | ~10 req/day |
| Tavily | 1,000 searches/month | ~280/month (8 queries × 5 × 7 days) |
| Render Web Service | 750 hours/month | ~720 hours/month |
| Render PostgreSQL | 1GB storage, 90 days | < 100MB typically |
| LangSmith | 5,000 traces/month | ~30/month |
| Slack API | Unlimited (personal) | — |
| Telegram Bot API | Unlimited | — |
| Google APIs | Gmail: 1B quota units/day | Negligible |

**Total monthly cost: $0.**

---

## Extending the Agent

The codebase is structured to make extensions straightforward:

**Add a new delivery channel** — create `app/delivery/your_channel.py` with `send_digest_to_X()` and `send_alert_to_X()`, then add it to `app/delivery/channels.py`.

**Add a new LangGraph node** — create `app/graph/your_node.py`, register it in `digest_graph.py`, add edges. The `DigestState` TypedDict in `graph/state.py` is the single place to add new state fields.

**Add a new search vertical** — add a query string to `SEARCH_QUERIES` in `search.py` and a corresponding entry to `ALERT_QUERIES` in `alert_graph.py`.

**Change the LLM model** — set `GROQ_MODEL` in your `.env`. Any model available on Groq's API works without code changes.

**Add a new email template** — add a `build_*_html()` function to `email_builder.py` following the existing pattern.

---

## License

MIT — use freely, modify freely, deploy freely.
