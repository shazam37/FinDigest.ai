"""
app/delivery/channels.py — Multi-channel delivery fan-out.

Coordinates delivery to all configured channels:
  - Email (Gmail) — always primary
  - Slack — if SLACK_BOT_TOKEN + SLACK_CHANNEL_ID set
  - Telegram — if TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID set

Each channel is attempted independently. A failure in Slack
does not prevent Telegram delivery, and vice versa.

Called from delivery_agent after the Gmail send succeeds.
"""

import logging

from app.config import settings

logger = logging.getLogger(__name__)


async def fan_out_digest(subject: str, stories: list[dict]) -> dict:
    """
    Send the digest to all configured non-email channels.
    Returns a dict of {channel: bool} delivery results.
    """
    results = {}

    # Slack
    if settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID:
        try:
            from app.delivery.slack import send_digest_to_slack
            results["slack"] = send_digest_to_slack(subject, stories)
        except Exception as e:
            logger.error(f"[channels] Slack fan-out failed: {e}")
            results["slack"] = False
    else:
        results["slack"] = None  # Not configured

    # Telegram
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        try:
            from app.delivery.telegram import send_digest_to_telegram
            results["telegram"] = send_digest_to_telegram(subject, stories)
        except Exception as e:
            logger.error(f"[channels] Telegram fan-out failed: {e}")
            results["telegram"] = False
    else:
        results["telegram"] = None  # Not configured

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

    return results