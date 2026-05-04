# FinTech Intelligence Agent

An AI-powered intelligence agent designed to deliver high-signal, executive-ready briefings on the fintech industry. This agent acts as a digital "Chief of Staff," monitoring news across banks and asset management companies to provide concise, strategic insights without the noise of general market news.

## Key Features

* **Agentic Search:** Utilizes **Tavily AI** to perform deep, multi-query searches specifically targeted at fintech innovation, regulation, and M&A activity.
* **Executive Summarization:** Employs **gpt-oss-120B (via Groq)** to transform raw news items into 2-3 sentence strategic synopses focused on the "why" behind the news.
* **Automated Scheduling:** Features an integrated **APScheduler** that triggers briefings at exactly 9:00 AM in the user's local timezone.
* **Smart Filtering:** Implements hard-coded and LLM-driven exclusion criteria to filter out share price movements, conference announcements, and general market commentary.
* **Reliability & Audit Trails:** Automatically creates **Google Calendar** events to serve as an audit trail for successful briefing delivery.
* **Interactive Dashboard:** Built with **FastAPI** to provide a web interface for health checks, manual digest triggers, and live email previews.

## Tech Stack

* **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Asynchronous Python)
* **Search Engine:** [Tavily AI](https://tavily.com/) (Optimized for LLM RAG)
* **Inference Engine:** [Groq](https://groq.com/) (gpt-oss-120B)
* **Email/Calendar:** [Google Workspace APIs](https://developers.google.com/gmail/api) (OAuth2)
* **Scheduler:** [APScheduler](https://apscheduler.readthedocs.io/)

## Quick Start

### 1. Prerequisites
* Python 3.10+
* Google Cloud Project with Gmail and Calendar APIs enabled

### 2. Installation
```bash
git clone [https://github.com/shazam37/Fintech-Agent.git](https://github.com/shazam37/Fintech-Agent.git)
cd fintech-agent
pip install -r requirements.txt
```

### 3. Configuration

Create a .env file in the root directory:

```env
GROQ_API_KEY=your_key
TAVILY_API_KEY=your_key
RECIPIENT_EMAIL=executive@example.com
SENDER_EMAIL=agent@example.com
USER_TIMEZONE=Asia/Kolkata
```

### 4. Run the Agent
1. **Authorize Google:** Run `python app/authorize_google.py` and follow the OAuth2 flow to generate `token.json`.
2. **Start Server:** Run `uvicorn main:app --reload`.
3. **Access Dashboard:** Open `http://localhost:8000` to trigger a manual digest or preview the output.

---

### Error Handling & Reliability
* **Fallback Logic:** If the LLM reasoning fails, the agent reverts to raw snippets to ensure a briefing is still delivered.
* **Misfire Grace:** The `misfire_grace_time` setting ensures that if the server is offline at 9:00 AM, the briefing triggers immediately upon reconnection.
* **State Tracking:** Maintains an in-memory `agent_state` to monitor run history and successful story counts.

---

### Future Roadmap
* **Deduplication:** Integration of a Vector Database (e.g., Pinecone) to ensure stories aren't repeated day-over-day.
* **Personalization:** Adding "Like/Dislike" feedback loops to allow the agent to learn the executive’s preferences over time.
