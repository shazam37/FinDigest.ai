"""
app/demo.py — Demo mode for presentations and job interviews.

When DEMO_MODE=true:
  - GET /preview returns a static pre-rendered email (no API calls needed)
  - GET /run-now returns instantly with a fake "triggered" message
  - The dashboard shows realistic-looking run history
  - All other endpoints remain fully functional

Set APP_BASE_URL to your deployed URL so feedback links look real.

Usage:
  DEMO_MODE=true uvicorn app.main:app
  or set DEMO_MODE=true in Render env vars for your demo deployment.
"""

from datetime import date

from app.config import settings


def is_demo_mode() -> bool:
    import os
    return os.environ.get("DEMO_MODE", "").lower() in ("true", "1", "yes")


def get_demo_email_html() -> str:
    """Return a pre-rendered, realistic-looking digest email."""
    today = date.today().strftime("%A, %d %B %Y")
    base = settings.APP_BASE_URL

    stories = [
        {
            "num": "01",
            "watchlist": "",
            "title": "HSBC Partners with Behavox to Deploy AI-Driven Fraud Detection Across Retail Banking",
            "synopsis": "HSBC has signed a multi-year contract with compliance AI firm Behavox to roll out real-time transaction monitoring across its 40 million retail accounts globally. The system uses large language models to detect anomalous behaviour patterns that traditional rule-based systems miss, targeting synthetic identity fraud specifically. The bank cited a 34% rise in first-party fraud attempts in 2024 as the primary driver for accelerating the deployment.",
            "source": "FINANCIAL TIMES",
            "date": "Today",
            "url": "#",
        },
        {
            "num": "02",
            "watchlist": "",
            "title": "EU's PSD3 Final Text Requires Banks to Open Premium Data APIs by Q3 2026",
            "synopsis": "The European Parliament has ratified the final PSD3 text, giving banks 18 months to expose enhanced data endpoints covering mortgage, pension, and insurance products — a significant expansion from the payments-only scope of PSD2. The directive also introduces new liability standards that shift fraud reimbursement obligations to the institution holding the data, a provision that caught several major banks off-guard during consultation. Analysts expect UK regulators to follow with an equivalent Smart Data mandate within six months.",
            "source": "REUTERS",
            "date": "Today",
            "url": "#",
        },
        {
            "num": "03",
            "watchlist": "★ BlackRock",
            "title": "BlackRock Acquires Tokenisation Infrastructure Startup Securitize for $400M",
            "synopsis": "BlackRock has completed its acquisition of Securitize, the digital asset securities platform it first invested in last year, for approximately $400 million. The deal gives the world's largest asset manager direct control over the infrastructure underpinning its tokenised treasury fund, BUIDL, which has grown to $1.7 billion in AUM since launch. BlackRock cited plans to extend tokenised products to private equity and real estate assets by end of 2025.",
            "source": "BLOOMBERG",
            "date": "Today",
            "url": "#",
        },
        {
            "num": "04",
            "watchlist": "",
            "title": "Monzo Granted Full Banking Licence in Germany, Accelerating European Expansion",
            "synopsis": "UK neobank Monzo has received a full banking licence from BaFin, Germany's financial regulator, removing its previous reliance on passporting under its UK licence. The approval unlocks €100,000 deposit protection for German customers and gives Monzo direct access to the Eurozone payments infrastructure. The bank confirmed Berlin as the location for its European headquarters and said it expects to launch current accounts in Germany by September.",
            "source": "THE GUARDIAN",
            "date": "Today",
            "url": "#",
        },
        {
            "num": "05",
            "watchlist": "★ RBI",
            "title": "RBI Issues Corrective Action Framework for Payment Aggregators After Pine Labs Outage",
            "synopsis": "India's Reserve Bank has published a new Prompt Corrective Action framework specifically targeting payment aggregators, requiring firms processing above ₹1,000 crore monthly to maintain minimum liquidity buffers and submit to quarterly stress testing. The framework follows a 14-hour outage at Pine Labs in April that disrupted point-of-sale terminals across approximately 600,000 merchants. Non-compliant aggregators face mandatory volume restrictions pending remediation.",
            "source": "ECONOMIC TIMES",
            "date": "Today",
            "url": "#",
        },
        {
            "num": "06",
            "watchlist": "",
            "title": "Goldman Sachs Asset Management Closes $3.2B Private Credit Fund Targeting Mid-Market Lending",
            "synopsis": "Goldman Sachs Asset Management has closed its West Street Mid-Market Lending Partners fund at $3.2 billion, exceeding its original $2.5 billion target. The fund targets senior secured loans to North American companies with EBITDA between $10–75 million, a segment the firm says is underserved following the exit of several regional banks from syndicated lending. This is GSAM's largest private credit close to date and reflects continued institutional appetite for direct lending.",
            "source": "WALL STREET JOURNAL",
            "date": "Today",
            "url": "#",
        },
    ]

    stories_html = ""
    for i, s in enumerate(stories, 1):
        up_link = f"{base}/feedback?signal=1&url={s['url']}&title=Demo+Story&source=Demo&run_id=demo&user_id=1"
        down_link = f"{base}/feedback?signal=-1&url={s['url']}&title=Demo+Story&source=Demo&run_id=demo&user_id=1"

        watchlist_badge = ""
        if s["watchlist"]:
            watchlist_badge = f"""<span style="font-family:'Courier New',monospace;font-size:9px;
              font-weight:bold;letter-spacing:1px;text-transform:uppercase;
              background:#1a3a2e;color:#4ade80;padding:2px 6px;border-radius:3px;
              margin-right:6px;">{s["watchlist"]}</span>"""

        stories_html += f"""
        <tr><td style="padding:0 0 28px 0;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding-bottom:6px;">
              {watchlist_badge}
              <span style="font-family:Georgia,serif;font-size:11px;font-weight:bold;
                letter-spacing:2px;text-transform:uppercase;color:#8a7355;">{s["num"]}</span>
            </td></tr>
            <tr><td style="padding-bottom:8px;">
              <a href="{s['url']}" style="font-family:Georgia,serif;font-size:18px;
                font-weight:bold;color:#1a1a2e;text-decoration:none;line-height:1.3;">
                {s["title"]}
              </a>
            </td></tr>
            <tr><td style="padding-bottom:10px;">
              <p style="font-family:Georgia,serif;font-size:15px;color:#2d2d2d;
                line-height:1.65;margin:0;">{s["synopsis"]}</p>
            </td></tr>
            <tr><td>
              <span style="font-family:'Courier New',monospace;font-size:11px;
                color:#8a7355;letter-spacing:1px;">{s["source"]} · {s["date"]}</span>
              &nbsp;&nbsp;
              <a href="{s['url']}" style="font-family:'Courier New',monospace;
                font-size:11px;color:#1a56db;">READ →</a>
              &nbsp;&nbsp;&nbsp;
              <a href="{up_link}" style="font-size:12px;color:#4ade80;text-decoration:none;"
                title="Useful story">👍</a>
              &nbsp;
              <a href="{down_link}" style="font-size:12px;color:#f87171;text-decoration:none;"
                title="Not relevant">👎</a>
            </td></tr>
          </table>
          <hr style="border:none;border-top:1px solid #e8e2d9;margin:0;padding-top:28px;">
        </td></tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FinTech Morning Briefing — {today}</title>
</head>
<body style="margin:0;padding:0;background-color:#f5f0e8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f0e8;">
    <tr><td align="center" style="padding:32px 16px;">
      <table width="640" cellpadding="0" cellspacing="0"
        style="max-width:640px;background:#fffef9;border:1px solid #e0d8cc;">

        <tr><td style="background:#1a1a2e;padding:28px 40px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td>
              <p style="font-family:'Courier New',monospace;font-size:10px;
                letter-spacing:3px;color:#8a7355;text-transform:uppercase;margin:0 0 8px;">
                FINTECH INTELLIGENCE</p>
              <p style="font-family:Georgia,serif;font-size:26px;font-weight:bold;
                color:#fffef9;margin:0;line-height:1.2;">Morning Briefing</p>
            </td>
            <td align="right" valign="middle">
              <p style="font-family:'Courier New',monospace;font-size:11px;
                color:#8a7355;margin:0;text-align:right;">
                {today}<br>
                <span style="font-size:10px;">6 STORIES · 9:00 IST</span>
              </p>
            </td>
          </tr></table>
        </td></tr>

        <tr><td style="background:#2d3561;padding:14px 40px;">
          <p style="font-family:Georgia,serif;font-size:13px;font-style:italic;
            color:#c8c0e0;margin:0;">
            EU open banking mandate triggers platform pivot; HSBC deepens AI fraud partnership
          </p>
        </td></tr>

        <tr><td style="padding:32px 40px 8px 40px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            {stories_html}
          </table>
        </td></tr>

        <tr><td style="background:#f0ebe0;padding:20px 40px;border-top:2px solid #1a1a2e;">
          <p style="font-family:'Courier New',monospace;font-size:10px;color:#9a9080;
            margin:0 0 6px;letter-spacing:1px;text-transform:uppercase;">
            FinTech Intelligence Agent · Demo Mode · Automated Daily Briefing
          </p>
          <p style="font-family:'Courier New',monospace;font-size:10px;color:#9a9080;margin:0;">
            👍 👎 clicks teach the agent your preferences — it gets smarter over time.
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


DEMO_RUN_HISTORY = [
    {"timestamp": "2025-05-09 09:00 UTC", "status": "success", "stories": 7, "duration_s": 42.3, "run_id": "demo-001"},
    {"timestamp": "2025-05-08 09:00 UTC", "status": "success", "stories": 6, "duration_s": 38.7, "run_id": "demo-002"},
    {"timestamp": "2025-05-07 09:00 UTC", "status": "success", "stories": 8, "duration_s": 51.2, "run_id": "demo-003"},
    {"timestamp": "2025-05-06 09:00 UTC", "status": "aborted: All stories seen in last 7 days", "stories": 0, "duration_s": 12.1, "run_id": "demo-004"},
    {"timestamp": "2025-05-05 09:00 UTC", "status": "success", "stories": 7, "duration_s": 44.8, "run_id": "demo-005"},
]