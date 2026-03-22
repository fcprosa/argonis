"""
Adverse media search — Serper.dev API + Claude summarization.

Serper.dev (https://serper.dev) provides Google search results via a simple
REST API.  Endpoint: POST https://google.serper.dev/search (or /news).

Budget constraint: 3-5 queries per investigation, max.

Targeted queries:
  - '{name} money laundering'
  - '{name} sanctions fraud'
  - '{name} regulatory action'
  - '{name} financial crime'  (if budget allows)
  - '{name} {nationality} sanctions'  (if nationality provided)

Claude summarizes relevance of each article.
Store the actual URLs — analysts MUST click through and read the source.

ANTI-ERROR: If the analyst can't click through and read the source,
the screening is worthless. Every article has a URL, title, snippet.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import anthropic
import httpx

from app.screening.models import AdverseMediaArticle, AdverseMediaResponse

logger = logging.getLogger(__name__)

SERPER_SEARCH_URL = "https://google.serper.dev/search"
SERPER_NEWS_URL = "https://google.serper.dev/news"

# Targeted query templates — these are the AML-specific searches
_QUERY_TEMPLATES = [
    "{name} money laundering",
    "{name} sanctions fraud",
    "{name} regulatory action",
    "{name} financial crime",
    "{name} {extra} sanctions",  # Only used if nationality/extra context provided
]

MAX_QUERIES_PER_INVESTIGATION = 5
MAX_RESULTS_PER_QUERY = 3  # Serper returns up to 100; we take top 3


# ---------------------------------------------------------------------------
# Serper.dev Search
# ---------------------------------------------------------------------------


async def _search_serper(
    query: str,
    api_key: str,
    num_results: int = MAX_RESULTS_PER_QUERY,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Execute a single search query via the Serper.dev API.

    Hits both the regular search and news endpoints, deduplicates by URL,
    and returns a merged list of results.
    """
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "q": query,
        "num": min(num_results, 10),
        "tbs": "qdr:y5",  # Last 5 years for relevance
    }

    articles: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    async with httpx.AsyncClient(timeout=timeout) as client:
        # --- Regular web search ---
        try:
            response = await client.post(
                SERPER_SEARCH_URL, json=payload, headers=headers,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()

            for item in data.get("organic", [])[:num_results]:
                url = item.get("link", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    articles.append({
                        "url": url,
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                    })
        except httpx.HTTPError as exc:
            logger.error("Serper web search error for query '%s': %s", query, exc)

        # --- News search (often surfaces more relevant AML/sanctions articles) ---
        try:
            news_payload = {**payload}
            news_payload.pop("tbs", None)  # tbs not supported on /news
            news_response = await client.post(
                SERPER_NEWS_URL, json=news_payload, headers=headers,
            )
            news_response.raise_for_status()
            news_data: dict[str, Any] = news_response.json()

            for item in news_data.get("news", [])[:num_results]:
                url = item.get("link", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    articles.append({
                        "url": url,
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                    })
        except httpx.HTTPError as exc:
            logger.error("Serper news search error for query '%s': %s", query, exc)

    return articles


# ---------------------------------------------------------------------------
# Claude relevance summarization
# ---------------------------------------------------------------------------


async def _summarize_relevance(
    entity_name: str,
    articles: list[dict[str, str]],
    anthropic_client: anthropic.AsyncAnthropic,
) -> list[AdverseMediaArticle]:
    """
    Use Claude to assess the relevance of each article to AML concerns.

    Returns articles with relevance_score and claude_summary.
    """
    if not articles:
        return []

    # Build a compact prompt — we don't want to waste tokens
    articles_text = "\n".join(
        f"[{i+1}] Title: {a['title']}\n    URL: {a['url']}\n    Snippet: {a['snippet']}"
        for i, a in enumerate(articles)
    )

    prompt = f"""You are an AML compliance analyst. Assess the relevance of each article to financial crime concerns about "{entity_name}".

For each article, provide:
1. relevance_score (0.0-1.0): How relevant is this to AML/sanctions/financial crime?
2. summary (1-2 sentences): Why is this relevant or not?

IMPORTANT: Only score > 0.5 if the article specifically mentions the entity in connection with financial crime, sanctions, money laundering, fraud, or regulatory action. Generic news or name collisions score < 0.3.

Articles:
{articles_text}

Respond as JSON array:
[{{"index": 1, "relevance_score": 0.85, "summary": "Article describes..."}}]"""

    try:
        message = await anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",  # Use Sonnet for cost efficiency on summarization
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        import json
        response_text = message.content[0].text  # type: ignore[union-attr]

        # Extract JSON from response (handle markdown code blocks)
        json_text = response_text
        if "```" in json_text:
            # Extract content between code fences
            import re
            json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", json_text, re.DOTALL)
            if json_match:
                json_text = json_match.group(1)

        assessments = json.loads(json_text)
    except Exception as exc:
        logger.warning("Claude relevance summarization failed: %s", exc)
        # Fall back: return articles without Claude assessment
        return [
            AdverseMediaArticle(
                url=a.get("url", ""),
                title=a.get("title", ""),
                snippet=a.get("snippet", ""),
                query_used=a.get("query_used", ""),
                relevance_score=0.5,  # Unknown relevance
                claude_summary=None,
            )
            for a in articles
        ]

    # Merge Claude assessments with articles
    scored_articles: list[AdverseMediaArticle] = []
    for assessment in assessments:
        idx = int(assessment.get("index", 0)) - 1
        if 0 <= idx < len(articles):
            article = articles[idx]
            scored_articles.append(
                AdverseMediaArticle(
                    url=article["url"],
                    title=article["title"],
                    snippet=article["snippet"],
                    query_used=article.get("query_used", ""),
                    relevance_score=min(1.0, max(0.0, float(assessment.get("relevance_score", 0.5)))),
                    claude_summary=assessment.get("summary"),
                )
            )

    return scored_articles


# ---------------------------------------------------------------------------
# Store results in Supabase
# ---------------------------------------------------------------------------


async def _store_adverse_media(
    entity_name: str,
    articles: list[AdverseMediaArticle],
    supabase_url: str,
    supabase_key: str,
    organization_id: str | None = None,
    case_id: str | None = None,
) -> None:
    """Persist adverse media results to the adverse_media_results table."""
    if not articles or not supabase_url or not supabase_key:
        return

    try:
        from supabase import acreate_client
    except ImportError:
        return

    db = await acreate_client(supabase_url, supabase_key)

    for article in articles:
        row: dict[str, Any] = {
            "entity_name": entity_name,
            "query_text": article.query_used,
            "article_url": article.url,
            "article_title": article.title,
            "article_snippet": article.snippet,
            "relevance_score": article.relevance_score,
            "claude_summary": article.claude_summary,
            "search_engine": "serper",
        }
        if organization_id:
            row["organization_id"] = organization_id
        if case_id:
            row["case_id"] = case_id

        try:
            await db.table("adverse_media_results").insert(row).execute()
        except Exception as exc:
            logger.warning("Failed to store adverse media result: %s", exc)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def search_adverse_media(
    name: str,
    serper_api_key: str,
    anthropic_api_key: str | None = None,
    nationality: str | None = None,
    max_queries: int = MAX_QUERIES_PER_INVESTIGATION,
    supabase_url: str = "",
    supabase_key: str = "",
    organization_id: str | None = None,
    case_id: str | None = None,
) -> AdverseMediaResponse:
    """
    Search for adverse media about an entity.

    1. Build 3-5 targeted queries
    2. Execute via Serper.dev API (web search + news search)
    3. Deduplicate results
    4. Claude summarizes relevance
    5. Store article URLs in database

    Returns AdverseMediaResponse with articles, each containing:
      - url (MUST be present — analysts click through to verify)
      - title
      - snippet
      - relevance_score
      - claude_summary
    """
    # --- Build queries ---
    queries: list[str] = []
    for template in _QUERY_TEMPLATES[:max_queries]:
        if "{extra}" in template:
            if nationality:
                queries.append(template.format(name=name, extra=nationality))
        else:
            queries.append(template.format(name=name))

    queries = queries[:max_queries]
    logger.info("Adverse media search for '%s': %d queries", name, len(queries))

    # --- Execute searches ---
    all_articles: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for query in queries:
        results = await _search_serper(query, serper_api_key)
        for result in results:
            url = result["url"]
            if url not in seen_urls:
                seen_urls.add(url)
                result["query_used"] = query
                all_articles.append(result)

    logger.info("Found %d unique articles for '%s'", len(all_articles), name)

    if not all_articles:
        return AdverseMediaResponse(
            entity_name=name,
            articles=[],
            queries_used=queries,
            total_articles_found=0,
        )

    # --- Claude summarization (optional but recommended) ---
    if anthropic_api_key:
        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
        scored_articles = await _summarize_relevance(name, all_articles, client)
    else:
        # Without Claude, return raw articles with neutral score
        scored_articles = [
            AdverseMediaArticle(
                url=a["url"],
                title=a["title"],
                snippet=a["snippet"],
                query_used=a.get("query_used", ""),
                relevance_score=0.5,
                claude_summary=None,
            )
            for a in all_articles
        ]

    # Sort by relevance
    scored_articles.sort(key=lambda a: a.relevance_score, reverse=True)

    # --- Store in DB ---
    await _store_adverse_media(
        name, scored_articles, supabase_url, supabase_key,
        organization_id=organization_id, case_id=case_id,
    )

    return AdverseMediaResponse(
        entity_name=name,
        articles=scored_articles,
        queries_used=queries,
        total_articles_found=len(scored_articles),
    )
