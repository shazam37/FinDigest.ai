#!/usr/bin/env python3
"""
Register the Telegram webhook URL with the Bot API after first deploy.

Run this ONCE after deploying to Render:
    TELEGRAM_BOT_TOKEN=xxx APP_BASE_URL=https://your-app.onrender.com python scripts/setup_telegram.py

Or with .env loaded:
    python scripts/setup_telegram.py
"""

import os
import sys
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def main():
    from app.config import settings

    token = settings.TELEGRAM_BOT_TOKEN
    base_url = settings.APP_BASE_URL

    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    webhook_url = f"{base_url}/telegram/webhook"
    api_url = f"https://api.telegram.org/bot{token}/setWebhook"

    print(f"Registering webhook: {webhook_url}")

    resp = httpx.post(api_url, json={"url": webhook_url, "allowed_updates": ["message"]})
    data = resp.json()

    if data.get("ok"):
        print(f"✅ Webhook registered successfully!")
        print(f"   URL: {webhook_url}")
    else:
        print(f"❌ Failed: {data}")
        sys.exit(1)

    # Get bot info
    info = httpx.get(f"https://api.telegram.org/bot{token}/getMe").json()
    if info.get("ok"):
        bot = info["result"]
        print(f"\nBot: @{bot['username']} ({bot['first_name']})")
        print(f"Start chatting: https://t.me/{bot['username']}")

    # Get your chat ID if not already set
    if not settings.TELEGRAM_CHAT_ID:
        print(f"\nTo get your TELEGRAM_CHAT_ID:")
        print(f"  1. Send any message to your bot")
        print(f"  2. Visit: https://api.telegram.org/bot{token}/getUpdates")
        print(f"  3. Copy the 'id' from message.chat in the response")
        print(f"  4. Set TELEGRAM_CHAT_ID=<that_id> in your Render env vars")


if __name__ == "__main__":
    main()