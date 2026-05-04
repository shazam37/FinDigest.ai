"""
News fetcher using Tavily Search API.
Tavily is purpose-built for AI agents — it returns clean, structured results
with publication names and URLs, making it far better than raw Google search
for this use case.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from tavily import TavilyClient

from app.config import settings

logger = logging.getLogger(__name__)

# === Search Queries ===
# Split into focused queries rather than one broad query.
# This improves recall across different story types.
SEARCH_QUERIES = [
    "fintech banking innovation regulation 2025",
    "asset management fund investment technology news",
    "digital banking neobank payment startup news",
    "banking regulation compliance financial crime news",
    "central bank CBDC digital currency news",
    "wealth management robo-advisor fintech news",
    "bank acquisition merger partnership fintech",
    "open banking API financial data news",
]

# === Hard exclusion keywords (post-filter) ===
EXCLUDE_KEYWORDS = [
    "share price", "stock price", "trading at", "earnings per share",
    "quarterly earnings", "annual results", "revenue beat", "revenue miss",
    "conference", "summit", "forum", "keynote", "webinar", "panel discussion",
    "FTSE", "S&P", "Nasdaq", "Dow Jones", "market cap", "bull market", "bear market",
    "index rose", "index fell", "basis points", "yield curve",
]


def is_excluded(title: str, content: str) -> bool:
    """Return True if the story matches any exclusion rule."""
    text = (title + " " + content).lower()
    return any(kw.lower() in text for kw in EXCLUDE_KEYWORDS)


def fetch_fintech_news() -> list[dict]:
    """
    Fetch and deduplicate fintech news from the last LOOKBACK_HOURS hours.
    Returns a list of story dicts: {title, url, source, published_date, snippet}
    """
    client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.LOOKBACK_HOURS)

    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    stories: list[dict] = []

    for query in SEARCH_QUERIES:
        try:
            response = client.search(
                query=query,
                search_depth="advanced",
                topic="news",
                days=1,  # Tavily's built-in recency filter
                max_results=5,
            )
            for result in response.get("results", []):
                url = result.get("url", "")
                title = result.get("title", "").strip()
                snippet = result.get("content", "").strip()
                source = _extract_source(url)
                published = result.get("published_date")

                # Dedup by URL and by title (catches same story from different sources)
                title_key = title[:60].lower()
                if url in seen_urls or title_key in seen_titles:
                    continue

                if is_excluded(title, snippet):
                    logger.debug(f"Excluded: {title}")
                    continue

                seen_urls.add(url)
                seen_titles.add(title_key)
                stories.append({
                    "title": title,
                    "url": url,
                    "source": source,
                    "published_date": published,
                    "snippet": snippet[:400],  # Keep snippets concise
                })

        except Exception as e:
            logger.warning(f"Search failed for query '{query}': {e}")

    logger.info(f"Fetched {len(stories)} stories after filtering")
    return stories[:settings.MAX_STORIES * 2]  # Give LLM some headroom to select best ones


def _extract_source(url: str) -> str:
    """Extract a clean publication name from a URL."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.replace("www.", "")
        # Clean up common suffixes
        host = host.replace(".com", "").replace(".co.uk", "").replace(".org", "")
        # Capitalise each part
        return " ".join(part.capitalize() for part in host.split("."))
    except Exception:
        return "Unknown"