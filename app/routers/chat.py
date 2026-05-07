"""
app/routers/chat.py — Conversational Q&A over the story archive.

A user can ask natural language questions about recent fintech news:
  "What happened with Revolut this week?"
  "Any stories about open banking regulation?"
  "Summarise HSBC news from the last 7 days"

Architecture (ReAct-style, single LLM call):
  1. Embed the user query with all-MiniLM-L6-v2
  2. Search story_memory via pgvector cosine similarity
  3. Retrieve top-K matching stories (title + source + url)
  4. Send query + retrieved stories to Groq for answer synthesis
  5. Return answer with inline citations (source + url)

The pgvector index makes step 2 fast even with thousands of stored stories.
No extra vector DB needed — we reuse the same story_memory table from Phase 1.

Endpoints:
  POST /chat           — { "query": "...", "user_id": 1 }
  GET  /chat/history   — last N Q&A exchanges for a user
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from groq import Groq

from app.config import settings
from app.database import get_conn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])
_groq = Groq(api_key=settings.GROQ_API_KEY)


class ChatRequest(BaseModel):
    query: str
    user_id: int = 1
    lookback_days: int = 14   # How far back to search the story archive


class ChatResponse(BaseModel):
    query: str
    answer: str
    sources: list[dict]
    stories_searched: int


async def answer_question(query: str, user_id: int = 1, lookback_days: int = 14) -> str:
    """
    Core Q&A function — also called by the Telegram bot command handler.
    Returns the answer as a plain string.
    """
    result = await _rag_answer(query, lookback_days)
    return result["answer"]


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest):
    """Answer a question about recent fintech news using RAG."""
    result = await _rag_answer(body.query, body.lookback_days)

    # Persist to chat history
    try:
        await _save_chat_history(body.user_id, body.query, result["answer"])
    except Exception as e:
        logger.warning(f"[chat] History save failed (non-critical): {e}")

    return ChatResponse(
        query=body.query,
        answer=result["answer"],
        sources=result["sources"],
        stories_searched=result["stories_searched"],
    )


@router.get("/history")
async def get_chat_history(user_id: int = 1, limit: int = 20):
    """Return recent Q&A exchanges for a user."""
    try:
        async with get_conn() as conn:
            rows = await (await conn.execute(
                """
                SELECT query, answer, created_at
                FROM chat_history
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )).fetchall()
        return {
            "history": [
                {
                    "query": r[0],
                    "answer": r[1],
                    "created_at": r[2].isoformat() if isinstance(r[2], datetime) else r[2],
                }
                for r in rows
            ]
        }
    except Exception as e:
        logger.error(f"[chat] History fetch failed: {e}")
        return {"history": []}


async def _rag_answer(query: str, lookback_days: int) -> dict:
    """
    Retrieve relevant stories via pgvector, then synthesise an answer with Groq.
    """
    # Step 1: Embed the query
    from app.memory import embed
    query_vec = embed([query])[0].tolist()

    # Step 2: pgvector similarity search
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    stories = await _vector_search(query_vec, cutoff, top_k=8)

    if not stories:
        return {
            "answer": (
                f"I don't have any stories about that in my archive for the last "
                f"{lookback_days} days. Try expanding the lookback window or "
                "check back after the next digest run."
            ),
            "sources": [],
            "stories_searched": 0,
        }

    # Step 3: Groq synthesis
    stories_context = "\n\n".join(
        f"[{i+1}] {s['title']}\nSource: {s['source']}\nURL: {s['url']}"
        for i, s in enumerate(stories)
    )

    prompt = f"""You are a fintech intelligence assistant. Answer the user's question
using ONLY the news stories provided below. If the stories don't contain enough
information to answer the question, say so clearly.

For each claim in your answer, cite the relevant story using [n] notation.
Keep your answer concise (3-5 sentences max) unless a longer answer is clearly needed.

USER QUESTION: {query}

AVAILABLE STORIES:
{stories_context}

Answer:"""

    try:
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=600,
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[chat] Groq synthesis failed: {e}")
        answer = "I encountered an error synthesising an answer. Please try again."

    return {
        "answer": answer,
        "sources": [{"title": s["title"], "source": s["source"], "url": s["url"]}
                    for s in stories],
        "stories_searched": len(stories),
    }


async def _vector_search(query_vec: list[float], cutoff: datetime, top_k: int = 8) -> list[dict]:
    """
    Run a cosine similarity search against story_memory using pgvector.
    Returns top_k most relevant stories within the lookback window.
    """
    vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"
    try:
        async with get_conn() as conn:
            rows = await (await conn.execute(
                """
                SELECT title, source, url,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM story_memory
                WHERE created_at >= %s
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_str, cutoff, vec_str, top_k),
            )).fetchall()
        return [
            {"title": r[0], "source": r[1], "url": r[2], "similarity": round(r[3], 3)}
            for r in rows
        ]
    except Exception as e:
        logger.error(f"[chat] Vector search failed: {e}")
        return []


async def _save_chat_history(user_id: int, query: str, answer: str):
    """Persist Q&A exchange to chat_history table."""
    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO chat_history (user_id, query, answer)
            VALUES (%s, %s, %s)
            """,
            (user_id, query, answer[:2000]),
        )
        await conn.commit()