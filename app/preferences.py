"""
preferences.py — Feedback-driven preference learning.

How it works end-to-end:
  1. Each story in the email has a one-click feedback link:
       GET /feedback/{story_id}?signal=1   (thumbs up)
       GET /feedback/{story_id}?signal=-1  (thumbs down)

  2. On each click, record_feedback() stores the signal in story_feedback.
     Then rebuild_preference_profile() is called asynchronously — it reads
     the last FEEDBACK_WINDOW signals, calls Groq to summarise the user's
     revealed interests into a structured JSON profile, and saves it to
     user_preferences.

  3. Before each digest run, curator_agent loads the profile and injects
     it into the LLM curation prompt as an additional instruction block.
     This means the agent literally gets smarter with every click.

  4. After MIN_FEEDBACK_FOR_PROFILE signals are collected (default: 5),
     the profile is considered "warm" and begins influencing curation.
     Before that threshold, curation uses the default criteria only.

Profile JSON structure:
  {
    "liked_topics":     ["regulation", "CBDC", "open banking"],
    "disliked_topics":  ["startup funding", "product launches"],
    "liked_sources":    ["Financial Times", "Reuters"],
    "disliked_sources": [],
    "liked_entities":   ["HSBC", "RBI", "Stripe"],
    "profile_summary":  "Plain English summary for LLM injection"
  }
"""

import json
import logging
from collections import Counter

from groq import Groq
from app.config import settings
from app.database import (
    fetch_recent_feedback,
    upsert_preference_profile,
    fetch_preference_profile,
)

logger = logging.getLogger(__name__)
_groq = Groq(api_key=settings.GROQ_API_KEY)


async def rebuild_preference_profile(user_id: int) -> dict | None:
    """
    Re-compute the preference profile from the user's recent feedback signals.
    Called asynchronously after every feedback click — fast enough to not
    block the response.

    Returns the new profile dict, or None if not enough data yet.
    """
    feedback = await fetch_recent_feedback(user_id, limit=settings.FEEDBACK_WINDOW)
    if len(feedback) < settings.MIN_FEEDBACK_FOR_PROFILE:
        logger.info(
            f"[preferences] User {user_id}: only {len(feedback)} signals "
            f"(need {settings.MIN_FEEDBACK_FOR_PROFILE}) — profile not yet active"
        )
        return None

    liked = [f for f in feedback if f["signal"] == 1]
    disliked = [f for f in feedback if f["signal"] == -1]

    # Fast heuristic pass — extract sources and topics without LLM
    liked_sources = _top_values([f["source"] for f in liked if f.get("source")], n=5)
    disliked_sources = _top_values([f["source"] for f in disliked if f.get("source")], n=3)

    # Extract liked/disliked topic keywords from titles using LLM
    liked_titles = [f["title"] for f in liked[:20]]
    disliked_titles = [f["title"] for f in disliked[:10]]

    try:
        profile = await _llm_build_profile(liked_titles, disliked_titles, liked_sources, disliked_sources)
    except Exception as e:
        logger.error(f"[preferences] LLM profile build failed: {e} — using heuristic fallback")
        profile = _heuristic_profile(liked, disliked, liked_sources, disliked_sources)

    await upsert_preference_profile(user_id, profile, len(feedback))
    logger.info(
        f"[preferences] Profile rebuilt for user {user_id}: "
        f"{len(liked)} liked, {len(disliked)} disliked"
    )
    return profile


