"""
Builds the HTML email. Designed to render cleanly in Gmail, Outlook, and Apple Mail.
Uses table-based layout for email client compatibility.
"""

from datetime import date, datetime, timezone
import pytz
from app.config import settings


def build_email_html(digest: dict) -> str:
    today = date.today().strftime("%A, %d %B %Y")
    stories_html = ""

    for i, story in enumerate(digest["stories"], 1):
        source = story.get("source", "Unknown")
        pub_date = _format_date(story.get("published_date"))
        date_str = f" · {pub_date}" if pub_date else ""

        stories_html += f"""
        <tr>
          <td style="padding:0 0 28px 0;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding-bottom:6px;">
                  <span style="font-family:Georgia,serif;font-size:11px;font-weight:bold;
                    letter-spacing:2px;text-transform:uppercase;color:#8a7355;">
                    {i:02d}
                  </span>
                </td>
              </tr>
              <tr>
                <td style="padding-bottom:8px;">
                  <a href="{story['url']}" style="font-family:Georgia,serif;font-size:18px;
                    font-weight:bold;color:#1a1a2e;text-decoration:none;line-height:1.3;">
                    {story['title']}
                  </a>
                </td>
              </tr>
              <tr>
                <td style="padding-bottom:10px;">
                  <p style="font-family:Georgia,serif;font-size:15px;color:#2d2d2d;
                    line-height:1.65;margin:0;">
                    {story['synopsis']}
                  </p>
                </td>
              </tr>
              <tr>
                <td>
                  <span style="font-family:'Courier New',monospace;font-size:11px;
                    color:#8a7355;letter-spacing:1px;">
                    {source.upper()}{date_str}
                  </span>
                  &nbsp;&nbsp;
                  <a href="{story['url']}" style="font-family:'Courier New',monospace;
                    font-size:11px;color:#1a56db;letter-spacing:0.5px;">
                    READ →
                  </a>
                </td>
              </tr>
            </table>
            <hr style="border:none;border-top:1px solid #e8e2d9;margin:0;padding-top:28px;">
          </td>
        </tr>"""

    story_count = len(digest["stories"])
    tz = pytz.timezone(settings.USER_TIMEZONE)
    sent_time = datetime.now(tz).strftime("%H:%M %Z")

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{digest['subject']}</title>
</head>
<body style="margin:0;padding:0;background-color:#f5f0e8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f0e8;">
    <tr>
      <td align="center" style="padding:32px 16px;">

        <!-- Container -->
        <table width="640" cellpadding="0" cellspacing="0"
          style="max-width:640px;background:#fffef9;border:1px solid #e0d8cc;">

          <!-- Header -->
          <tr>
            <td style="background:#1a1a2e;padding:28px 40px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td>
                    <p style="font-family:'Courier New',monospace;font-size:10px;
                      letter-spacing:3px;color:#8a7355;text-transform:uppercase;margin:0 0 8px 0;">
                      FINTECH INTELLIGENCE
                    </p>
                    <p style="font-family:Georgia,serif;font-size:26px;font-weight:bold;
                      color:#fffef9;margin:0;line-height:1.2;">
                      Morning Briefing
                    </p>
                  </td>
                  <td align="right" valign="middle">
                    <p style="font-family:'Courier New',monospace;font-size:11px;
                      color:#8a7355;margin:0;text-align:right;">
                      {today}<br>
                      <span style="font-size:10px;">{story_count} STORIES · {sent_time}</span>
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Subject line as lede -->
          <tr>
            <td style="background:#2d3561;padding:14px 40px;">
              <p style="font-family:Georgia,serif;font-size:13px;font-style:italic;
                color:#c8c0e0;margin:0;letter-spacing:0.3px;">
                {digest['subject']}
              </p>
            </td>
          </tr>

          <!-- Stories -->
          <tr>
            <td style="padding:32px 40px 8px 40px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                {stories_html}
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#f0ebe0;padding:20px 40px;border-top:2px solid #1a1a2e;">
              <p style="font-family:'Courier New',monospace;font-size:10px;color:#9a9080;
                margin:0;letter-spacing:1px;text-transform:uppercase;">
                FinTech Intelligence Agent · Automated Daily Briefing ·
                Excludes share prices, market commentary &amp; conference news
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _format_date(date_str: str | None) -> str:
    if not date_str:
        return ""
    try:
        # Tavily returns ISO format or various date strings
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%-d %b")
    except Exception:
        return ""