"""
OpenSanctions integration — covers UN, EU, UK, and 40+ lists.

API: https://api.opensanctions.org/match/default
Docs: https://www.opensanctions.org/docs/api/

Architecture:
  - Batch screen: screen(name, dob?, nationality?) → results[]
  - Cache results in screening_results table (Supabase)
  - DON'T hit API per investigation — costs money and adds latency
  - Each result includes source_url and list_name

Cache strategy:
  - Before calling API, check screening_results for recent results (< 24h)
  - If cache hit, return cached results
  - If cache miss, call API, store results, return
  - Batch multiple names in a single API call (OpenSanctions supports this)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.screening.models import ScreeningMatch
from app.screening.name_utils import normalize_name

logger = logging.getLogger(__name__)

OPENSANCTIONS_MATCH_URL = "https://api.opensanctions.org/match/default"
CACHE_TTL_HOURS = 24  # Cache results for 24 hours


# ---------------------------------------------------------------------------
# Cache layer (Supabase screening_results table)
# ---------------------------------------------------------------------------


async def _check_cache(
    entity_name: str,
    supabase_url: str,
    supabase_key: str,
) -> list[ScreeningMatch] | None:
    """Check if we have recent cached results for this entity."""
    try:
        from supabase import acreate_client
    except ImportError:
        return None

    db = await acreate_client(supabase_url, supabase_key)
    cutoff = (datetime.utcnow() - timedelta(hours=CACHE_TTL_HOURS)).isoformat()

    try:
        response = (
            await db.table("screening_results")
            .select("*")
            .eq("screened_name", entity_name)
            .gte("created_at", cutoff)
            .ilike("list_name", "%opensanctions%")
            .execute()
        )
    except Exception as exc:
        logger.warning("OpenSanctions cache check failed: %s", exc)
        return None

    if not response.data:
        return None

    logger.info("OpenSanctions cache hit for '%s': %d results", entity_name, len(response.data))

    matches: list[ScreeningMatch] = []
    for row in response.data:
        matches.append(
            ScreeningMatch(
                matched=float(row.get("match_confidence", 0)) >= 0.5,
                confidence=float(row.get("match_confidence", 0)),
                matched_entry=row.get("match_data") or {},
                source_url=row.get("source_url") or "",
                list_name=row.get("list_name") or "opensanctions",
                match_type="fuzzy",
                entity_name_queried=entity_name,
                entity_name_matched=row.get("entity_name"),
                screened_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                if row.get("created_at")
                else datetime.utcnow(),
            )
        )

    return matches


async def _store_cache(
    entity_name: str,
    matches: list[ScreeningMatch],
    supabase_url: str,
    supabase_key: str,
    organization_id: str,
    case_id: str | None = None,
) -> None:
    """Store screening results in the cache table. ``organization_id`` is required."""
    try:
        from supabase import acreate_client
    except ImportError:
        return

    db = await acreate_client(supabase_url, supabase_key)

    for match in matches:
        row: dict[str, Any] = {
            "organization_id": organization_id,
            "entity_name": match.entity_name_matched or entity_name,
            "screened_name": entity_name,
            "match_confidence": match.confidence,
            "source_url": match.source_url,
            "match_data": match.matched_entry,
            "list_name": match.list_name,
            "status": "pending",
        }
        if case_id:
            row["case_id"] = case_id

        try:
            await db.table("screening_results").insert(row).execute()
        except Exception as exc:
            logger.warning("Failed to cache screening result: %s", exc)


# ---------------------------------------------------------------------------
# OpenSanctions API
# ---------------------------------------------------------------------------


async def screen_opensanctions(
    name: str,
    api_key: str,
    dob: str | None = None,
    nationality: str | None = None,
    entity_type: str | None = None,
    supabase_url: str = "",
    supabase_key: str = "",
    organization_id: str | None = None,
    case_id: str | None = None,
    use_cache: bool = True,
    timeout: float = 15.0,
) -> list[ScreeningMatch]:
    """
    Screen a name against OpenSanctions (UN, EU, UK, 40+ lists).

    With caching:
      1. Check screening_results for recent results (< 24h)
      2. If cache hit, return immediately
      3. If cache miss, call API, cache results, return

    Returns list of ScreeningMatch with source_url and list_name per hit.
    """
    # --- Check cache ---
    if use_cache and supabase_url and supabase_key:
        cached = await _check_cache(name, supabase_url, supabase_key)
        if cached is not None:
            return cached

    # --- Build API request ---
    properties: dict[str, list[str]] = {"name": [name]}
    if dob:
        properties["birthDate"] = [dob]
    if nationality:
        properties["nationality"] = [nationality]

    schema = "Person" if entity_type == "person" else "LegalEntity"

    payload = {
        "queries": {
            "q": {
                "schema": schema,
                "properties": properties,
            }
        }
    }

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"

    # --- Call API ---
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                OPENSANCTIONS_MATCH_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
    except httpx.HTTPError as exc:
        logger.error("OpenSanctions API error for '%s': %s", name, exc)
        raise

    # --- Parse results ---
    matches: list[ScreeningMatch] = []
    results = data.get("responses", {}).get("q", {}).get("results", [])

    for result in results:
        score = float(result.get("score", 0.0))
        if score < 0.4:  # Very low threshold — let caller decide
            continue

        datasets: list[str] = result.get("datasets", [])
        list_name = _classify_dataset(datasets)
        entity_id = result.get("id", "")
        caption = result.get("caption", "")

        source_url = f"https://www.opensanctions.org/entities/{entity_id}/"

        match_entry = {
            "entity_id": entity_id,
            "caption": caption,
            "schema": result.get("schema"),
            "datasets": datasets,
            "properties": result.get("properties", {}),
            "first_seen": result.get("first_seen"),
            "last_seen": result.get("last_seen"),
            "score": score,
        }

        matches.append(
            ScreeningMatch(
                matched=score >= 0.5,
                confidence=score,
                matched_entry=match_entry,
                source_url=source_url,
                list_name=list_name,
                match_type="exact" if score >= 0.9 else "fuzzy",
                entity_name_queried=name,
                entity_name_matched=caption,
            )
        )

    # --- Cache results ---
    if supabase_url and supabase_key and matches:
        if not organization_id:
            logger.debug(
                "skipping OpenSanctions cache write — no organization_id",
            )
        else:
            await _store_cache(
                name, matches, supabase_url, supabase_key,
                organization_id,
                case_id=case_id,
            )

    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches


# ---------------------------------------------------------------------------
# Batch screening
# ---------------------------------------------------------------------------


async def batch_screen_opensanctions(
    names: list[str],
    api_key: str,
    dob: str | None = None,
    nationality: str | None = None,
    supabase_url: str = "",
    supabase_key: str = "",
    organization_id: str | None = None,
    case_id: str | None = None,
    timeout: float = 30.0,
) -> dict[str, list[ScreeningMatch]]:
    """
    Batch screen multiple names in a single API call.

    OpenSanctions /match supports multiple queries in one request.
    This is critical for cost + latency: don't hit API per name.
    """
    # Build multi-query payload
    queries: dict[str, dict[str, Any]] = {}
    cache_hits: dict[str, list[ScreeningMatch]] = {}

    for i, name in enumerate(names):
        # Check cache first
        if supabase_url and supabase_key:
            cached = await _check_cache(name, supabase_url, supabase_key)
            if cached is not None:
                cache_hits[name] = cached
                continue

        properties: dict[str, list[str]] = {"name": [name]}
        if dob:
            properties["birthDate"] = [dob]
        if nationality:
            properties["nationality"] = [nationality]

        queries[f"q{i}"] = {
            "schema": "LegalEntity",
            "properties": properties,
        }

    # If everything was cached, return immediately
    if not queries:
        return cache_hits

    # Call API with all uncached names
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                OPENSANCTIONS_MATCH_URL,
                headers=headers,
                json={"queries": queries},
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
    except httpx.HTTPError as exc:
        logger.error("OpenSanctions batch API error: %s", exc)
        return cache_hits

    # Parse per-query results
    all_results: dict[str, list[ScreeningMatch]] = dict(cache_hits)
    responses = data.get("responses", {})

    for query_key, query_data in responses.items():
        # Map query key back to name
        idx_str = query_key.replace("q", "")
        try:
            idx = int(idx_str)
            name = names[idx]
        except (ValueError, IndexError):
            continue

        matches: list[ScreeningMatch] = []
        for result in query_data.get("results", []):
            score = float(result.get("score", 0.0))
            if score < 0.4:
                continue

            datasets = result.get("datasets", [])
            list_name = _classify_dataset(datasets)
            entity_id = result.get("id", "")

            matches.append(
                ScreeningMatch(
                    matched=score >= 0.5,
                    confidence=score,
                    matched_entry={
                        "entity_id": entity_id,
                        "caption": result.get("caption", ""),
                        "datasets": datasets,
                        "properties": result.get("properties", {}),
                        "score": score,
                    },
                    source_url=f"https://www.opensanctions.org/entities/{entity_id}/",
                    list_name=list_name,
                    match_type="exact" if score >= 0.9 else "fuzzy",
                    entity_name_queried=name,
                    entity_name_matched=result.get("caption"),
                )
            )

        all_results[name] = sorted(matches, key=lambda m: m.confidence, reverse=True)

        # Cache results
        if supabase_url and supabase_key and matches:
            if not organization_id:
                logger.debug(
                    "skipping OpenSanctions cache write — no organization_id",
                )
            else:
                await _store_cache(
                    name, matches, supabase_url, supabase_key,
                    organization_id,
                    case_id=case_id,
                )

    return all_results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_dataset(datasets: list[str]) -> str:
    """Map OpenSanctions dataset tags to a canonical list name."""
    joined = " ".join(datasets).lower()
    if "pep" in joined:
        return "PEP"
    if "ofac" in joined:
        return "OFAC_SDN"
    if "un_sc" in joined or "un_consolidated" in joined:
        return "UN_CONSOLIDATED"
    if "eu_" in joined:
        return "EU_SANCTIONS"
    if "gb_" in joined or "uk_" in joined:
        return "UK_SANCTIONS"
    return f"opensanctions:{','.join(datasets[:3])}"
