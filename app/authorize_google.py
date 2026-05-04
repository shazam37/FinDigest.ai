#!/usr/bin/env python3
"""
Run this ONCE locally to authorize Google OAuth and generate token.json.
After running, set the contents of token.json as GOOGLE_TOKEN_JSON env var on Render.

Usage:
    python scripts/authorize_google.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from google_auth_oauthlib.flow import InstalledAppFlow
from app.config import settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
]


def main():
    creds_path = settings.GOOGLE_CREDENTIALS_PATH
    if not os.path.exists(creds_path):
        print(f"ERROR: Credentials file not found at {creds_path}")
        print("Download OAuth2 credentials from Google Cloud Console and save there.")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0)

    os.makedirs(os.path.dirname(settings.GOOGLE_TOKEN_PATH), exist_ok=True)
    with open(settings.GOOGLE_TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

    print(f"\n✅ Token saved to {settings.GOOGLE_TOKEN_PATH}")
    print("\n📋 Copy the contents below as GOOGLE_TOKEN_JSON env var on Render:\n")
    with open(settings.GOOGLE_TOKEN_PATH) as f:
        token_data = json.load(f)
    print(json.dumps(token_data))


if __name__ == "__main__":
    main()