"""
Builds the HTML email. Designed to render cleanly in Gmail, Outlook, and Apple Mail.
Uses table-based layout for email client compatibility.

Phase 2 additions:
  - Feedback links (👍 / 👎) per story — one-click, no JS required
  - Watchlist badge shown on stories that matched a tracked entity
  - build_sentiment_alert_html() for sentiment velocity alert emails
  - build_weekly_synthesis_html() for Friday narrative synthesis emails
"""

from datetime import date, datetime, timezone
import pytz
from app.config import settings


def build_email_html(digest: dict, run_id: str = "", user_id: int = 1) -> str:
    today = date.today().strftime("%A, %d %B %Y")
    stories_html = ""

    for i, story in enumerate(digest["stories"], 1):
        source = story.get("source", "Unknown")
        pub_date = _format_date(story.get("published_date"))
        date_str = f" · {pub_date}" if pub_date else ""
        is_watchlist = story.get("watchlist_match", False)
        watchlist_entity = story.get("watchlist_entity", "")

        # Encode story URL for use in feedback link query param
        from urllib.parse import quote
        encoded_url = quote(story["url"], safe="")
        encoded_title = quote(story["title"][:120], safe="")
        encoded_source = quote(source, safe="")

        # Feedback links — GET requests so they work in any email client
        base = settings.APP_BASE_URL
        up_link = (
            f"{base}/feedback?signal=1"
            f"&url={encoded_url}&title={encoded_title}"
            f"&source={encoded_source}&run_id={run_id}&user_id={user_id}"
        )
        down_link = (
            f"{base}/feedback?signal=-1"
            f"&url={encoded_url}&title={encoded_title}"
            f"&source={encoded_source}&run_id={run_id}&user_id={user_id}"
        )

        watchlist_badge = ""
        if is_watchlist and watchlist_entity:
            watchlist_badge = f"""
              <span style="font-family:'Courier New',monospace;font-size:9px;
                font-weight:bold;letter-spacing:1px;text-transform:uppercase;
                background:#1a3a2e;color:#4ade80;padding:2px 6px;
                border-radius:3px;margin-right:6px;">
                ★ {watchlist_entity}
              </span>"""

        stories_html += f"""
        <tr>
          <td style="padding:0 0 28px 0;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding-bottom:6px;">
                  {watchlist_badge}
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
                  &nbsp;&nbsp;&nbsp;
                  <a href="{up_link}" style="font-family:'Courier New',monospace;
                    font-size:12px;color:#4ade80;text-decoration:none;" title="Useful story">
                    👍
                  </a>
                  &nbsp;
                  <a href="{down_link}" style="font-family:'Courier New',monospace;
                    font-size:12px;color:#f87171;text-decoration:none;" title="Not relevant">
                    👎
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

          <!-- Footer with feedback explanation -->
          <tr>
            <td style="background:#f0ebe0;padding:20px 40px;border-top:2px solid #1a1a2e;">
              <p style="font-family:'Courier New',monospace;font-size:10px;color:#9a9080;
                margin:0 0 6px;letter-spacing:1px;text-transform:uppercase;">
                FinTech Intelligence Agent · Automated Daily Briefing ·
                Excludes share prices, market commentary &amp; conference news
              </p>
              <p style="font-family:'Courier New',monospace;font-size:10px;color:#9a9080;margin:0;">
                👍 👎 clicks teach the agent your preferences — it gets smarter over time.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def build_sentiment_alert_html(
    entity: str,
    delta: float,
    recent_avg: float,
    baseline_avg: float,
    recent_stories: list[dict],
) -> str:
    """HTML email for sentiment velocity alerts."""
    direction = "deteriorated" if delta < 0 else "improved"
    arrow = "↓" if delta < 0 else "↑"
    colour = "#f87171" if delta < 0 else "#4ade80"
    today = date.today().strftime("%A, %d %B %Y")

    stories_html = ""
    for s in recent_stories[:5]:
        score = s.get("score", 0)
        score_colour = "#f87171" if score < -0.2 else "#4ade80" if score > 0.2 else "#94a3b8"
        stories_html += f"""
        <tr>
          <td style="padding:8px 0;border-bottom:1px solid #e8e2d9;">
            <span style="font-family:Georgia,serif;font-size:14px;color:#1a1a2e;">
              {s.get('title', '')}
            </span><br>
            <span style="font-family:'Courier New',monospace;font-size:10px;
              color:{score_colour};letter-spacing:1px;">
              SENTIMENT: {score:+.2f}
            </span>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Sentiment Alert: {entity}</title></head>
