"""
app/routers/subscribe.py — Public subscribe flow with onboarding.

Three pages:
  GET  /subscribe                    — email + name entry form
  GET  /subscribe/onboard?token=...  — sector/region/role preference form
  POST /subscribe/onboard            — save preferences, send welcome email
  GET  /subscribe/confirm?token=...  — email confirmation link
  GET  /unsubscribe?token=...        — one-click unsubscribe (linked from email footer)

Flow:
  1. User visits /subscribe, enters name + email
  2. System creates user, sends confirmation email with onboarding link
  3. User clicks link → /subscribe/onboard → selects sectors, regions, role
  4. Preferences saved immediately → first digest uses them from day one
  5. Welcome email sent with instructions

This is the shareable URL you give to colleagues or put in a demo.
"""

import logging
import secrets
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.config import settings
from app.database import (
    get_conn,
    get_or_create_default_user,
    upsert_user_onboarding,
    fetch_user_onboarding,
    get_user_by_unsubscribe_token,
)
from app.gmail import send_digest_email

logger = logging.getLogger(__name__)
router = APIRouter(tags=["subscribe"])

SECTORS = [
    ("payments",    "💳 Payments",          "Digital payments, card networks, wallets"),
    ("banking",     "🏦 Banking",           "Retail & commercial banking, neobanks"),
    ("regulation",  "⚖️ Regulation",        "FCA, RBI, ECB, enforcement actions"),
    ("lending",     "💰 Lending & Credit",  "BNPL, mortgages, consumer credit"),
    ("wealth",      "📈 Wealth Management", "Asset management, robo-advisors, funds"),
    ("crypto",      "₿ Crypto & DeFi",     "Blockchain, digital assets, CBDCs"),
    ("insurance",   "🛡 InsurTech",         "Insurance technology and disruption"),
    ("fraud",       "🔒 Fraud & Security",  "Financial crime, cybersecurity incidents"),
    ("cbdc",        "🏛 CBDC",              "Central bank digital currencies"),
    ("openbanking", "🔗 Open Banking",      "APIs, PSD3, financial data sharing"),
]

REGIONS = [
    ("uk",     "🇬🇧 United Kingdom"),
    ("india",  "🇮🇳 India"),
    ("us",     "🇺🇸 United States"),
    ("eu",     "🇪🇺 European Union"),
    ("apac",   "🌏 Asia Pacific"),
    ("global", "🌍 Global"),
]

ROLES = [
    ("executive",    "C-Suite / Executive",    "Balanced briefing across all topics"),
    ("risk_officer", "Risk / Compliance",       "Regulation, fraud, enforcement weighted higher"),
    ("product_lead", "Product / Technology",    "Innovation, APIs, product launches weighted higher"),
    ("investor",     "Investor / Analyst",      "M&A, funding rounds, market entries weighted higher"),
]


