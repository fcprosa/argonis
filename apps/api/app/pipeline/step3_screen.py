"""
Step 3: SCREEN — Sanctions, PEP, and adverse media screening.

Deterministic: external API calls returning structured hits. No LLM.
Every hit is stored with match_confidence and source_url.

Failure policy
--------------
* **OFAC SDN** — HARD FAIL. It's local and our primary sanctions source.
  An empty table or query failure means something is fundamentally broken.
  The pipeline halts via ``OfacDataUnavailableError``.

* **OpenSanctions** — SOFT FAIL. A 429, timeout, or other error is recorded
  in ``ScreeningBundle.coverage_gaps`` and the pipeline continues with
  ``is_partial=True``.

* **Serper adverse media** — SOFT FAIL (same treatment).

OpenSanctions uses a 10-second ``asyncio.wait_for`` timeout. Adverse media
(Serper multi-query) uses 25 seconds: Serper can legitimately take 15–20s on
slow networks; 25s gives headroom without letting a real hang block the
pipeline indefinitely. Both use try/except that classifies the failure mode.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any

import httpx

from app.pipeline.errors import OfacDataUnavailableError
from app.pipeline.models import (
    ParsedAlert,
    ScreeningBundle,
    ScreeningHit,
    SourceResult,
)
from app.screening.ofac import search_ofac
from app.screening.opensanctions import screen_opensanctions
from app.screening.adverse_media import search_adverse_media
from app.screening.models import ScreeningMatch

logger = logging.getLogger(__name__)

_SOFT_SOURCE_TIMEOUT_SECONDS = 10


def _sanitize_gap_message(source: str, status: str, raw_error: str) -> str:
    """Map raw screening errors to analyst-facing language (no URLs / HTTP noise)."""
    s = (source or "").strip().lower()
    if s == "opensanctions":
        return (
            "Sanctions list screening (OpenSanctions) was unavailable — "
            "no match could be confirmed."
        )
    if s == "adverse_media":
        if (status or "").strip().lower() == "timeout":
            return "Adverse media screening timed out before completion."
        return "Adverse media screening was unavailable."
    if s == "ofac":
        return "OFAC SDN screening was unavailable."
    return f"{source} screening was unavailable."


def _record_gap(
    *,
    coverage_gaps: list[str],
    coverage_gaps_debug: list[str],
    source: str,
    status: str,
    raw_message: str,
) -> None:
    coverage_gaps_debug.append(raw_message)
    coverage_gaps.append(_sanitize_gap_message(source, status, raw_error=raw_message))


# Serper multi-query searches can legitimately take 15–20s on slow networks;
# 25s gives headroom without letting a real hang block the pipeline indefinitely.
_ADVERSE_MEDIA_TIMEOUT_SECONDS = 25


# ---------------------------------------------------------------------------
# OFAC preflight (hard fail)
# ---------------------------------------------------------------------------


async def _assert_ofac_loaded(supabase_url: str, supabase_key: str) -> None:
    """Raise OfacDataUnavailableError if the OFAC SDN table is empty."""
    from supabase import acreate_client

    db = await acreate_client(supabase_url, supabase_key)
    result = (
        await db.table("ofac_sdn_entries")
        .select("id", count="exact")
        .limit(0)
        .execute()
    )
    if (result.count or 0) == 0:
        raise OfacDataUnavailableError(
            "OFAC SDN tables are empty — refresh required before screening"
        )


# ---------------------------------------------------------------------------
# Per-source screening with failure classification
# ---------------------------------------------------------------------------


def _classify_exception(exc: Exception) -> str:
    """Return a status string based on exception type."""
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 429:
            return "rate_limited"
    return "failed"


def _sanitize_error(exc: Exception) -> str:
    """Produce a log-safe error message (no credentials/tokens)."""
    msg = str(exc)
    msg = re.sub(r"(key|token|secret|password)=\S+", r"\1=***", msg, flags=re.I)
    return msg[:500]


async def _screen_ofac(
    entities: list[str],
    supabase_url: str,
    supabase_key: str,
    now: datetime,
) -> SourceResult:
    """OFAC SDN local fuzzy match.  Returns SourceResult; exceptions propagate."""
    t0 = time.monotonic()
    matches: list[ScreeningHit] = []
    for entity in entities:
        raw_matches = await search_ofac(entity, supabase_url, supabase_key)
        for m in raw_matches:
            matches.append(
                ScreeningHit(
                    entity_name=entity,
                    list_name=m.list_name,
                    match_confidence=m.confidence,
                    match_type=m.match_type,
                    source_url=m.source_url,
                    snippet=(
                        m.matched_entry.get("caption")
                        or m.matched_entry.get("remarks")
                        or m.matched_entry.get("sdn_name")
                    ),
                    screened_at=m.screened_at,
                )
            )
    elapsed = int((time.monotonic() - t0) * 1000)
    return SourceResult(
        source_name="OFAC_SDN",
        status="success",
        matches=matches,
        duration_ms=elapsed,
    )


async def _screen_opensanctions(
    entities: list[str],
    api_key: str,
    parsed: ParsedAlert,
    supabase_url: str,
    supabase_key: str,
    organization_id: str | None,
    case_id: str | None,
    now: datetime,
) -> SourceResult:
    """OpenSanctions API screening with timeout + soft-fail."""
    t0 = time.monotonic()
    matches: list[ScreeningHit] = []
    try:
        for entity in entities:
            raw = await asyncio.wait_for(
                screen_opensanctions(
                    entity,
                    api_key,
                    dob=parsed.dob.isoformat() if parsed.dob else None,
                    nationality=parsed.nationality,
                    supabase_url=supabase_url,
                    supabase_key=supabase_key,
                    organization_id=organization_id,
                    case_id=case_id,
                ),
                timeout=_SOFT_SOURCE_TIMEOUT_SECONDS,
            )
            for m in raw:
                matches.append(
                    ScreeningHit(
                        entity_name=entity,
                        list_name=m.list_name,
                        match_confidence=m.confidence,
                        match_type=m.match_type,
                        source_url=m.source_url,
                        snippet=(
                            m.matched_entry.get("caption")
                            or m.matched_entry.get("remarks")
                        ),
                        screened_at=m.screened_at,
                    )
                )
        elapsed = int((time.monotonic() - t0) * 1000)
        return SourceResult(
            source_name="OpenSanctions",
            status="success",
            matches=matches,
            duration_ms=elapsed,
        )
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        status = _classify_exception(exc)
        err_msg = _sanitize_error(exc)
        logger.warning(
            "OpenSanctions screening %s: %s (duration=%dms)",
            status, err_msg, elapsed,
        )
        return SourceResult(
            source_name="OpenSanctions",
            status=status,
            matches=matches,
            error_message=err_msg,
            duration_ms=elapsed,
        )


async def _screen_adverse_media(
    entities: list[str],
    serper_api_key: str,
    anthropic_api_key: str | None,
    parsed: ParsedAlert,
    supabase_url: str,
    supabase_key: str,
    organization_id: str | None,
    case_id: str | None,
    now: datetime,
) -> SourceResult:
    """Serper.dev adverse media search with timeout + soft-fail."""
    t0 = time.monotonic()
    matches: list[ScreeningHit] = []
    try:
        for entity in entities:
            response = await asyncio.wait_for(
                search_adverse_media(
                    name=entity,
                    serper_api_key=serper_api_key,
                    anthropic_api_key=anthropic_api_key,
                    nationality=parsed.nationality,
                    supabase_url=supabase_url,
                    supabase_key=supabase_key,
                    organization_id=organization_id,
                    case_id=case_id,
                ),
                timeout=_ADVERSE_MEDIA_TIMEOUT_SECONDS,
            )
            for article in response.articles:
                if article.relevance_score < 0.5:
                    continue
                matches.append(
                    ScreeningHit(
                        entity_name=entity,
                        list_name="adverse_media",
                        match_confidence=article.relevance_score,
                        match_type="keyword",
                        source_url=article.url,
                        snippet=article.snippet[:400] if article.snippet else None,
                        screened_at=response.screened_at,
                    )
                )
        elapsed = int((time.monotonic() - t0) * 1000)
        return SourceResult(
            source_name="adverse_media",
            status="success",
            matches=matches,
            duration_ms=elapsed,
        )
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        status = _classify_exception(exc)
        err_msg = _sanitize_error(exc)
        logger.warning(
            "Adverse media screening %s: %s (duration=%dms)",
            status, err_msg, elapsed,
        )
        return SourceResult(
            source_name="adverse_media",
            status=status,
            matches=matches,
            error_message=err_msg,
            duration_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# Keywords-based adverse media (always runs, free, never fails)
# ---------------------------------------------------------------------------

_ADVERSE_KEYWORDS = frozenset(
    [
        "fraud", "money laundering", "corruption", "bribery", "trafficking",
        "terrorism", "sanctions", "embezzlement", "tax evasion", "vat fraud",
        "criminal", "convicted", "indicted", "arrested", "investigated",
        "charged", "debarred",
    ]
)


def _screen_adverse_media_keywords(
    parsed: ParsedAlert,
    entities: list[str],
    now: datetime,
) -> list[ScreeningHit]:
    """Keyword-based adverse media detection across all alert text fields."""
    corpus = " ".join(
        [
            parsed.screening_hits_raw,
            parsed.sanctions_hits_raw,
            parsed.pep_hits_raw,
            parsed.actual_activity_30d,
        ]
    ).lower()

    found_keywords = [kw for kw in _ADVERSE_KEYWORDS if kw in corpus]
    if not found_keywords:
        return []

    hits: list[ScreeningHit] = []
    for entity in entities:
        if entity.lower() in parsed.screening_hits_raw.lower():
            hits.append(
                ScreeningHit(
                    entity_name=entity,
                    list_name="adverse_media",
                    match_confidence=0.85,
                    match_type="keyword",
                    source_url=_extract_source(parsed.screening_hits_raw),
                    snippet=parsed.screening_hits_raw[:400],
                    screened_at=now,
                )
            )
    return hits


def _extract_source(text: str) -> str | None:
    match = re.search(r"source:\s*([^,)]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _stub_sanctions_screen(
    parsed: ParsedAlert,
    entities: list[str],
    now: datetime,
) -> list[ScreeningHit]:
    """Read pre-existing sanctions/PEP hits from the alert's own fields."""
    hits: list[ScreeningHit] = []
    sanctions_raw = parsed.sanctions_hits_raw.strip()
    pep_raw = parsed.pep_hits_raw.strip()

    for entity in entities:
        if sanctions_raw and sanctions_raw.lower() != "none":
            hits.append(
                ScreeningHit(
                    entity_name=entity,
                    list_name="sanctions_alert_field",
                    match_confidence=0.90,
                    match_type="exact",
                    source_url=None,
                    snippet=sanctions_raw[:300],
                    screened_at=now,
                )
            )
        if pep_raw and pep_raw.lower() != "none":
            hits.append(
                ScreeningHit(
                    entity_name=entity,
                    list_name="PEP_alert_field",
                    match_confidence=0.80,
                    match_type="fuzzy",
                    source_url=None,
                    snippet=pep_raw[:300],
                    screened_at=now,
                )
            )
    return hits