<body style="margin:0;padding:0;background:#f5f0e8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f0e8;">
    <tr><td align="center" style="padding:32px 16px;">
      <table width="600" cellpadding="0" cellspacing="0"
        style="max-width:600px;background:#fffef9;border:1px solid #e0d8cc;">

        <tr><td style="background:#1a1a2e;padding:24px 36px;">
          <p style="font-family:'Courier New',monospace;font-size:9px;letter-spacing:3px;
            color:#8a7355;text-transform:uppercase;margin:0 0 6px;">SENTIMENT SIGNAL</p>
          <p style="font-family:Georgia,serif;font-size:22px;font-weight:bold;
            color:#fffef9;margin:0;">
            {entity} <span style="color:{colour}">{arrow} {abs(delta):.0%}</span>
          </p>
        </td></tr>

        <tr><td style="background:#2d3561;padding:12px 36px;">
          <p style="font-family:Georgia,serif;font-size:12px;font-style:italic;
            color:#c8c0e0;margin:0;">
            News sentiment around {entity} has {direction} significantly in the last 48 hours
            versus the {settings.SENTIMENT_WINDOW_DAYS}-day baseline.
          </p>
        </td></tr>

        <tr><td style="padding:24px 36px;">
          <table width="100%" cellpadding="0" cellspacing="0"
            style="background:#f0ebe0;border-radius:4px;margin-bottom:20px;">
            <tr>
              <td style="padding:12px 16px;text-align:center;">
                <p style="font-family:'Courier New',monospace;font-size:10px;
                  color:#8a7355;letter-spacing:1px;margin:0 0 4px;">48H AVG</p>
                <p style="font-family:Georgia,serif;font-size:24px;font-weight:bold;
                  color:{colour};margin:0;">{recent_avg:+.2f}</p>
              </td>
              <td style="padding:12px 16px;text-align:center;">
                <p style="font-family:'Courier New',monospace;font-size:10px;
                  color:#8a7355;letter-spacing:1px;margin:0 0 4px;">
                  {settings.SENTIMENT_WINDOW_DAYS}D BASELINE</p>
                <p style="font-family:Georgia,serif;font-size:24px;font-weight:bold;
                  color:#2d2d2d;margin:0;">{baseline_avg:+.2f}</p>
              </td>
              <td style="padding:12px 16px;text-align:center;">
                <p style="font-family:'Courier New',monospace;font-size:10px;
                  color:#8a7355;letter-spacing:1px;margin:0 0 4px;">DELTA</p>
                <p style="font-family:Georgia,serif;font-size:24px;font-weight:bold;
                  color:{colour};margin:0;">{delta:+.2f}</p>
              </td>
            </tr>
          </table>

          <p style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;
            text-transform:uppercase;color:#8a7355;margin:0 0 12px;">
            CONTRIBUTING STORIES</p>
          <table width="100%" cellpadding="0" cellspacing="0">
            {stories_html}
          </table>
        </td></tr>

        <tr><td style="background:#f0ebe0;padding:16px 36px;border-top:2px solid #1a1a2e;">
          <p style="font-family:'Courier New',monospace;font-size:9px;color:#9a9080;margin:0;
            letter-spacing:1px;text-transform:uppercase;">
            FinTech Intelligence Agent · Sentiment Velocity Alert · {today}
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def build_weekly_synthesis_html(synthesis: dict) -> str:
    """
    HTML email for the Friday weekly narrative synthesis.
    synthesis dict: {
        "subject": str,
        "week_range": str,
        "themes": [{"title": str, "narrative": str, "story_count": int}, ...],
        "story_count_total": int
    }
    """
    today = date.today().strftime("%A, %d %B %Y")
    themes_html = ""

    for i, theme in enumerate(synthesis.get("themes", []), 1):
        themes_html += f"""
        <tr>
          <td style="padding:0 0 24px 0;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr><td style="padding-bottom:4px;">
                <span style="font-family:'Courier New',monospace;font-size:10px;
                  font-weight:bold;letter-spacing:2px;text-transform:uppercase;color:#8a7355;">
                  THEME {i:02d} · {theme.get('story_count', 0)} STORIES
                </span>
              </td></tr>
              <tr><td style="padding-bottom:8px;">
                <p style="font-family:Georgia,serif;font-size:17px;font-weight:bold;
                  color:#1a1a2e;margin:0;">
                  {theme['title']}
                </p>
              </td></tr>
              <tr><td>
                <p style="font-family:Georgia,serif;font-size:15px;color:#2d2d2d;
                  line-height:1.65;margin:0;">
                  {theme['narrative']}
                </p>
              </td></tr>
            </table>
            <hr style="border:none;border-top:1px solid #e8e2d9;margin:16px 0 0;">
          </td>
        </tr>"""

    total = synthesis.get("story_count_total", 0)
    week_range = synthesis.get("week_range", "")

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>{synthesis.get('subject', 'Weekly FinTech Synthesis')}</title></head>
<body style="margin:0;padding:0;background:#f5f0e8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f0e8;">
    <tr><td align="center" style="padding:32px 16px;">
      <table width="640" cellpadding="0" cellspacing="0"
        style="max-width:640px;background:#fffef9;border:1px solid #e0d8cc;">

        <tr><td style="background:#1a1a2e;padding:28px 40px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td>
              <p style="font-family:'Courier New',monospace;font-size:10px;
                letter-spacing:3px;color:#8a7355;text-transform:uppercase;margin:0 0 8px;">
                FINTECH INTELLIGENCE · WEEKLY SYNTHESIS
              </p>
              <p style="font-family:Georgia,serif;font-size:26px;font-weight:bold;
                color:#fffef9;margin:0;line-height:1.2;">Week in Review</p>
            </td>
            <td align="right" valign="middle">
              <p style="font-family:'Courier New',monospace;font-size:11px;
                color:#8a7355;margin:0;text-align:right;">
                {today}<br>
                <span style="font-size:10px;">{total} STORIES · {week_range}</span>
              </p>
            </td>
          </tr></table>
        </td></tr>

        <tr><td style="background:#2d3561;padding:14px 40px;">
          <p style="font-family:Georgia,serif;font-size:13px;font-style:italic;
            color:#c8c0e0;margin:0;">
            {synthesis.get('subject', '')}
          </p>
        </td></tr>

        <tr><td style="padding:32px 40px 8px 40px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            {themes_html}
          </table>
        </td></tr>

        <tr><td style="background:#f0ebe0;padding:20px 40px;border-top:2px solid #1a1a2e;">
          <p style="font-family:'Courier New',monospace;font-size:10px;color:#9a9080;
            margin:0;letter-spacing:1px;text-transform:uppercase;">
            FinTech Intelligence Agent · Weekly Narrative Synthesis · {today}
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _format_date(date_str: str | None) -> str:
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%-d %b")
    except Exception:
        return ""