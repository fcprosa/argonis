"""
Unified screening module.

Entry point: screen(name, dob?, nationality?) → ScreeningResponse

Aggregates results from:
  1. OFAC SDN (free, local fuzzy match against downloaded list)
  2. OpenSanctions (UN, EU, UK, 40+ lists — API with caching)
  3. Adverse media (Google Custom Search + Claude summarization)

Each result includes source_url and list_name.
Cache results. Batch screen. Don't repeat API calls.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.screening.adverse_media import search_adverse_media
from app.screening.models import (
    AdverseMediaResponse,
    ScreeningMatch,
    ScreeningRequest,
    ScreeningResponse,
)
from app.screening.ofac import search_ofac
from app.screening.opensanctions import (
    batch_screen_opensanctions,
    screen_opensanctions,
)

logger = logging.getLogger(__name__)

__all__ = [
    "screen",
    "batch_screen",
    "search_adverse_media",
    "ScreeningRequest",
    "ScreeningResponse",
    "ScreeningMatch",
    "AdverseMediaResponse",
]


async def screen(
    name: str,
    dob: str | None = None,
    nationality: str | None = None,
    entity_type: str | None = None,
    *,
    supabase_url: str = "",
    supabase_key: str = "",
    opensanctions_api_key: str = "",
    organization_id: str | None = None,
    case_id: str | None = None,
    include_ofac: bool = True,
    include_opensanctions: bool = True,
) -> ScreeningResponse:
    """
    Unified screening function: screen(name, dob?, nationality?) → results[].

    Runs OFAC SDN and OpenSanctions in parallel.
    Each result includes source_url and list_name.
    Results are cached in screening_results table.
    """
    all_matches: list[ScreeningMatch] = []
    sources_queried: list[str] = []

    tasks: list[asyncio.Task[Any]] = []

    # --- OFAC SDN (always free, local DB match) ---
    if include_ofac and supabase_url and supabase_key:
        tasks.append(
            asyncio.create_task(
                _screen_ofac_safe(name, supabase_url, supabase_key),
                name="ofac",
            )
        )

    # --- OpenSanctions (API, with caching) ---
    if include_opensanctions and opensanctions_api_key:
        tasks.append(
            asyncio.create_task(
                _screen_opensanctions_safe(
                    name, opensanctions_api_key, dob, nationality, entity_type,
                    supabase_url, supabase_key, organization_id, case_id,
                ),
                name="opensanctions",
            )
        )

    # --- Run in parallel ---
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for task, result in zip(tasks, results):
            task_name = task.get_name()
            if isinstance(result, Exception):
                logger.error("Screening task '%s' failed: %s", task_name, result)
                continue
            matches, source = result
            all_matches.extend(matches)
            sources_queried.append(source)

    return ScreeningResponse(
        entity_name=name,
        results=all_matches,
        sources_queried=sources_queried,
        screened_at=datetime.utcnow(),
    )


async def batch_screen(
    names: list[str],
    dob: str | None = None,
    nationality: str | None = None,
    *,
    supabase_url: str = "",
    supabase_key: str = "",
    opensanctions_api_key: str = "",
    organization_id: str | None = None,
    case_id: str | None = None,
) -> dict[str, ScreeningResponse]:
    """
    Batch screen multiple names.

    Uses OpenSanctions batch API for efficiency.
    OFAC is screened per-name (local DB, fast).
    """
    results: dict[str, ScreeningResponse] = {}

    # --- OFAC: screen each name (local DB, fast) ---
    ofac_results: dict[str, list[ScreeningMatch]] = {}
    if supabase_url and supabase_key:
        ofac_tasks = {
            name: asyncio.create_task(
                _screen_ofac_safe(name, supabase_url, supabase_key)
            )
            for name in names
        }
        ofac_gathered = await asyncio.gather(*ofac_tasks.values(), return_exceptions=True)
        for name, result in zip(ofac_tasks.keys(), ofac_gathered):
            if isinstance(result, Exception):
                logger.error("OFAC batch screen failed for '%s': %s", name, result)
                ofac_results[name] = []
            else:
                ofac_results[name] = result[0]

    # --- OpenSanctions: batch API call ---
    os_results: dict[str, list[ScreeningMatch]] = {}
    if opensanctions_api_key:
        os_results = await batch_screen_opensanctions(
            names, opensanctions_api_key,
            dob=dob, nationality=nationality,
            supabase_url=supabase_url, supabase_key=supabase_key,
            organization_id=organization_id, case_id=case_id,
        )

    # --- Merge results ---
    for name in names:
        all_matches: list[ScreeningMatch] = []
        sources: list[str] = []

        if name in ofac_results:
            all_matches.extend(ofac_results[name])
            sources.append("OFAC_SDN")

        if name in os_results:
            all_matches.extend(os_results[name])
            sources.append("OpenSanctions")

        results[name] = ScreeningResponse(
            entity_name=name,
            results=all_matches,
            sources_queried=sources,
        )

    return results


# ---------------------------------------------------------------------------
# Safe wrappers (catch exceptions, return empty on failure)
# ---------------------------------------------------------------------------


async def _screen_ofac_safe(
    name: str,
    supabase_url: str,
    supabase_key: str,
) -> tuple[list[ScreeningMatch], str]:
    """Wrapper that catches exceptions."""
    try:
        matches = await search_ofac(name, supabase_url, supabase_key)
        return matches, "OFAC_SDN"
    except Exception as exc:
        logger.error("OFAC screening failed for '%s': %s", name, exc)
        return [], "OFAC_SDN"


async def _screen_opensanctions_safe(
    name: str,
    api_key: str,
    dob: str | None,
    nationality: str | None,
    entity_type: str | None,
    supabase_url: str,
    supabase_key: str,
    organization_id: str | None,
    case_id: str | None,
) -> tuple[list[ScreeningMatch], str]:
    """Wrapper that catches exceptions."""
    try:
        matches = await screen_opensanctions(
            name, api_key,
            dob=dob, nationality=nationality, entity_type=entity_type,
            supabase_url=supabase_url, supabase_key=supabase_key,
            organization_id=organization_id, case_id=case_id,
        )
        return matches, "OpenSanctions"
    except Exception as exc:
        logger.error("OpenSanctions screening failed for '%s': %s", name, exc)
        return [], "OpenSanctions"