def _extract_entity_names(parsed: ParsedAlert) -> list[str]:
    names: list[str] = []
    if parsed.account_holder:
        names.append(parsed.account_holder)
    if parsed.beneficial_owner_name and parsed.beneficial_owner_name != parsed.account_holder:
        names.append(parsed.beneficial_owner_name)
    return names


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def screen_entities(
    parsed: ParsedAlert,
    opensanctions_api_key: str = "",
    serper_api_key: str = "",
    anthropic_api_key: str | None = None,
    supabase_url: str = "",
    supabase_key: str = "",
    organization_id: str | None = None,
    case_id: str | None = None,
) -> ScreeningBundle:
    """
    Screen all entities with explicit failure policy.

    OFAC = hard fail (raises OfacDataUnavailableError).
    OpenSanctions / adverse media = soft fail (pipeline continues).
    """
    entities = _extract_entity_names(parsed)
    all_hits: list[ScreeningHit] = []
    sources_queried: list[str] = []
    source_results: list[SourceResult] = []
    coverage_gaps: list[str] = []
    coverage_gaps_debug: list[str] = []
    now = datetime.utcnow()

    has_supabase = bool(supabase_url and supabase_key)

    # --- OFAC preflight (hard fail) ---
    if has_supabase:
        await _assert_ofac_loaded(supabase_url, supabase_key)

    # --- Run sources in parallel where possible ---
    tasks: dict[str, asyncio.Task[SourceResult]] = {}

    if has_supabase:
        tasks["ofac"] = asyncio.create_task(
            _screen_ofac(entities, supabase_url, supabase_key, now)
        )

    if opensanctions_api_key:
        tasks["opensanctions"] = asyncio.create_task(
            _screen_opensanctions(
                entities, opensanctions_api_key, parsed,
                supabase_url, supabase_key, organization_id, case_id, now,
            )
        )
    else:
        source_results.append(SourceResult(
            source_name="OpenSanctions", status="skipped",
        ))

    if serper_api_key:
        tasks["adverse_media"] = asyncio.create_task(
            _screen_adverse_media(
                entities, serper_api_key, anthropic_api_key, parsed,
                supabase_url, supabase_key, organization_id, case_id, now,
            )
        )
    else:
        source_results.append(SourceResult(
            source_name="adverse_media", status="skipped",
        ))

    if tasks:
        done = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for key, result in zip(tasks, done):
            if isinstance(result, Exception):
                if key == "ofac":
                    raise result
                status = _classify_exception(result)
                err_msg = _sanitize_error(result)
                logger.error("Screening source '%s' raised: %s", key, err_msg)
                sr = SourceResult(
                    source_name=key, status=status, error_message=err_msg,
                )
                source_results.append(sr)
                raw_gap = f"{key} screening {status}: {err_msg}"
                _record_gap(
                    coverage_gaps=coverage_gaps,
                    coverage_gaps_debug=coverage_gaps_debug,
                    source=key,
                    status=status,
                    raw_message=raw_gap,
                )
            else:
                source_results.append(result)
                if result.status == "success":
                    all_hits.extend(result.matches)
                    sources_queried.append(result.source_name)
                else:
                    raw_gap = (
                        f"{result.source_name} screening {result.status}"
                        + (
                            f": {result.error_message}"
                            if result.error_message
                            else ""
                        )
                    )
                    _record_gap(
                        coverage_gaps=coverage_gaps,
                        coverage_gaps_debug=coverage_gaps_debug,
                        source=result.source_name,
                        status=result.status,
                        raw_message=raw_gap,
                    )

    if not has_supabase and not opensanctions_api_key:
        logger.warning("step=screen no API keys configured — reading from alert fields")
        stub_hits = _stub_sanctions_screen(parsed, entities, now)
        all_hits.extend(stub_hits)
        sources_queried.append("alert_fields_stub")

    # Keyword-based adverse media always runs (free, local, never fails)
    media_hits = _screen_adverse_media_keywords(parsed, entities, now)
    all_hits.extend(media_hits)
    if media_hits:
        sources_queried.append("adverse_media_keywords")

    sources_queried = list(dict.fromkeys(sources_queried))

    is_partial = len(coverage_gaps) > 0
    if is_partial:
        logger.warning(
            "step=screen PARTIAL coverage: %s", coverage_gaps,
        )

    return ScreeningBundle(
        entity_names=entities,
        hits=all_hits,
        sources_queried=sources_queried,
        screened_at=now,
        source_results=source_results,
        coverage_gaps=coverage_gaps,
        coverage_gaps_debug=coverage_gaps_debug,
        is_partial=is_partial,
    )