def _page(title: str, content: str) -> str:
    """Shared HTML shell for subscribe pages — standalone, no dashboard nav."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — FinTech Intelligence</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: Georgia, serif; background: #0a0a0f; color: #e2e2e8;
           min-height: 100vh; display: flex; align-items: center;
           justify-content: center; padding: 2rem 1rem; }}
    .card {{ background: #13131a; border: 1px solid #2a2a3a; border-radius: 12px;
             padding: 2.5rem; max-width: 560px; width: 100%; }}
    .logo {{ font-family: 'Courier New', monospace; font-size: 10px;
             letter-spacing: 3px; color: #c9a96e; text-transform: uppercase;
             margin-bottom: 0.5rem; }}
    h1 {{ font-size: 24px; color: #e2e2e8; margin-bottom: 0.5rem; }}
    .subtitle {{ font-size: 14px; color: #94a3b8; margin-bottom: 2rem;
                 line-height: 1.6; }}
    label {{ display: block; font-family: 'Courier New', monospace;
             font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase;
             color: #94a3b8; margin-bottom: 6px; margin-top: 1.25rem; }}
    input[type=text], input[type=email] {{
      width: 100%; padding: 0.6rem 0.85rem;
      background: #1c1c26; border: 1px solid #2a2a3a; border-radius: 8px;
      color: #e2e2e8; font-family: Georgia, serif; font-size: 15px; }}
    input:focus {{ outline: none; border-color: #60a5fa; }}
    .sector-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
                    margin-top: 0.5rem; }}
    .region-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px;
                    margin-top: 0.5rem; }}
    .check-item {{ position: relative; }}
    .check-item input[type=checkbox] {{ position: absolute; opacity: 0; width: 0; }}
    .check-item label {{
      display: flex; align-items: flex-start; gap: 8px;
      padding: 0.6rem 0.75rem; background: #1c1c26;
      border: 1px solid #2a2a3a; border-radius: 8px; cursor: pointer;
      font-family: Georgia, serif; font-size: 13px; letter-spacing: 0;
      text-transform: none; color: #e2e2e8; margin: 0; line-height: 1.4;
      transition: border-color 0.15s; }}
    .check-item input:checked + label {{
      border-color: #60a5fa; background: rgba(96,165,250,0.08); }}
    .check-item label:hover {{ border-color: #4a4a5a; }}
    .role-list {{ display: flex; flex-direction: column; gap: 8px; margin-top: 0.5rem; }}
    .role-item {{ position: relative; }}
    .role-item input[type=radio] {{ position: absolute; opacity: 0; width: 0; }}
    .role-item label {{
      display: flex; flex-direction: column; padding: 0.75rem 1rem;
      background: #1c1c26; border: 1px solid #2a2a3a; border-radius: 8px;
      cursor: pointer; font-family: Georgia, serif; font-size: 14px;
      letter-spacing: 0; text-transform: none; color: #e2e2e8; margin: 0;
      transition: border-color 0.15s; }}
    .role-item label .role-desc {{
      font-size: 12px; color: #94a3b8; margin-top: 3px; font-style: italic; }}
    .role-item input:checked + label {{
      border-color: #60a5fa; background: rgba(96,165,250,0.08); }}
    .btn {{ display: block; width: 100%; padding: 0.85rem; margin-top: 2rem;
            background: #60a5fa; color: #fff; border: none; border-radius: 8px;
            font-family: 'Courier New', monospace; font-size: 13px;
            letter-spacing: 1px; text-transform: uppercase; cursor: pointer;
            transition: opacity 0.15s; }}
    .btn:hover {{ opacity: 0.9; }}
    .note {{ font-size: 12px; color: #64748b; margin-top: 1rem;
             text-align: center; line-height: 1.5; }}
    .success {{ text-align: center; }}
    .success .icon {{ font-size: 3rem; margin-bottom: 1rem; }}
    .success h2 {{ font-size: 20px; margin-bottom: 0.5rem; }}
    .success p {{ font-size: 14px; color: #94a3b8; line-height: 1.6; }}
    .error {{ color: #f87171; font-size: 13px; margin-top: 0.5rem; }}
    @media(max-width:480px) {{
      .sector-grid {{ grid-template-columns: 1fr; }}
      .region-grid {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="card">
    {content}
  </div>
</body>
</html>"""


# ── Step 1: Email entry ───────────────────────────────────────────────────────

@router.get("/subscribe", response_class=HTMLResponse)
async def subscribe_page(error: str = ""):
    error_html = f'<p class="error">⚠ {error}</p>' if error else ""
    content = f"""
    <div class="logo">FinTech Intelligence</div>
    <h1>Daily Briefing</h1>
    <p class="subtitle">
      A personalised AI-curated fintech digest, delivered to your inbox every morning at 9 AM.
      No share prices. No conference noise. Just what matters.
    </p>
    {error_html}
    <form method="POST" action="/subscribe">
      <label>Your name</label>
      <input type="text" name="name" placeholder="Alex Chen" autocomplete="name">
      <label>Work email *</label>
      <input type="email" name="email" placeholder="you@company.com"
             autocomplete="email" required>
      <button type="submit" class="btn">Get Started →</button>
    </form>
    <p class="note">
      Free forever. Unsubscribe with one click. No spam.
    </p>"""
    return HTMLResponse(_page("Subscribe", content))


@router.post("/subscribe", response_class=HTMLResponse)
async def subscribe_submit(request_body: dict = None):
    """Handle the email + name form submission."""
    from fastapi import Request
    # We need the raw form — use Request directly
    raise HTTPException(status_code=405, detail="Use the form")


# FastAPI form handling requires Form() — use a separate endpoint
from fastapi import Form

