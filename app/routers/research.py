"""
app/routers/research.py — Deep-dive research mode.

A user requests a research brief on a specific company or topic:
  POST /research  { "topic": "Klarna", "user_id": 1 }

The research agent:
  1. Runs RESEARCH_MAX_SEARCHES targeted Tavily searches
  2. Cross-references against story_memory (stories already seen)
  3. Sends ALL candidates to Groq for synthesis into a structured brief
  4. Generates a PDF using reportlab (bundled, no external service)
  5. Stores the brief in research_briefs table
  6. Emails the PDF + HTML version to the user
  7. Returns a download link

The PDF is stored on disk at /tmp/research/{brief_id}.pdf and served
via GET /research/{brief_id}/pdf

Brief structure:
  - Executive summary (3-4 sentences)
  - Key developments (chronological, 5-10 bullet points)
  - Strategic implications (2-3 paragraphs)
  - Source list

Endpoints:
  POST /research                   — trigger a research run (async)
  GET  /research                   — list past briefs for a user
  GET  /research/{brief_id}        — get brief detail (JSON)
  GET  /research/{brief_id}/pdf    — download the PDF
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from groq import Groq
from tavily import TavilyClient

from app.config import settings
from app.database import get_conn
from app.gmail import send_digest_email
from app.search import is_excluded, _extract_source

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/research", tags=["research"])
_groq = Groq(api_key=settings.GROQ_API_KEY)

PDF_DIR = "/tmp/research"
os.makedirs(PDF_DIR, exist_ok=True)


# ── Pydantic models ───────────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    topic: str
    user_id: int = 1
    send_email: bool = True


class ResearchBriefSummary(BaseModel):
    brief_id: str
    topic: str
    status: str
    created_at: str
    story_count: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("")
async def request_research(body: ResearchRequest, background_tasks: BackgroundTasks):
    """Kick off a research brief — runs in background, returns brief_id immediately."""
    brief_id = str(uuid.uuid4())[:8]
    topic = body.topic.strip()

    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty")

    # Create a pending record immediately so the user has a brief_id to poll
    await _upsert_brief(brief_id, topic, body.user_id, "pending", 0, None)

    background_tasks.add_task(
        run_research_brief,
        brief_id=brief_id,
        topic=topic,
        user_id=body.user_id,
        send_email=body.send_email,
    )

    return {
        "brief_id": brief_id,
        "topic": topic,
        "status": "pending",
        "message": f"Research started. Poll GET /research/{brief_id} for status. "
                   "Brief is typically ready in 30-60 seconds.",
        "pdf_url": f"{settings.APP_BASE_URL}/research/{brief_id}/pdf",
    }


@router.get("")
async def list_briefs(user_id: int = 1, limit: int = 20):
    """List past research briefs for a user."""
    async with get_conn() as conn:
        rows = await (await conn.execute(
            """
            SELECT brief_id, topic, status, created_at, story_count
            FROM research_briefs
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )).fetchall()

    return {
        "briefs": [
            {
                "brief_id": r[0],
                "topic": r[1],
                "status": r[2],
                "created_at": r[3].isoformat() if isinstance(r[3], datetime) else r[3],
                "story_count": r[4],
                "pdf_url": f"{settings.APP_BASE_URL}/research/{r[0]}/pdf",
            }
            for r in rows
        ]
    }


@router.get("/{brief_id}")
async def get_brief(brief_id: str):
    """Get the full JSON content of a research brief."""
    async with get_conn() as conn:
        row = await (await conn.execute(
            "SELECT brief_id, topic, status, brief_json, story_count, created_at "
            "FROM research_briefs WHERE brief_id = %s",
            (brief_id,),
        )).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Brief {brief_id} not found")

    brief_json = json.loads(row[3]) if row[3] else {}
    return {
        "brief_id": row[0],
        "topic": row[1],
        "status": row[2],
        "story_count": row[4],
        "created_at": row[5].isoformat() if isinstance(row[5], datetime) else row[5],
        "brief": brief_json,
        "pdf_url": f"{settings.APP_BASE_URL}/research/{brief_id}/pdf",
    }


