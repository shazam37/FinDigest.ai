"""
app/delivery/telegram.py — Telegram bot delivery + interactive commands.

Two modes:

1. PUSH DELIVERY
   send_digest_to_telegram() and send_alert_to_telegram() push formatted
   messages to your personal chat when the scheduled digest runs.

2. PULL COMMANDS (via webhook)
   Users can interact with the bot in real time:
     /start    — welcome + status
     /digest   — trigger an on-demand digest run
     /watchlist — show current watchlist
     /add <entity> — add to watchlist
     /remove <n>   — remove watchlist item n
     /ask <query>  — ask the Q&A agent a question about recent stories
     /status   — show last run status

   The webhook endpoint is: POST /telegram/webhook
   Register it with:
     curl https://api.telegram.org/bot{TOKEN}/setWebhook?url={APP_BASE_URL}/telegram/webhook

Setup:
  1. Message @BotFather on Telegram → /newbot → copy token → TELEGRAM_BOT_TOKEN
  2. Message your bot once, then visit:
     https://api.telegram.org/bot{TOKEN}/getUpdates
     Copy the chat.id from the response → TELEGRAM_CHAT_ID
  3. Set the webhook after deploying (see scripts/setup_telegram.py)

Free tier: Telegram Bot API is completely free, no rate limits for personal use.
"""

import json
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def is_configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def _api_url(method: str) -> str:
    return TELEGRAM_API.format(token=settings.TELEGRAM_BOT_TOKEN, method=method)


