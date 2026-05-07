"""
app/delivery/slack.py — Slack delivery channel.

Sends the digest as a Slack thread: one message per story with
title, one-line synopsis, source, and link. Clean enough to read
in the Slack mobile app.

Setup:
  1. Create a Slack app at api.slack.com/apps
  2. Add OAuth scope: chat:write
  3. Install to workspace, copy Bot User OAuth Token → SLACK_BOT_TOKEN
  4. Invite the bot to your channel: /invite @YourBotName
  5. Copy the channel ID (starts with C) → SLACK_CHANNEL_ID

Free tier: Slack API is completely free for personal/small team use.
"""

import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def _get_client():
    """Lazy-load the Slack WebClient."""
    try:
        from slack_sdk import WebClient
        return WebClient(token=settings.SLACK_BOT_TOKEN)
    except ImportError:
        raise RuntimeError("slack-sdk not installed. Run: pip install slack-sdk")


def is_configured() -> bool:
    return bool(settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID)


def send_digest_to_slack(subject: str, stories: list[dict]) -> bool:
    """
    Send the digest to Slack as a thread.
    - Header message: date + subject line
    - One reply per story with title, synopsis snippet, source, link
    Returns True on success.
    """
    if not is_configured():
        logger.info("[slack] Not configured — skipping")
        return False

    try:
        client = _get_client()
        from datetime import date
        today = date.today().strftime("%A, %-d %b %Y")

        # Post the header as the parent message
        header_response = client.chat_postMessage(
            channel=settings.SLACK_CHANNEL_ID,
            text=f"🏦 *FinTech Morning Briefing — {today}*\n_{subject}_",
            unfurl_links=False,
        )
        thread_ts = header_response["ts"]

        # Reply with each story as a thread message
        for i, story in enumerate(stories, 1):
            synopsis = story.get("synopsis", story.get("snippet", ""))
            # Truncate synopsis to first sentence for Slack compactness
            first_sentence = synopsis.split(".")[0].strip() + "." if synopsis else ""
            source = story.get("source", "").upper()
            watchlist = story.get("watchlist_entity")
            watchlist_tag = f" `★ {watchlist}`" if watchlist else ""

            story_text = (
                f"*{i:02d}.{watchlist_tag} {story['title']}*\n"
                f"{first_sentence}\n"
                f"_{source}_ · <{story['url']}|Read →>"
            )

            client.chat_postMessage(
                channel=settings.SLACK_CHANNEL_ID,
                thread_ts=thread_ts,
                text=story_text,
                unfurl_links=False,
            )

        logger.info(f"[slack] Sent {len(stories)} stories to channel {settings.SLACK_CHANNEL_ID}")
        return True

    except Exception as e:
        logger.error(f"[slack] Delivery failed: {e}")
        return False


def send_alert_to_slack(title: str, synopsis: str, url: str, urgency: int) -> bool:
    """Send a breaking news alert as a standalone Slack message (not threaded)."""
    if not is_configured():
        return False

    try:
        client = _get_client()
        text = (
            f"🚨 *BREAKING ({urgency}/10 urgency)*\n"
            f"*{title}*\n"
            f"{synopsis[:200]}\n"
            f"<{url}|Read full story →>"
        )
        client.chat_postMessage(
            channel=settings.SLACK_CHANNEL_ID,
            text=text,
            unfurl_links=False,
        )
        logger.info(f"[slack] Alert sent: {title[:60]}")
        return True
    except Exception as e:
        logger.error(f"[slack] Alert failed: {e}")
        return False