@router.get("/{brief_id}/pdf")
async def download_pdf(brief_id: str):
    """Stream the PDF file for a research brief."""
    pdf_path = os.path.join(PDF_DIR, f"{brief_id}.pdf")
    if not os.path.exists(pdf_path):
        # Check if brief exists but PDF isn't generated yet
        async with get_conn() as conn:
            row = await (await conn.execute(
                "SELECT status FROM research_briefs WHERE brief_id = %s",
                (brief_id,),
            )).fetchone()
        if row and row[0] == "pending":
            raise HTTPException(status_code=202, detail="Brief is still being generated. Try again shortly.")
        raise HTTPException(status_code=404, detail="PDF not found")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"fintech-research-{brief_id}.pdf",
    )


# ── Core research pipeline ────────────────────────────────────────────────────

async def run_research_brief(brief_id: str, topic: str, user_id: int, send_email: bool):
    """
    Full research pipeline. Runs as a background task.
    Stages: search → deduplicate → synthesise → PDF → email
    """
    logger.info(f"[research] Starting brief {brief_id}: '{topic}'")
    started = datetime.now(timezone.utc)

    try:
        # Stage 1: Multi-query Tavily search
        stories = await _research_search(topic)
        logger.info(f"[research] {len(stories)} stories fetched for '{topic}'")

        if not stories:
            await _upsert_brief(brief_id, topic, user_id, "failed: no stories found", 0, None)
            return

        # Stage 2: Synthesise with Groq
        brief = await _synthesise_brief(topic, stories)
        brief["brief_id"] = brief_id
        brief["topic"] = topic
        brief["generated_at"] = started.isoformat()

        # Stage 3: Generate PDF
        pdf_path = await _generate_pdf(brief_id, brief)

        # Stage 4: Persist
        await _upsert_brief(brief_id, topic, user_id, "complete", len(stories), brief)
        logger.info(f"[research] Brief {brief_id} complete — {len(stories)} stories")

        # Stage 5: Email (optional)
        if send_email:
            html = _build_brief_html(brief)
            subject = f"📑 Research Brief: {topic}"
            send_digest_email(subject, html)
            logger.info(f"[research] Brief emailed: {topic}")

    except Exception as e:
        logger.exception(f"[research] Brief {brief_id} failed: {e}")
        await _upsert_brief(brief_id, topic, user_id, f"failed: {str(e)[:80]}", 0, None)


async def _research_search(topic: str) -> list[dict]:
    """
    Run multiple targeted Tavily searches for the topic.
    Uses varied query formulations to maximise recall.
    """
    queries = [
        f"{topic} fintech news",
        f"{topic} banking regulation",
        f"{topic} financial technology announcement",
        f"{topic} partnership acquisition",
        f"{topic} product launch",
    ]
    # Add time-scoped queries for recent news
    from datetime import date
    year = date.today().year
    queries.append(f"{topic} {year}")

    client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    seen_urls: set[str] = set()
    stories: list[dict] = []

    for query in queries[:settings.RESEARCH_MAX_SEARCHES]:
        try:
            response = client.search(
                query=query,
                search_depth="advanced",
                topic="news",
                days=30,          # Wider window for research (30 days vs 1 day for digest)
                max_results=5,
            )
            for r in response.get("results", []):
                url = r.get("url", "")
                title = r.get("title", "").strip()
                snippet = r.get("content", "").strip()

                if url in seen_urls or not title:
                    continue
                if is_excluded(title, snippet):
                    continue

                seen_urls.add(url)
                stories.append({
                    "title": title,
                    "url": url,
                    "source": _extract_source(url),
                    "snippet": snippet[:500],
                    "published_date": r.get("published_date", ""),
                })
        except Exception as e:
            logger.warning(f"[research] Search failed for '{query}': {e}")

    return stories[:settings.RESEARCH_MAX_STORIES]


