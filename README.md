# FinTech Intelligence Agent

> **A self-improving AI agent that monitors fintech news and delivers personalised daily briefings — so you always know what matters, without having to look.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-orange)](https://langchain-ai.github.io/langgraph/)

**[🌐 Landing Page](https://fintech-intelligence.vercel.app)** · **[🧩 Install Extension](#browser-extension)** · **[📖 API Docs](/docs)** · **[💬 Contribute](#contributing)**

---

## What It Does

Every morning at 9 AM, the agent:

1. Runs **8 parallel Tavily searches** across banks, regulators, neobanks, and fintech verticals
2. Filters out share prices, conference coverage, and market noise — before the LLM even sees them
3. Removes stories already sent in the last 7 days using **semantic similarity** (pgvector + sentence embeddings)
4. Applies your **personal preference profile** — learned from 👍 / 👎 clicks, and active from day one via onboarding
5. Sends a beautifully formatted email with 6–8 stories, each with a 2–3 sentence executive synopsis
6. Fans out to **Slack**, **Telegram**, and **WhatsApp** simultaneously
7. Creates a **Google Calendar event** as an audit trail
8. Tracks **sentiment** on your watched entities and alerts you when something shifts

Between digests: a lighter agent polls every 2 hours for breaking news. Stories scoring **8+/10 urgency** trigger immediate delivery.

Every Friday: a narrative **Week in Review** synthesises the week's themes into analytical arcs — not a list, but a story.

Every Monday: the agent **emails itself a health report** with LLM-analysed error patterns and KPIs.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                       APScheduler                            │
│  9 AM digest · 2h alerts · Fri synthesis · Mon health       │
└────────────────────┬─────────────────────────────────────────┘
                     │
            ┌────────▼────────┐
            │   LangGraph     │  PostgreSQL checkpoint — resumes on restart
            │  StateGraph     │
            └────────┬────────┘
                     │
     ┌───────────────┼────────────────┐
     ▼               ▼                ▼
 news_agent     memory_agent     curator_agent
 (Tavily)       (pgvector)       (Groq LLM)
     │               │                │
     └───────────────┼────────────────┘
                     ▼
            delivery_agent
          Gmail · Slack · Telegram · WhatsApp
                     │
            calendar_agent
          Calendar event · DB run log
```

### Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.115 |
| Agent orchestration | LangGraph 0.2 |
| LLM | Groq — Llama 3.3 70B (free) |
| News search | Tavily |
| Database | PostgreSQL + pgvector |
| Embeddings | all-MiniLM-L6-v2 (offline, 80MB) |
| Email | Gmail API (OAuth2) |
| Slack | slack-sdk |
| WhatsApp | Twilio (free sandbox) |
| Telegram | Bot API + webhook |
| PDF | reportlab |
| Observability | LangSmith (free tier) |
| Deploy | Render (free tier) |
| Browser Extension | Manifest V3 — Chrome + Firefox |

---

## Project Structure

```
fintech-agent/
├── app/
│   ├── main.py                  # FastAPI app, lifespan, all routers
│   ├── config.py                # All settings via pydantic-settings
│   ├── database.py              # psycopg3 pool, schema, all DB helpers
│   ├── memory.py                # pgvector semantic deduplication
│   ├── preferences.py           # Feedback learning + onboarding cold-start
│   ├── watchlist.py             # Entity tracking + sentiment + velocity alerts
│   ├── llm.py                   # Groq curation with preference injection
│   ├── search.py                # Tavily queries + exclusion filters
│   ├── email_builder.py         # HTML templates for all 5 email types
│   ├── gmail.py                 # Gmail API sender + Calendar logger
│   ├── observability.py         # LangSmith + Monday health report
│   ├── alert_graph.py           # Breaking news LangGraph
│   ├── synthesis_graph.py       # Friday narrative synthesis
│   ├── demo.py                  # Demo mode — static email for presentations
│   ├── graph/
│   │   ├── state.py             # DigestState TypedDict
│   │   ├── digest_graph.py      # Compiles StateGraph + AsyncPostgresSaver
│   │   ├── news_agent.py        # Node 1: Tavily + watchlist queries
│   │   ├── memory_agent.py      # Node 2: pgvector deduplication
│   │   ├── curator_agent.py     # Node 3: Groq + preference injection
│   │   ├── builder_agent.py     # Node 4: validation gate
│   │   ├── delivery_agent.py    # Node 5: Gmail + fan-out + memory save
│   │   └── calendar_agent.py    # Node 6: Calendar + DB persist
│   ├── delivery/
│   │   ├── channels.py          # Multi-channel fan-out coordinator
│   │   ├── slack.py             # Slack delivery
│   │   ├── telegram.py          # Telegram bot + webhook handler
│   │   └── whatsapp.py          # WhatsApp via Twilio
│   └── routers/
│       ├── feedback.py          # One-click email feedback
│       ├── watchlist.py         # Watchlist CRUD + sentiment
│       ├── users.py             # Multi-user management
│       ├── chat.py              # RAG Q&A over story archive
│       ├── research.py          # Deep-dive brief + PDF generation
│       ├── subscribe.py         # Public subscribe + onboarding flow
│       └── dashboard.py         # HTMX web dashboard
├── extension/
│   ├── manifest.json            # Manifest V3
│   ├── src/
│   │   ├── background.js        # Service worker, context menus, API proxy
│   │   ├── content.js           # Toast notifications + sidebar panel
│   │   ├── content.css          # Sidebar + toast styles
│   │   ├── popup.html           # Extension popup (4 tabs)
│   │   └── popup.js             # Popup logic
│   └── README.md
├── scripts/
│   ├── authorize_google.py      # One-time Google OAuth token
│   ├── setup_database.py        # DB schema creation
│   ├── setup_telegram.py        # Telegram webhook registration
│   └── generate_icons.py        # Extension PNG icon generator
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Prerequisites

| Service | URL | Free allowance |
|---|---|---|
| Groq | console.groq.com | 14,400 req/day |
| Tavily | app.tavily.com | 1,000 searches/month |
| Google Cloud | console.cloud.google.com | Gmail + Calendar free |
| Render | render.com | Web service + PostgreSQL free |
| LangSmith *(optional)* | smith.langchain.com | 5,000 traces/month |
| Slack *(optional)* | api.slack.com/apps | Unlimited personal |
| Twilio *(optional)* | twilio.com | WhatsApp sandbox free |
| Telegram *(optional)* | t.me/BotFather | Unlimited |

---

## Local Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/fintech-agent.git
cd fintech-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Fill in at minimum: GROQ_API_KEY, TAVILY_API_KEY, RECIPIENT_EMAIL,
# SENDER_EMAIL, DATABASE_URL, APP_BASE_URL
```

### 3. Set up Google OAuth

1. [console.cloud.google.com](https://console.cloud.google.com) → create project
2. Enable **Gmail API** and **Google Calendar API**
3. Credentials → OAuth client ID → Desktop app → download JSON
4. Save as `credentials/google_credentials.json`

```bash
python scripts/authorize_google.py
# Opens browser — sign in and grant permissions
```

### 4. Database

```bash
createdb fintech_agent
python scripts/setup_database.py
```

### 5. Run

```bash
uvicorn app.main:app --reload --port 8000
```

Visit [http://localhost:8000/dashboard](http://localhost:8000/dashboard) then trigger a test run:

```bash
curl http://localhost:8000/run-now
# Wait ~60s, then open http://localhost:8000/preview
```

---

## Deploy to Render

### 1. PostgreSQL

Render → New → PostgreSQL → free tier → copy **Internal Database URL**.

Enable pgvector (one-time, using external URL):

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 2. Web Service

New → Web Service → Docker environment.

**Required env vars:**

| Variable | Value |
|---|---|
| `GROQ_API_KEY` | Groq key |
| `TAVILY_API_KEY` | Tavily key |
| `RECIPIENT_EMAIL` | Delivery address |
| `SENDER_EMAIL` | Gmail address |
| `DATABASE_URL` | Internal PostgreSQL URL |
| `APP_BASE_URL` | `https://your-app.onrender.com` |
| `GOOGLE_CREDENTIALS_JSON` | Contents of `credentials/google_credentials.json` |
| `GOOGLE_TOKEN_JSON` | Contents of `credentials/token.json` (printed on first auth) |

**Optional:**

```
USER_TIMEZONE, SLACK_BOT_TOKEN, SLACK_CHANNEL_ID,
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, WHATSAPP_TO,
LANGSMITH_API_KEY, DEMO_MODE
```

### 3. After deploy

```bash
# Register Telegram webhook (if using Telegram)
python scripts/setup_telegram.py
```

Verify: `GET https://your-app.onrender.com/health`

---

## Browser Extension

Brings your agent into every webpage.

### Features

| Tab / Feature | What it does |
|---|---|
| **Ask** | RAG Q&A over your story archive — semantic search + Groq synthesis |
| **Watchlist** | View/add/remove entities with live 7-day sentiment scores |
| **Status** | Last run info, trigger run, preview email, open dashboard |
| **Settings** | Backend URL and user ID |
| **Right-click → Add to Watchlist** | Select any text → one-click watchlist add |
| **Right-click → Ask about this page** | Opens popup pre-filled with page title |
| **Sidebar** | Slides in on any page, auto-searches archive, shows answer + citations |

### Install (Developer mode)

```bash
pip install Pillow
python scripts/generate_icons.py
```

**Chrome:** `chrome://extensions` → Developer mode ON → Load unpacked → select `extension/`

**Firefox:** `about:debugging` → This Firefox → Load Temporary Add-on → select `extension/manifest.json`

Then: extension icon → Settings → enter your backend URL → Save → Test Connection.

### Publishing to Chrome Web Store

```bash
cd fintech-agent
zip -r extension.zip extension/ --exclude "*/\.*"
```

1. [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole)
2. One-time $5 developer fee
3. Upload `extension.zip`, fill in store listing, submit for review (~3–7 days)

---

## User Onboarding

Share `/subscribe` with anyone. The flow:

1. Enter name + email
2. Select sectors (10 options), regions (6 options), role (4 options)
3. Preferences saved — **first digest is immediately tailored**
4. Welcome email with instructions + dashboard link

No waiting for the algorithm. The onboarding profile activates from digest #1.

---

## Preference Learning

Each email story has 👍 / 👎 links. Each click:
1. Records signal in `story_feedback`
2. Groq rebuilds preference profile from last 50 signals
3. Profile injected into next digest's curation prompt

After 5 signals, learned profile supplements onboarding. After 20+, it largely supersedes it.

---

## API Reference

Full interactive docs at `/docs`.

<details>
<summary>Digest control</summary>

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/run-now` | Trigger digest |
| `GET` | `/alert-now` | Trigger alert check |
| `GET` | `/synthesis-now` | Trigger weekly synthesis |
| `GET` | `/health-report-now` | Trigger health report |
| `GET` | `/preview` | View last email |
| `GET` | `/health` | Health check |
| `GET` | `/runs` | Run history |

</details>

<details>
<summary>Subscribe, Feedback, Watchlist, Users, Q&A, Research</summary>

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/subscribe` | Public signup |
| `GET` | `/unsubscribe?token=...` | One-click unsubscribe |
| `GET` | `/feedback?signal=1&url=...` | Record 👍 |
| `GET` | `/feedback?signal=-1&url=...` | Record 👎 |
| `GET` | `/feedback/stats` | Feedback stats + profile |
| `GET/POST/DELETE` | `/watchlist` | Watchlist CRUD |
| `GET` | `/watchlist/sentiment` | Sentiment for all entities |
| `GET/POST/PUT` | `/users` | User management |
| `POST` | `/users/run-digest` | Digest for all users |
| `POST` | `/chat` | Q&A query |
| `POST` | `/research` | Research brief |
| `GET` | `/research/{id}/pdf` | Download PDF |

</details>

---

## Environment Variables

<details>
<summary>Full reference (30 variables)</summary>

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | Groq API key ✅ |
| `TAVILY_API_KEY` | — | Tavily key ✅ |
| `RECIPIENT_EMAIL` | — | Digest recipient ✅ |
| `SENDER_EMAIL` | — | Gmail sender ✅ |
| `DATABASE_URL` | — | PostgreSQL URL ✅ |
| `APP_BASE_URL` | `http://localhost:8000` | Deployed URL ✅ |
| `GOOGLE_CREDENTIALS_JSON` | — | OAuth credentials (prod) ✅ |
| `GOOGLE_TOKEN_JSON` | — | OAuth token (prod) ✅ |
| `USER_TIMEZONE` | `Asia/Kolkata` | Digest timezone |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Model ID |
| `MAX_STORIES` | `8` | Stories per digest |
| `LOOKBACK_HOURS` | `24` | Search window |
| `ALERT_URGENCY_THRESHOLD` | `8` | Min urgency for alerts |
| `ALERT_POLL_HOURS` | `2` | Alert check frequency |
| `SIMILARITY_THRESHOLD` | `0.85` | Dedup threshold |
| `MEMORY_LOOKBACK_DAYS` | `7` | Dedup window |
| `MIN_FEEDBACK_FOR_PROFILE` | `5` | Signals before profile |
| `MAX_WATCHLIST_ENTITIES` | `20` | Per-user limit |
| `SYNTHESIS_DAY_OF_WEEK` | `fri` | Synthesis day |
| `SYNTHESIS_HOUR` | `8` | Synthesis hour |
| `SENTIMENT_ALERT_DELTA` | `0.3` | Velocity alert threshold |
| `SLACK_BOT_TOKEN` | — | Slack token |
| `SLACK_CHANNEL_ID` | — | Slack channel |
| `TELEGRAM_BOT_TOKEN` | — | Telegram token |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID |
| `TWILIO_ACCOUNT_SID` | — | Twilio SID |
| `TWILIO_AUTH_TOKEN` | — | Twilio token |
| `WHATSAPP_TO` | — | Your WhatsApp number |
| `LANGSMITH_API_KEY` | — | LangSmith key |
| `DEMO_MODE` | `false` | Static email for demos |

</details>

---

## Fault Tolerance

- **LangGraph checkpointing** — every node snapshotted. Restart mid-run → resumes from last node.
- **Misfire grace** — APScheduler retries missed jobs within 1h (digest) or 5min (alerts).
- **Graceful degradation** — dedup fail → continues. Groq fail → raw snippets sent. Slack fail → Gmail still delivers.
- **Min story guard** — fewer than `MIN_STORIES_BEFORE_SEND` curated → send skipped, logged.
- **Self-monitoring** — Monday health report with LLM error analysis.

---

## Cost

**$0/month.** Everything runs on free tiers.

| Service | Monthly usage | Limit |
|---|---|---|
| Groq | ~300 req | 14,400 req/day |
| Tavily | ~280 searches | 1,000/month |
| Render | ~720 hours | 750 hours |
| Render PostgreSQL | < 100MB | 1GB |
| LangSmith | ~30 traces | 5,000/month |

---

## Contributing

Contributions are welcome. This is open source — the more people improve it, the better.

**Areas that need help most:**
- Additional delivery channels (Discord, Teams, LINE)
- Test suite (currently zero tests — intentionally shipped fast)
- Multi-language digest support
- Firefox extension testing and fixes
- Docker Compose for self-hosting
- Helm chart for Kubernetes

**How:**
1. Fork the repo
2. `git checkout -b feature/your-feature`
3. Make focused changes with clear commits
4. Open a PR

**Register as a contributor** on the [landing page](https://fintech-intelligence.vercel.app) — we'll add you to the project channel.

**Code style:** async/await throughout, pydantic for validation, docstrings on every module, imperative commit messages.

---

## Troubleshooting

**Google token expires** — publish the OAuth app (Testing → Published) or re-run `scripts/authorize_google.py` and update `GOOGLE_TOKEN_JSON` on Render.

**No stories on first run** — Tavily rate-limits new accounts. Wait 2 minutes, retry `/run-now`.

**pgvector not found** — `CREATE EXTENSION IF NOT EXISTS vector;` in your database.

**Render server sleeping** — add a Render Cron Job at 9:05 AM calling `/run-now`, and use UptimeRobot to ping `/health` every 10 minutes.

**Telegram not responding** — re-run `scripts/setup_telegram.py` after deploy.

**WhatsApp not arriving** — activate the Twilio sandbox: text `join <your-word>` to `+1 415 523 8886`.

**Extension can't connect** — check Settings tab URL has no trailing slash and uses HTTPS.

---

## Screenshots

<p align="center">
  <img src="screenshots/overview.png" width="250"/>
  <img src="screenshots/run_history.png" width="250"/>
  <img src="screenshots/preferences.png" width="250"/>
</p>

<p align="center">
  <b>Dashboard, Run History & Preference Learning</b>
</p>

<br/>

<p align="center">
  <img src="screenshots/watchlist.png" width="250"/>
  <img src="screenshots/research.png" width="250"/>
  <img src="screenshots/research_brief.png" width="250"/>
</p>

<p align="center">
  <b>Watchlists & AI Research Briefs</b>
</p>

<br/>

<p align="center">
  <img src="screenshots/q&a.png" width="250"/>
  <img src="screenshots/gmail.png" width="250"/>
  <img src="screenshots/slack.png" width="250"/>
  <img src="screenshots/telegram.png" width="250"/>
</p>

<p align="center">
  <b>Q&A Assistant & Multi-Channel Delivery</b>
</p>

---

## License

MIT — use freely, modify freely, deploy freely.

---

## Acknowledgements

Built with [LangGraph](https://langchain-ai.github.io/langgraph/), [Groq](https://groq.com), [Tavily](https://tavily.com), [FastAPI](https://fastapi.tiangolo.com), and [pgvector](https://github.com/pgvector/pgvector).
