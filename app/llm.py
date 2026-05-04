"""
LLM layer using Groq.
Responsibilities:
  1. Score and rank stories by executive relevance
  2. Write a tight, professional synopsis per story
  3. Generate the email subject line
"""

import json
import logging
from groq import Groq
from app.config import settings

logger = logging.getLogger(__name__)
client = Groq(api_key=settings.GROQ_API_KEY)

SYSTEM_PROMPT = """You are a senior financial analyst writing a morning briefing for a C-suite executive.
Your job is to select the most strategically important fintech stories from the past 24 hours and summarise each one concisely.

SELECTION CRITERIA (include):
- Regulatory changes affecting banks or asset managers
- Product launches or technology pivots by major financial institutions
- Significant partnerships, M&A activity, or market entries
- Fraud, cybersecurity, or operational incidents at financial firms
- Central bank digital currency (CBDC) or monetary policy developments
- Fintech startup funding rounds of $50M+ or notable failures

EXCLUSION CRITERIA (never include):
- Share price movements or stock market commentary
- Conference announcements or industry event coverage
- General macroeconomic commentary not tied to a specific institution
- Analyst price target changes

TONE: Authoritative, direct, no fluff. Write like the FT, not TechCrunch.
Each synopsis must be 2-3 sentences. Start with the most important fact."""


def process_stories(raw_stories: list[dict]) -> dict:
    """
    Send raw stories to Groq. Returns:
    {
        "subject": "...",
        "stories": [{"title", "synopsis", "source", "url", "published_date"}, ...]
    }
    """
    if not raw_stories:
        return {"subject": "FinTech Digest — No significant stories today", "stories": []}

    stories_text = json.dumps(
        [{"title": s["title"], "snippet": s["snippet"], "source": s["source"], "url": s["url"]}
         for s in raw_stories],
        indent=2
    )

    prompt = f"""Below are {len(raw_stories)} raw fintech news items from the past 24 hours.

{stories_text}

Task:
1. Select the {settings.MAX_STORIES} most strategically important stories using the selection criteria.
2. For each selected story, write a 2-3 sentence executive synopsis. Do NOT start with the publication name.
3. Generate a sharp, specific email subject line (max 12 words) that captures today's most important theme.

Respond ONLY with valid JSON in this exact format (no markdown, no preamble):
{{
  "subject": "...",
  "stories": [
    {{
      "title": "original title",
      "synopsis": "2-3 sentence synopsis",
      "source": "publication name",
      "url": "https://..."
    }}
  ]
}}"""

    try:
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,  # Low temp = consistent, factual tone
            max_tokens=2000,
        )
        content = response.choices[0].message.content.strip()

        # Strip markdown fences if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        result = json.loads(content)
        logger.info(f"LLM selected {len(result.get('stories', []))} stories")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error from LLM: {e}\nRaw: {content[:500]}")
        # Graceful fallback: use raw stories with snippets as synopses
        return _fallback_format(raw_stories)
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        return _fallback_format(raw_stories)


def _fallback_format(raw_stories: list[dict]) -> dict:
    """Fallback if LLM fails — still send the email, just without AI synopses."""
    return {
        "subject": "FinTech Intelligence Digest — " + _today_str(),
        "stories": [
            {
                "title": s["title"],
                "synopsis": s["snippet"],
                "source": s["source"],
                "url": s["url"],
            }
            for s in raw_stories[:settings.MAX_STORIES]
        ],
    }


def _today_str() -> str:
    from datetime import date
    return date.today().strftime("%d %b %Y")