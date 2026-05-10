"""
app/delivery/channels.py — Multi-channel delivery fan-out.

Channels: Email (primary) · Slack · Telegram · WhatsApp
Each channel fails independently — one failure never blocks others.
"""

import logging
from app.config import settings

logger = logging.getLogger(__name__)


async def fan_out_digest(subject: str, stories: list[dict]) -> dict:
    """Send digest to all configured non-email channels."""
    results = {}

    if settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID:
        try:
            from app.delivery.slack import send_digest_to_slack
            results["slack"] = send_digest_to_slack(subject, stories)
        except Exception as e:
            logger.error(f"[channels] Slack failed: {e}")
            results["slack"] = False
    else:
        results["slack"] = None

    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        try:
            from app.delivery.telegram import send_digest_to_telegram
            results["telegram"] = send_digest_to_telegram(subject, stories)
        except Exception as e:
            logger.error(f"[channels] Telegram failed: {e}")
            results["telegram"] = False
    else:
        results["telegram"] = None

    if getattr(settings, "TWILIO_ACCOUNT_SID", None) and getattr(settings, "WHATSAPP_TO", None):
        try:
            from app.delivery.whatsapp import send_digest_to_whatsapp
            results["whatsapp"] = send_digest_to_whatsapp(subject, stories)
        except Exception as e:
            logger.error(f"[channels] WhatsApp failed: {e}")
            results["whatsapp"] = False
    else:
        results["whatsapp"] = None

    configured = [k for k, v in results.items() if v is not None]
    sent = [k for k, v in results.items() if v is True]
    if configured:
        logger.info(f"[channels] Fan-out: {sent}/{configured} additional channels")

    return results


async def fan_out_alert(title: str, synopsis: str, url: str, urgency: int) -> dict:
    """Send a breaking alert to all configured channels."""
    results = {}

    if settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID:
        try:
            from app.delivery.slack import send_alert_to_slack
            results["slack"] = send_alert_to_slack(title, synopsis, url, urgency)
        except Exception as e:
            logger.error(f"[channels] Slack alert failed: {e}")
            results["slack"] = False

    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        try:
            from app.delivery.telegram import send_alert_to_telegram
            results["telegram"] = send_alert_to_telegram(title, synopsis, url, urgency)
        except Exception as e:
            logger.error(f"[channels] Telegram alert failed: {e}")
            results["telegram"] = False

    if getattr(settings, "TWILIO_ACCOUNT_SID", None) and getattr(settings, "WHATSAPP_TO", None):
        try:
            from app.delivery.whatsapp import send_alert_to_whatsapp
            results["whatsapp"] = send_alert_to_whatsapp(title, synopsis, url, urgency)
        except Exception as e:
            logger.error(f"[channels] WhatsApp alert failed: {e}")
            results["whatsapp"] = False

    return results