async def _llm_build_profile(
    liked_titles: list[str],
    disliked_titles: list[str],
    liked_sources: list[str],
    disliked_sources: list[str],
) -> dict:
    """Ask Groq to distil the feedback signals into a structured preference profile."""

    liked_str = "\n".join(f"  - {t}" for t in liked_titles) if liked_titles else "  (none yet)"
    disliked_str = "\n".join(f"  - {t}" for t in disliked_titles) if disliked_titles else "  (none yet)"

    prompt = f"""A user has rated fintech news stories. Analyse their ratings to build a preference profile.

STORIES THEY LIKED (thumbs up):
{liked_str}

STORIES THEY DISLIKED (thumbs down):
{disliked_str}

SOURCES THEY TEND TO LIKE: {', '.join(liked_sources) or 'none identified yet'}
SOURCES THEY TEND TO DISLIKE: {', '.join(disliked_sources) or 'none'}

Based on these signals, extract:
1. The fintech topics/themes they prefer (e.g. "regulation", "central banking", "fraud", "open banking")
2. The topics they want less of
3. Any specific companies or entities that appear frequently in their liked stories
4. A 2-3 sentence plain English profile summary that can be injected into a news curation prompt

Respond ONLY with valid JSON (no markdown):
{{
  "liked_topics": ["topic1", "topic2"],
  "disliked_topics": ["topic1"],
  "liked_sources": {json.dumps(liked_sources)},
  "disliked_sources": {json.dumps(disliked_sources)},
  "liked_entities": ["entity1"],
  "profile_summary": "This user prefers..."
}}"""

    response = _groq.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=600,
    )
    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1].lstrip("json").strip()
    return json.loads(content)


def _heuristic_profile(
    liked: list[dict],
    disliked: list[dict],
    liked_sources: list[str],
    disliked_sources: list[str],
) -> dict:
    """Simple keyword extraction fallback when LLM fails."""
    TOPIC_KEYWORDS = [
        "regulation", "compliance", "fraud", "CBDC", "open banking", "API",
        "neobank", "payment", "crypto", "blockchain", "acquisition", "merger",
        "funding", "IPO", "AI", "machine learning", "cybersecurity", "lending",
    ]

    def extract_topics(stories, signal_label):
        counts = Counter()
        for s in stories:
            title_lower = s["title"].lower()
            for kw in TOPIC_KEYWORDS:
                if kw.lower() in title_lower:
                    counts[kw] += 1
        return [kw for kw, _ in counts.most_common(5)]

    liked_topics = extract_topics(liked, "liked")
    disliked_topics = extract_topics(disliked, "disliked")

    return {
        "liked_topics": liked_topics,
        "disliked_topics": [t for t in disliked_topics if t not in liked_topics],
        "liked_sources": liked_sources,
        "disliked_sources": disliked_sources,
        "liked_entities": [],
        "profile_summary": (
            f"User prefers stories about: {', '.join(liked_topics) or 'general fintech'}. "
            f"Prefers sources: {', '.join(liked_sources) or 'any'}."
        ),
    }


def _top_values(items: list[str], n: int) -> list[str]:
    """Return the top-N most frequent values from a list."""
    return [v for v, _ in Counter(items).most_common(n)]


def build_preference_prompt_block(profile: dict | None) -> str:
    """
    Returns a prompt instruction block that can be injected into the
    curator LLM prompt. Returns empty string if no profile yet.
    """
    if not profile:
        return ""

    summary = profile.get("profile_summary", "")
    liked_topics = profile.get("liked_topics", [])
    disliked_topics = profile.get("disliked_topics", [])
    liked_sources = profile.get("liked_sources", [])
    disliked_sources = profile.get("disliked_sources", [])
    liked_entities = profile.get("liked_entities", [])

    lines = ["\nPERSONALISATION (apply this in your story selection):"]
    lines.append(f"  User profile: {summary}")
    if liked_topics:
        lines.append(f"  Prioritise stories about: {', '.join(liked_topics)}")
    if disliked_topics:
        lines.append(f"  Deprioritise stories about: {', '.join(disliked_topics)}")
    if liked_sources:
        lines.append(f"  Favour sources: {', '.join(liked_sources)}")
    if disliked_sources:
        lines.append(f"  Avoid sources: {', '.join(disliked_sources)}")
    if liked_entities:
        lines.append(f"  Always include stories mentioning: {', '.join(liked_entities)}")

    return "\n".join(lines)