@router.post("/subscribe/submit", response_class=HTMLResponse)
async def subscribe_form_submit(
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    name: str = Form(default=""),
):
    email = email.strip().lower()
    name = name.strip()

    if not email or "@" not in email:
        return HTMLResponse(_page("Subscribe",
            f"""<div class="logo">FinTech Intelligence</div>
            <h1>Invalid email</h1>
            <p class="subtitle">Please enter a valid email address.</p>
            <a href="/subscribe" style="color:#60a5fa;">← Try again</a>"""))

    try:
        async with get_conn() as conn:
            # Create or find user
            existing = await (await conn.execute(
                "SELECT id, onboarding_complete FROM users WHERE email = %s", (email,)
            )).fetchone()

            if existing:
                user_id = existing[0]
                already_onboarded = existing[1]
            else:
                row = await (await conn.execute(
                    "INSERT INTO users (email, name) VALUES (%s, %s) RETURNING id",
                    (email, name or email.split("@")[0].title()),
                )).fetchone()
                user_id = row[0]
                already_onboarded = False
                await conn.commit()

        # Generate onboarding token
        token = secrets.token_urlsafe(32)
        async with get_conn() as conn:
            await conn.execute(
                "UPDATE users SET unsubscribe_token = COALESCE(unsubscribe_token, %s) WHERE id = %s",
                (token, user_id),
            )
            await conn.commit()

        # Fetch the actual token (may have already existed)
        onboarding = await fetch_user_onboarding(user_id)
        actual_token = onboarding.get("unsubscribe_token") or token

        if not already_onboarded:
            # Send onboarding email
            onboard_url = f"{settings.APP_BASE_URL}/subscribe/onboard?token={actual_token}"
            background_tasks.add_task(
                _send_onboarding_email, email, name or "there", onboard_url
            )

        onboard_url = f"{settings.APP_BASE_URL}/subscribe/onboard?token={actual_token}"

    except Exception as e:
        logger.error(f"[subscribe] Error: {e}")
        return HTMLResponse(_page("Error",
            f'<div class="logo">FinTech Intelligence</div><h1>Something went wrong</h1>'
            f'<p class="subtitle">{str(e)[:100]}</p>'))

    content = f"""
    <div class="success">
      <div class="icon">📬</div>
      <h2>Almost there!</h2>
      <p>
        Set up your preferences so we send you exactly what matters to you.
        It takes 30 seconds.
      </p>
      <a href="{onboard_url}"
         style="display:inline-block;margin-top:1.5rem;padding:.75rem 2rem;
                background:#60a5fa;color:#fff;border-radius:8px;
                font-family:'Courier New',monospace;font-size:12px;
                letter-spacing:1px;text-transform:uppercase;text-decoration:none;">
        Set My Preferences →
      </a>
    </div>"""
    return HTMLResponse(_page("Check Your Email", content))


# ── Step 2: Onboarding preference form ───────────────────────────────────────

@router.get("/subscribe/onboard", response_class=HTMLResponse)
async def onboard_page(token: str = Query(...)):
    # Verify token
    user = await get_user_by_unsubscribe_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Invalid or expired link")

    sector_items = ""
    for key, label, desc in SECTORS:
        sector_items += f"""
        <div class="check-item">
          <input type="checkbox" name="sectors" value="{key}" id="s_{key}">
          <label for="s_{key}">
            <span>{label}</span>
            <span style="font-size:11px;color:#64748b;font-style:italic;display:block;margin-top:2px;">{desc}</span>
          </label>
        </div>"""

    region_items = ""
    for key, label in REGIONS:
        region_items += f"""
        <div class="check-item">
          <input type="checkbox" name="regions" value="{key}" id="r_{key}">
          <label for="r_{key}">{label}</label>
        </div>"""

    role_items = ""
    for key, label, desc in ROLES:
        checked = 'checked' if key == "executive" else ""
        role_items += f"""
        <div class="role-item">
          <input type="radio" name="role" value="{key}" id="role_{key}" {checked}>
          <label for="role_{key}">
            {label}
            <span class="role-desc">{desc}</span>
          </label>
        </div>"""

    content = f"""
    <div class="logo">FinTech Intelligence</div>
    <h1>Set Your Preferences</h1>
    <p class="subtitle">
      Tell us what matters to you. Your digest will be tailored from day one —
      no waiting for the algorithm to learn.
    </p>

    <form method="POST" action="/subscribe/onboard">
      <input type="hidden" name="token" value="{token}">

      <label>Sectors you care about <span style="color:#64748b">(pick all that apply)</span></label>
      <div class="sector-grid">{sector_items}</div>

      <label style="margin-top:1.5rem;">Regions <span style="color:#64748b">(pick all that apply)</span></label>
      <div class="region-grid">{region_items}</div>

      <label style="margin-top:1.5rem;">Your role</label>
      <div class="role-list">{role_items}</div>

      <button type="submit" class="btn">Start My Briefings →</button>
    </form>

    <p class="note">You can update these anytime from your dashboard.</p>"""

    return HTMLResponse(_page("Your Preferences", content))