async def _synthesise_brief(topic: str, stories: list[dict]) -> dict:
    """Ask Groq to synthesise stories into a structured research brief."""
    stories_text = "\n\n".join(
        f"[{i+1}] {s['title']}\nSource: {s['source']}\nDate: {s.get('published_date','')[:10]}\n{s['snippet'][:300]}"
        for i, s in enumerate(stories)
    )

    prompt = f"""You are a senior analyst at a financial intelligence firm.
Produce a structured research brief on: *{topic}*

Source material ({len(stories)} articles):
{stories_text}

Write the brief in this exact JSON structure (no markdown):
{{
  "executive_summary": "3-4 sentences covering the most important recent development and its significance",
  "key_developments": [
    {{"date": "DD Mon YYYY or 'Recent'", "headline": "short headline", "detail": "1-2 sentence detail"}},
    ...
  ],
  "strategic_implications": [
    {{"theme": "theme title", "analysis": "2-3 sentence analytical paragraph"}},
    ...
  ],
  "sentiment": "positive|negative|neutral|mixed",
  "sentiment_rationale": "one sentence explaining the sentiment",
  "outlook": "1-2 sentences forward-looking conclusion"
}}

Requirements:
- key_developments: 5-10 items, most recent first
- strategic_implications: 2-4 themes
- Be specific and factual — cite specific numbers, dates, entities from the sources
- Write like an FT or Bloomberg intelligence report, not a press release summary"""

    try:
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a senior financial intelligence analyst. Be precise, analytical, and cite specific facts.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2000,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1].lstrip("json").strip()
        brief = json.loads(content)
        brief["sources"] = [
            {"title": s["title"], "source": s["source"], "url": s["url"]}
            for s in stories
        ]
        return brief
    except Exception as e:
        logger.error(f"[research] Synthesis failed: {e}")
        # Minimal fallback brief
        return {
            "executive_summary": f"Research brief on {topic} based on {len(stories)} recent articles.",
            "key_developments": [
                {"date": "Recent", "headline": s["title"], "detail": s["snippet"][:150]}
                for s in stories[:8]
            ],
            "strategic_implications": [],
            "sentiment": "neutral",
            "sentiment_rationale": "Insufficient data for sentiment analysis.",
            "outlook": "See source articles for full context.",
            "sources": [{"title": s["title"], "source": s["source"], "url": s["url"]} for s in stories],
        }


