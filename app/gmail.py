"""
Gmail sender using the Gmail API with OAuth2.
Also creates a Google Calendar event to confirm the send time.

First-time setup:
  1. Enable Gmail API + Calendar API in Google Cloud Console
  2. Create OAuth2 credentials (Desktop app type)
  3. Download as credentials/google_credentials.json
  4. Run: python scripts/authorize_google.py
  5. This creates credentials/token.json

On Render: Set GOOGLE_CREDENTIALS_JSON and GOOGLE_TOKEN_JSON env vars
           (paste the file contents as environment variables)
"""

import base64
import json
import logging
import os
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import pytz

from app.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
]


def _get_credentials() -> Credentials:
    """Load or refresh Google OAuth2 credentials."""
    creds = None

    # Production: load from environment variable (JSON string)
    if settings.GOOGLE_CREDENTIALS_JSON:
        token_env = os.environ.get("GOOGLE_TOKEN_JSON")
        if token_env:
            token_data = json.loads(token_env)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)

    # Local dev: load from file
    elif os.path.exists(settings.GOOGLE_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(settings.GOOGLE_TOKEN_PATH, SCOPES)

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            creds = None

    if not creds or not creds.valid:
        raise RuntimeError(
            "No valid Google credentials. Run scripts/authorize_google.py locally first, "
            "then set GOOGLE_TOKEN_JSON env var on Render."
        )

    return creds


def _save_token(creds: Credentials):
    """Persist refreshed token."""
    token_data = json.loads(creds.to_json())
    if settings.GOOGLE_CREDENTIALS_JSON:
        # In production, log the new token so you can update the env var if needed
        logger.info("Token refreshed. Update GOOGLE_TOKEN_JSON env var if needed.")
    else:
        os.makedirs(os.path.dirname(settings.GOOGLE_TOKEN_PATH), exist_ok=True)
        with open(settings.GOOGLE_TOKEN_PATH, "w") as f:
            json.dump(token_data, f)


def send_digest_email(subject: str, html_body: str) -> bool:
    """Send the digest email via Gmail API. Returns True on success."""
    try:
        creds = _get_credentials()
        service = build("gmail", "v1", credentials=creds)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🏦 {subject}"
        msg["From"] = settings.SENDER_EMAIL
        msg["To"] = settings.RECIPIENT_EMAIL

        # Plain text fallback for email clients that don't render HTML
        plain = _html_to_plain(html_body)
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()

        logger.info(f"Email sent to {settings.RECIPIENT_EMAIL}: {subject}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def create_calendar_confirmation(subject: str, story_count: int) -> bool:
    """
    Create a brief Google Calendar event as an audit trail of the send.
    This also lets you see at a glance if a day's digest was skipped.
    """
    try:
        creds = _get_credentials()
        service = build("calendar", "v3", credentials=creds)

        tz = pytz.timezone(settings.USER_TIMEZONE)
        now = datetime.now(tz)
        start = now.replace(hour=9, minute=0, second=0, microsecond=0)
        end = start + timedelta(minutes=5)

        event = {
            "summary": f"📬 FinTech Digest Sent ({story_count} stories)",
            "description": subject,
            "start": {"dateTime": start.isoformat(), "timeZone": settings.USER_TIMEZONE},
            "end": {"dateTime": end.isoformat(), "timeZone": settings.USER_TIMEZONE},
            "colorId": "2",  # Sage green
        }

        service.events().insert(calendarId="primary", body=event).execute()
        logger.info("Calendar event created")
        return True

    except Exception as e:
        logger.warning(f"Calendar event creation failed (non-critical): {e}")
        return False


def _html_to_plain(html: str) -> str:
    """Very basic HTML -> plain text for email fallback."""
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"  +", " ", text)
    return text.strip()