@router.post("/subscribe/onboard", response_class=HTMLResponse)
async def onboard_submit(
    background_tasks: BackgroundTasks,
    token: str = Form(...),
    role: str = Form(default="executive"),
    sectors: list[str] = Form(default=[]),
    regions: list[str] = Form(default=[]),
):
    user = await get_user_by_unsubscribe_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Invalid or expired link")

    # Default selections if user skipped
    if not sectors:
        sectors = ["banking", "regulation", "payments"]
    if not regions:
        regions = ["global"]

    await upsert_user_onboarding(
        user_id=user["id"],
        sectors=sectors,
        regions=regions,
        role=role,
        name=user.get("name", ""),
    )

    background_tasks.add_task(
        _send_welcome_email,
        user["email"],
        user.get("name") or "there",
        sectors,
        regions,
        role,
        token,
    )

    logger.info(
        f"[subscribe] Onboarding complete for user {user['id']}: "
        f"sectors={sectors} regions={regions} role={role}"
    )

    content = f"""
    <div class="success">
      <div class="icon">✅</div>
      <h2>You're all set!</h2>
      <p>
        Your first briefing arrives tomorrow at 9 AM, tailored to
        <strong>{', '.join(sectors[:3])}</strong>
        {f'and {len(sectors)-3} more sectors' if len(sectors) > 3 else ''}.
      </p>
      <p style="margin-top:1rem;">
        A welcome email is on its way with everything you need to know.
      </p>
      <a href="{settings.APP_BASE_URL}/dashboard"
         style="display:inline-block;margin-top:1.5rem;padding:.75rem 2rem;
                background:#60a5fa;color:#fff;border-radius:8px;
                font-family:'Courier New',monospace;font-size:12px;
                letter-spacing:1px;text-transform:uppercase;text-decoration:none;">
        Open Dashboard →
      </a>
    </div>"""
    return HTMLResponse(_page("You're subscribed!", content))


# ── Unsubscribe ───────────────────────────────────────────────────────────────

@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(token: str = Query(...)):
    user = await get_user_by_unsubscribe_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Invalid unsubscribe link")

    async with get_conn() as conn:
        await conn.execute(
            "UPDATE users SET active = FALSE WHERE id = %s", (user["id"],)
        )
        await conn.commit()

    logger.info(f"[subscribe] Unsubscribed user {user['id']} ({user['email']})")

    content = f"""
    <div class="success">
      <div class="icon">👋</div>
      <h2>Unsubscribed</h2>
      <p>
        {user.get('name') or 'You'} ({user['email']}) will no longer receive
        the FinTech Intelligence digest.
      </p>
      <p style="margin-top:1rem;font-size:13px;color:#64748b;">
        Changed your mind?
        <a href="/subscribe" style="color:#60a5fa;">Subscribe again →</a>
      </p>
    </div>"""
    return HTMLResponse(_page("Unsubscribed", content))


# ── Email helpers ─────────────────────────────────────────────────────────────

