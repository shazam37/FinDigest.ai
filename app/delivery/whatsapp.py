"""
app/delivery/whatsapp.py — WhatsApp delivery via Twilio.

Setup (free Twilio sandbox — no credit card needed):
  1. Sign up at twilio.com
  2. Go to Messaging → Try it out → Send a WhatsApp message
  3. Follow the sandbox activation (send a code to +1 415 523 8886)
  4. Copy Account SID and Auth Token
  5. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, WHATSAPP_TO in .env

Free sandbox limits:
  - Must activate sandbox by messaging Twilio's number first
  - Messages only go to verified numbers
  - No cost for sandbox testing

For production (verified business account):
  - Apply for WhatsApp Business API approval (~1-2 weeks)
  - Set TWILIO_WHATSAPP_FROM to your approved number

Message format:
  WhatsApp renders markdown: *bold*, _italic_, ```code```
  Each story is a separate message to stay within WhatsApp's 4096-char limit.
"""

import logging
from app.config import settings

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(
        settings.TWILIO_ACCOUNT_SID
        and settings.TWILIO_AUTH_TOKEN
        and settings.WHATSAPP_TO
    )


def _get_client():
    try:
        from twilio.rest import Client
        return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    except ImportError:
        raise RuntimeError("twilio not installed. Run: pip install twilio")


def _send(to: str, body: str) -> bool:
    """Send a single WhatsApp message via Twilio."""
    try:
        client = _get_client()
        from_number = getattr(settings, "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
        if not from_number.startswith("whatsapp:"):
            from_number = f"whatsapp:{from_number}"
        to_number = to if to.startswith("whatsapp:") else f"whatsapp:{to}"

        client.messages.create(body=body, from_=from_number, to=to_number)
        return True
    except Exception as e:
        logger.error(f"[whatsapp] Send failed: {e}")
        return False


def send_digest_to_whatsapp(subject: str, stories: list[dict]) -> bool:
    """
    Send the digest to WhatsApp.
    Header + one message per story.
    """
    if not is_configured():
        logger.info("[whatsapp] Not configured — skipping")
        return False

    from datetime import date
    to = settings.WHATSAPP_TO
    today = date.today().strftime("%-d %b %Y")

    # Header message
    _send(to, f"🏦 *FinTech Intelligence — {today}*\n_{subject}_")

    sent = 0
    for i, story in enumerate(stories, 1):
        synopsis = story.get("synopsis", story.get("snippet", ""))
        # First sentence only for WhatsApp compactness
        first_sentence = synopsis.split(".")[0].strip() + "." if synopsis else ""
        source = story.get("source", "").upper()
        watchlist = story.get("watchlist_entity")
        wl_tag = f"★ _{watchlist}_ | " if watchlist else ""

        body = (
            f"*{i:02d}. {story['title']}*\n"
            f"_{wl_tag}{source}_\n\n"
            f"{first_sentence}\n\n"
            f"{story['url']}"
        )

        if _send(to, body):
            sent += 1

    logger.info(f"[whatsapp] Sent {sent}/{len(stories)} stories to {to}")
    return sent > 0


def send_alert_to_whatsapp(title: str, synopsis: str, url: str, urgency: int) -> bool:
    """Send a breaking news alert to WhatsApp."""
    if not is_configured():
        return False

    body = (
        f"🚨 *BREAKING NEWS* _(urgency {urgency}/10)_\n\n"
        f"*{title}*\n\n"
        f"{synopsis[:300]}\n\n"
        f"{url}"
    )
    return _send(settings.WHATSAPP_TO, body)


def send_weekly_synthesis_to_whatsapp(subject: str, themes: list[dict]) -> bool:
    """Send Friday synthesis summary to WhatsApp."""
    if not is_configured():
        return False

    from datetime import date
    today = date.today().strftime("%-d %b %Y")

    _send(settings.WHATSAPP_TO, f"📋 *FinTech Week in Review — {today}*\n_{subject}_")

    for i, theme in enumerate(themes, 1):
        body = (
            f"*Theme {i}: {theme.get('title', '')}*\n\n"
            f"{theme.get('narrative', '')[:400]}"
        )
        _send(settings.WHATSAPP_TO, body)

    return True