def send_message(chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
    """Send a message to a Telegram chat. Synchronous (uses httpx)."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return False
    try:
        resp = httpx.post(
            _api_url("sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"[telegram] send_message failed: {e}")
        return False


def send_digest_to_telegram(subject: str, stories: list[dict]) -> bool:
    """
    Send the digest to Telegram as a series of messages.
    Telegram has a 4096-char limit per message, so each story is its own message.
    """
    if not is_configured():
        logger.info("[telegram] Not configured — skipping")
        return False

    from datetime import date
    today = date.today().strftime("%-d %b %Y")
    chat_id = settings.TELEGRAM_CHAT_ID

    # Header
    send_message(chat_id, f"🏦 *FinTech Briefing — {today}*\n_{subject}_")

    for i, story in enumerate(stories, 1):
        synopsis = story.get("synopsis", story.get("snippet", ""))
        first_sentence = synopsis.split(".")[0].strip() + "." if synopsis else ""
        source = story.get("source", "").upper()
        watchlist = story.get("watchlist_entity")
        wl_tag = f"★ {watchlist} | " if watchlist else ""

        text = (
            f"*{i:02d}. {story['title']}*\n"
            f"_{wl_tag}{source}_\n\n"
            f"{first_sentence}\n\n"
            f"[Read →]({story['url']})"
        )
        send_message(chat_id, text)

    logger.info(f"[telegram] Sent {len(stories)} stories to chat {chat_id}")
    return True


def send_alert_to_telegram(title: str, synopsis: str, url: str, urgency: int) -> bool:
    """Send a breaking news alert to Telegram."""
    if not is_configured():
        return False
    text = (
        f"🚨 *BREAKING NEWS* _(urgency {urgency}/10)_\n\n"
        f"*{title}*\n\n"
        f"{synopsis[:300]}\n\n"
        f"[Read full story →]({url})"
    )
    return send_message(settings.TELEGRAM_CHAT_ID, text)


# ── Webhook handler ───────────────────────────────────────────────────────────

async def handle_webhook(body: dict) -> None:
    """
    Process an incoming Telegram update (command or message).
    Called from the POST /telegram/webhook FastAPI endpoint.
    Runs async so it can call the Q&A agent.
    """
    message = body.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()

    if not chat_id or not text:
        return

    logger.info(f"[telegram] Received: {text[:80]} from chat {chat_id}")

    # Route commands
    if text.startswith("/start"):
        await _cmd_start(chat_id)
    elif text.startswith("/digest"):
        await _cmd_digest(chat_id)
    elif text.startswith("/status"):
        await _cmd_status(chat_id)
    elif text.startswith("/watchlist"):
        await _cmd_watchlist(chat_id)
    elif text.startswith("/add "):
        entity = text[5:].strip()
        await _cmd_add(chat_id, entity)
    elif text.startswith("/remove "):
        await _cmd_remove(chat_id, text[8:].strip())
    elif text.startswith("/ask "):
        query = text[5:].strip()
        await _cmd_ask(chat_id, query)
    else:
        # Treat any non-command message as a Q&A query
        await _cmd_ask(chat_id, text)


async def _cmd_start(chat_id: str):
    send_message(chat_id,
        "👋 *FinTech Intelligence Agent*\n\n"
        "I send you daily fintech briefings and can answer questions about recent news.\n\n"
        "*Commands:*\n"
        "/digest — trigger a digest now\n"
        "/status — last run status\n"
        "/watchlist — view your watchlist\n"
        "/add <company> — watch an entity\n"
        "/remove <n> — remove watchlist item\n"
        "/ask <question> — ask about recent news\n\n"
        "_Or just type any question directly._"
    )


async def _cmd_status(chat_id: str):
    from app.state import agent_state
    last_run = agent_state.get("last_run", "Never")
    last_status = agent_state.get("last_status", "—")
    stories = agent_state.get("stories_found", 0)
    send_message(chat_id,
        f"📊 *Agent Status*\n\n"
        f"Last run: {last_run}\n"
        f"Status: {last_status}\n"
        f"Stories: {stories}"
    )


async def _cmd_digest(chat_id: str):
    send_message(chat_id, "⏳ Triggering digest… I'll send the stories shortly.")
    try:
        from app.graph.digest_graph import run_fintech_digest
        import asyncio
        asyncio.create_task(run_fintech_digest())
    except Exception as e:
        send_message(chat_id, f"❌ Failed to trigger digest: {e}")


async def _cmd_watchlist(chat_id: str):
    try:
        from app.database import fetch_watchlist, get_or_create_default_user
        user_id = await get_or_create_default_user()
        entities = await fetch_watchlist(user_id)
        if not entities:
            send_message(chat_id, "Your watchlist is empty. Use /add <company> to start tracking.")
            return
        lines = "\n".join(f"{i}. {e['entity']} _{e['entity_type']}_"
                          for i, e in enumerate(entities, 1))
        send_message(chat_id, f"👁 *Your Watchlist*\n\n{lines}")
    except Exception as e:
        send_message(chat_id, f"❌ Error: {e}")


async def _cmd_add(chat_id: str, entity: str):
    if not entity:
        send_message(chat_id, "Usage: /add <entity name>  e.g. /add HSBC")
        return
    try:
        from app.database import add_watchlist_entity, get_or_create_default_user
        user_id = await get_or_create_default_user()
        await add_watchlist_entity(user_id, entity)
        send_message(chat_id, f"✅ *{entity}* added to your watchlist.")
    except Exception as e:
        send_message(chat_id, f"❌ Error: {e}")


async def _cmd_remove(chat_id: str, index_str: str):
    try:
        from app.database import fetch_watchlist, remove_watchlist_entity, get_or_create_default_user
        user_id = await get_or_create_default_user()
        entities = await fetch_watchlist(user_id)
        idx = int(index_str) - 1
        if idx < 0 or idx >= len(entities):
            send_message(chat_id, f"Invalid number. You have {len(entities)} watchlist items.")
            return
        entity = entities[idx]
        await remove_watchlist_entity(user_id, entity["id"])
        send_message(chat_id, f"✅ *{entity['entity']}* removed from watchlist.")
    except (ValueError, IndexError):
        send_message(chat_id, "Usage: /remove <number>  e.g. /remove 2")
    except Exception as e:
        send_message(chat_id, f"❌ Error: {e}")


async def _cmd_ask(chat_id: str, query: str):
    """Route the query to the conversational Q&A agent."""
    send_message(chat_id, "🔍 Searching recent stories…")
    try:
        from app.routers.chat import answer_question
        answer = await answer_question(query, user_id=1)
        # Truncate for Telegram (4096 char limit)
        text = answer[:3800] + "…" if len(answer) > 3800 else answer
        send_message(chat_id, text)
    except Exception as e:
        logger.error(f"[telegram] Q&A failed: {e}")
        send_message(chat_id, "❌ Could not answer that question right now. Try again later.")