async def _generate_pdf(brief_id: str, brief: dict) -> str:
    """Generate a PDF from the brief using reportlab. Returns the PDF path."""
    pdf_path = os.path.join(PDF_DIR, f"{brief_id}.pdf")
    topic = brief.get("topic", "Research Brief")

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.colors import HexColor, black, white
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer,
            HRFlowable, Table, TableStyle,
        )
        from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
        from datetime import date

        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            leftMargin=2.5 * cm,
            rightMargin=2.5 * cm,
            topMargin=2.5 * cm,
            bottomMargin=2.5 * cm,
        )

        DARK = HexColor("#1a1a2e")
        GOLD = HexColor("#8a7355")
        LIGHT_BG = HexColor("#f5f0e8")
        MID = HexColor("#2d2d2d")

        styles = getSampleStyleSheet()

        def style(name, **kwargs):
            return ParagraphStyle(name, **kwargs)

        header_style = style("Header", fontSize=20, textColor=white,
                             fontName="Helvetica-Bold", leading=24)
        label_style = style("Label", fontSize=8, textColor=GOLD,
                            fontName="Helvetica-Bold", spaceAfter=4,
                            leading=10, wordWrap="CJK")
        title_style = style("Title2", fontSize=14, textColor=DARK,
                            fontName="Helvetica-Bold", spaceAfter=6, leading=18)
        body_style = style("Body2", fontSize=10, textColor=MID,
                           fontName="Helvetica", leading=15, alignment=TA_JUSTIFY)
        dev_title_style = style("DevTitle", fontSize=10, textColor=DARK,
                                fontName="Helvetica-Bold", leading=13)
        dev_body_style = style("DevBody", fontSize=9, textColor=MID,
                               fontName="Helvetica", leading=13)
        source_style = style("Source", fontSize=8, textColor=GOLD,
                             fontName="Helvetica", leading=11)

        story_elements = []

        # ── Cover block ───────────────────────────────────────────────────
        cover_data = [[
            Paragraph("FINTECH INTELLIGENCE", label_style),
        ]]
        cover_table = Table(cover_data, colWidths=[16 * cm])
        cover_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), DARK),
            ("TOPPADDING", (0, 0), (-1, -1), 20),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ]))
        story_elements.append(cover_table)

        title_data = [[Paragraph(f"Research Brief: {topic}", header_style)]]
        title_table = Table(title_data, colWidths=[16 * cm])
        title_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), DARK),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 20),
            ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ]))
        story_elements.append(title_table)

        meta_data = [[
            Paragraph(
                f"Generated: {date.today().strftime('%-d %B %Y')} · "
                f"{len(brief.get('sources', []))} sources · "
                f"Sentiment: {brief.get('sentiment', 'N/A').upper()}",
                style("Meta", fontSize=9, textColor=GOLD, fontName="Helvetica",
                      leading=12, backColor=HexColor("#2d3561")),
            )
        ]]
        meta_table = Table(meta_data, colWidths=[16 * cm])
        meta_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#2d3561")),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ]))
        story_elements.append(meta_table)
        story_elements.append(Spacer(1, 0.6 * cm))

        # ── Executive summary ─────────────────────────────────────────────
        story_elements.append(Paragraph("EXECUTIVE SUMMARY", label_style))
        story_elements.append(HRFlowable(width="100%", thickness=1, color=GOLD))
        story_elements.append(Spacer(1, 0.2 * cm))
        story_elements.append(Paragraph(brief.get("executive_summary", ""), body_style))
        story_elements.append(Spacer(1, 0.5 * cm))

        # ── Key developments ──────────────────────────────────────────────
        story_elements.append(Paragraph("KEY DEVELOPMENTS", label_style))
        story_elements.append(HRFlowable(width="100%", thickness=1, color=GOLD))
        story_elements.append(Spacer(1, 0.2 * cm))

        for dev in brief.get("key_developments", []):
            date_str = dev.get("date", "Recent")
            headline = dev.get("headline", "")
            detail = dev.get("detail", "")
            story_elements.append(
                Paragraph(f"<font color='#8a7355'>{date_str}</font> — {headline}",
                          dev_title_style)
            )
            if detail:
                story_elements.append(Paragraph(detail, dev_body_style))
            story_elements.append(Spacer(1, 0.25 * cm))

        story_elements.append(Spacer(1, 0.3 * cm))

        # ── Strategic implications ────────────────────────────────────────
        implications = brief.get("strategic_implications", [])
        if implications:
            story_elements.append(Paragraph("STRATEGIC IMPLICATIONS", label_style))
            story_elements.append(HRFlowable(width="100%", thickness=1, color=GOLD))
            story_elements.append(Spacer(1, 0.2 * cm))
            for impl in implications:
                story_elements.append(Paragraph(impl.get("theme", ""), title_style))
                story_elements.append(Paragraph(impl.get("analysis", ""), body_style))
                story_elements.append(Spacer(1, 0.3 * cm))

        # ── Outlook ───────────────────────────────────────────────────────
        outlook = brief.get("outlook", "")
        if outlook:
            story_elements.append(Paragraph("OUTLOOK", label_style))
            story_elements.append(HRFlowable(width="100%", thickness=1, color=GOLD))
            story_elements.append(Spacer(1, 0.2 * cm))
            story_elements.append(Paragraph(outlook, body_style))
            story_elements.append(Spacer(1, 0.5 * cm))

        # ── Sources ───────────────────────────────────────────────────────
        sources = brief.get("sources", [])
        if sources:
            story_elements.append(Paragraph("SOURCES", label_style))
            story_elements.append(HRFlowable(width="100%", thickness=1, color=GOLD))
            story_elements.append(Spacer(1, 0.2 * cm))
            for i, src in enumerate(sources[:20], 1):
                story_elements.append(
                    Paragraph(
                        f"{i}. {src['title']} — <font color='#8a7355'>{src['source']}</font>",
                        source_style,
                    )
                )

        doc.build(story_elements)
        logger.info(f"[research] PDF generated: {pdf_path}")
        return pdf_path

    except ImportError:
        logger.warning("[research] reportlab not installed — skipping PDF generation")
        return ""
    except Exception as e:
        logger.error(f"[research] PDF generation failed: {e}")
        return ""


def _build_brief_html(brief: dict) -> str:
    """Build an HTML email version of the research brief."""
    from datetime import date
    today = date.today().strftime("%A, %d %B %Y")
    topic = brief.get("topic", "Research Brief")
    brief_id = brief.get("brief_id", "")

    developments_html = ""
    for dev in brief.get("key_developments", [])[:8]:
        developments_html += f"""
        <tr><td style="padding:8px 0;border-bottom:1px solid #e8e2d9;">
          <p style="font-family:'Courier New',monospace;font-size:10px;
            color:#8a7355;margin:0 0 3px;">{dev.get('date','Recent').upper()}</p>
          <p style="font-family:Georgia,serif;font-size:14px;font-weight:bold;
            color:#1a1a2e;margin:0 0 3px;">{dev.get('headline','')}</p>
          <p style="font-family:Georgia,serif;font-size:13px;color:#2d2d2d;
            margin:0;line-height:1.5;">{dev.get('detail','')}</p>
        </td></tr>"""

    implications_html = ""
    for impl in brief.get("strategic_implications", []):
        implications_html += f"""
        <p style="font-family:Georgia,serif;font-size:15px;font-weight:bold;
          color:#1a1a2e;margin:0 0 6px;">{impl.get('theme','')}</p>
        <p style="font-family:Georgia,serif;font-size:14px;color:#2d2d2d;
          line-height:1.65;margin:0 0 16px;">{impl.get('analysis','')}</p>"""

    sentiment = brief.get("sentiment", "neutral")
    sent_colour = {"positive": "#4ade80", "negative": "#f87171",
                   "mixed": "#fbbf24", "neutral": "#94a3b8"}.get(sentiment, "#94a3b8")

    pdf_link = f"{settings.APP_BASE_URL}/research/{brief_id}/pdf"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Research Brief: {topic}</title></head>