def _send_onboarding_email(email: str, name: str, onboard_url: str):
    subject = "One last step — set your FinTech briefing preferences"
    html = f"""<!DOCTYPE html>
<html><body style="font-family:Georgia,serif;background:#f5f0e8;padding:2rem;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table width="560" style="background:#fffef9;border:1px solid #e0d8cc;max-width:560px;">
  <tr><td style="background:#1a1a2e;padding:24px 36px;">
    <p style="font-family:'Courier New',monospace;font-size:9px;letter-spacing:3px;
      color:#8a7355;margin:0 0 6px;">FINTECH INTELLIGENCE</p>
    <p style="font-family:Georgia,serif;font-size:20px;font-weight:bold;color:#fffef9;margin:0;">
      Hi {name}, you're almost in.</p>
  </td></tr>
  <tr><td style="padding:28px 36px;">
    <p style="font-size:15px;color:#2d2d2d;line-height:1.65;margin:0 0 20px;">
      Click below to set your sector and region preferences.
      This takes 30 seconds and means your very first digest is already tailored to you —
      no waiting for the algorithm to figure out what you care about.
    </p>
    <a href="{onboard_url}"
       style="display:inline-block;padding:12px 28px;background:#1a1a2e;color:#fff;
              font-family:'Courier New',monospace;font-size:12px;letter-spacing:1px;
              text-transform:uppercase;text-decoration:none;border-radius:4px;">
      Set My Preferences →
    </a>
    <p style="margin-top:20px;font-size:12px;color:#9a9080;">
      Or paste this link: {onboard_url}
    </p>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""
    send_digest_email(subject, html)


def _send_welcome_email(
    email: str, name: str,
    sectors: list, regions: list, role: str, token: str,
):
    unsubscribe_url = f"{settings.APP_BASE_URL}/unsubscribe?token={token}"
    dashboard_url = f"{settings.APP_BASE_URL}/dashboard"
    sector_list = ", ".join(s.title() for s in sectors)
    region_list = ", ".join(r.upper() for r in regions)

    subject = "Welcome to FinTech Intelligence — your briefing starts tomorrow"
    html = f"""<!DOCTYPE html>
<html><body style="font-family:Georgia,serif;background:#f5f0e8;padding:2rem;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table width="600" style="background:#fffef9;border:1px solid #e0d8cc;max-width:600px;">
  <tr><td style="background:#1a1a2e;padding:24px 40px;">
    <p style="font-family:'Courier New',monospace;font-size:9px;letter-spacing:3px;
      color:#8a7355;margin:0 0 6px;">FINTECH INTELLIGENCE</p>
    <p style="font-family:Georgia,serif;font-size:22px;font-weight:bold;
      color:#fffef9;margin:0;">Welcome, {name}.</p>
  </td></tr>
  <tr><td style="padding:28px 40px;">
    <p style="font-size:15px;color:#2d2d2d;line-height:1.65;">
      Your first briefing arrives <strong>tomorrow at 9 AM</strong>. Here's what to expect:
    </p>
    <table style="width:100%;margin:16px 0;background:#f0ebe0;border-radius:4px;">
      <tr><td style="padding:12px 16px;">
        <p style="font-family:'Courier New',monospace;font-size:10px;color:#8a7355;
          letter-spacing:1px;margin:0 0 4px;">YOUR FOCUS AREAS</p>
        <p style="font-size:14px;color:#1a1a2e;margin:0;">{sector_list}</p>
      </td></tr>
      <tr><td style="padding:8px 16px 12px;">
        <p style="font-family:'Courier New',monospace;font-size:10px;color:#8a7355;
          letter-spacing:1px;margin:0 0 4px;">YOUR REGIONS</p>
        <p style="font-size:14px;color:#1a1a2e;margin:0;">{region_list}</p>
      </td></tr>
    </table>
    <p style="font-size:15px;color:#2d2d2d;line-height:1.65;">
      Each story in your email has a <strong>👍 / 👎</strong> link.
      Click them — the agent uses your feedback to improve every subsequent digest.
    </p>
    <p style="margin-top:16px;">
      <a href="{dashboard_url}"
         style="display:inline-block;padding:10px 24px;background:#1a1a2e;color:#fff;
                font-family:'Courier New',monospace;font-size:11px;letter-spacing:1px;
                text-transform:uppercase;text-decoration:none;border-radius:4px;">
        Open Dashboard →
      </a>
    </p>
  </td></tr>
  <tr><td style="background:#f0ebe0;padding:14px 40px;border-top:1px solid #e0d8cc;">
    <p style="font-family:'Courier New',monospace;font-size:9px;color:#9a9080;margin:0;">
      FinTech Intelligence ·
      <a href="{unsubscribe_url}" style="color:#9a9080;">Unsubscribe</a>
    </p>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""
    send_digest_email(subject, html)