<body style="margin:0;padding:0;background:#f5f0e8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f0e8;">
    <tr><td align="center" style="padding:32px 16px;">
      <table width="660" cellpadding="0" cellspacing="0"
        style="max-width:660px;background:#fffef9;border:1px solid #e0d8cc;">

        <tr><td style="background:#1a1a2e;padding:28px 40px;">
          <p style="font-family:'Courier New',monospace;font-size:9px;letter-spacing:3px;
            color:#8a7355;text-transform:uppercase;margin:0 0 6px;">
            FINTECH INTELLIGENCE · RESEARCH BRIEF</p>
          <p style="font-family:Georgia,serif;font-size:24px;font-weight:bold;
            color:#fffef9;margin:0;">{topic}</p>
        </td></tr>

        <tr><td style="background:#2d3561;padding:12px 40px;">
          <p style="font-family:'Courier New',monospace;font-size:11px;color:#c8c0e0;margin:0;">
            {today} &nbsp;·&nbsp;
            {len(brief.get('sources',[]))} sources &nbsp;·&nbsp;
            Sentiment: <span style="color:{sent_colour};font-weight:bold;">
              {sentiment.upper()}</span> &nbsp;·&nbsp;
            <a href="{pdf_link}" style="color:#60a5fa;">Download PDF →</a>
          </p>
        </td></tr>

        <tr><td style="padding:28px 40px;">
          <p style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;
            text-transform:uppercase;color:#8a7355;margin:0 0 8px;">EXECUTIVE SUMMARY</p>
          <p style="font-family:Georgia,serif;font-size:15px;color:#2d2d2d;
            line-height:1.65;margin:0 0 24px;padding:16px;background:#f0ebe0;
            border-left:3px solid #8a7355;">
            {brief.get('executive_summary','')}</p>

          <p style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;
            text-transform:uppercase;color:#8a7355;margin:0 0 8px;">KEY DEVELOPMENTS</p>
          <table width="100%" cellpadding="0" cellspacing="0">
            {developments_html}
          </table>

          <div style="margin-top:24px;">
            <p style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;
              text-transform:uppercase;color:#8a7355;margin:0 0 12px;">
              STRATEGIC IMPLICATIONS</p>
            {implications_html}
          </div>

          <div style="margin-top:16px;padding:16px;background:#f0ebe0;">
            <p style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;
              text-transform:uppercase;color:#8a7355;margin:0 0 6px;">OUTLOOK</p>
            <p style="font-family:Georgia,serif;font-size:14px;color:#2d2d2d;
              line-height:1.65;margin:0;">{brief.get('outlook','')}</p>
          </div>
        </td></tr>

        <tr><td style="background:#f0ebe0;padding:16px 40px;border-top:2px solid #1a1a2e;">
          <p style="font-family:'Courier New',monospace;font-size:9px;color:#9a9080;
            margin:0;letter-spacing:1px;text-transform:uppercase;">
            FinTech Intelligence Agent · Research Brief · {today} &nbsp;·&nbsp;
            <a href="{pdf_link}" style="color:#8a7355;">PDF version</a>
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _upsert_brief(
    brief_id: str,
    topic: str,
    user_id: int,
    status: str,
    story_count: int,
    brief: Optional[dict],
):
    brief_json = json.dumps(brief) if brief else None
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO research_briefs
                (brief_id, topic, user_id, status, story_count, brief_json)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (brief_id) DO UPDATE SET
                status      = EXCLUDED.status,
                story_count = EXCLUDED.story_count,
                brief_json  = EXCLUDED.brief_json
            """,
            (brief_id, topic, user_id, status, story_count, brief_json),
        )
        await conn.commit()