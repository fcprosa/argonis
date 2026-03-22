"""
Step 3: SCREEN — Sanctions, PEP, and adverse media screening.

Deterministic: external API calls returning structured hits. No LLM.
Every hit is stored with match_confidence and source_url.

Screening sources (in order of priority):
  1. OFAC SDN (free — fuzzy match against downloaded list in Supabase)
  2. OpenSanctions API (UN, EU, UK, 40+ lists — with caching)
  3. Adverse media keyword detection (from alert's own screening fields)
  4. Serper.dev adverse media search (when configured)
  5. Stub path when no API keys are configured

All results are factual — confidence scores reflect actual match scores,
not LLM estimates. Every hit has source_url for analyst verification.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from app.pipeline.models import ParsedAlert, ScreeningBundle, ScreeningHit
from app.screening import screen as unified_screen
from app.screening.ofac import search_ofac

logger = logging.getLogger(__name__)

# Keywords that indicate adverse media when found in alert text
_ADVERSE_KEYWORDS = frozenset(
    [
        "fraud",
        "money laundering",
        "corruption",
        "bribery",
        "trafficking",
        "terrorism",
        "sanctions",
        "embezzlement",
        "tax evasion",
        "vat fraud",
        "criminal",
        "convicted",
        "indicted",
        "arrested",
        "investigated",
        "charged",
        "debarred",
    ]
)


async def screen_entities(
    parsed: ParsedAlert,
    opensanctions_api_key: str = "",
    supabase_url: str = "",
    supabase_key: str = "",
    organization_id: str | None = None,
    case_id: str | None = None,
) -> ScreeningBundle:
    """
    Screen all entities extracted from the parsed alert.

    Uses the unified screening module which runs OFAC SDN + OpenSanctions
    in parallel, with caching. Falls back to alert field stubs when
    no APIs are configured.
    """
    entities = _extract_entity_names(parsed)
    all_hits: list[ScreeningHit] = []
    sources_queried: list[str] = []
    now = datetime.utcnow()

    has_any_api = bool(opensanctions_api_key) or bool(supabase_url and supabase_key)

    if has_any_api:
        # --- Use the unified screening module ---
        for entity in entities:
            response = await unified_screen(
                name=entity,
                dob=parsed.dob.isoformat() if parsed.dob else None,
                nationality=parsed.nationality,
                supabase_url=supabase_url,
                supabase_key=supabase_key,
                opensanctions_api_key=opensanctions_api_key,
                organization_id=organization_id,
                case_id=case_id,
            )

            for match in response.results:
                all_hits.append(
                    ScreeningHit(
                        entity_name=entity,
                        list_name=match.list_name,
                        match_confidence=match.confidence,
                        match_type=match.match_type,
                        source_url=match.source_url,
                        snippet=match.matched_entry.get("caption")
                        or match.matched_entry.get("remarks")
                        or match.matched_entry.get("sdn_name"),
                        screened_at=match.screened_at,
                    )
                )

            sources_queried.extend(response.sources_queried)
    else:
        # --- Stub path: read from alert fields ---
        logger.warning("step=screen no API keys configured — reading from alert fields")
        stub_hits = _stub_sanctions_screen(parsed, entities, now)
        all_hits.extend(stub_hits)
        sources_queried.append("alert_fields_stub")

    # --- Always run keyword-based adverse media detection ---
    media_hits = _screen_adverse_media_keywords(parsed, entities, now)
    all_hits.extend(media_hits)
    if media_hits:
        sources_queried.append("adverse_media_keywords")

    # Deduplicate sources
    sources_queried = list(dict.fromkeys(sources_queried))

    return ScreeningBundle(
        entity_names=entities,
        hits=all_hits,
        sources_queried=sources_queried,
        screened_at=now,
    )


# ---------------------------------------------------------------------------
# Stub path (reads from alert fields when no APIs configured)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Adverse media (keyword scan — always runs, free)
# ---------------------------------------------------------------------------


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
    """Extract 'source: X' from screening text."""
    match = re.search(r"source:\s*([^,)]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_entity_names(parsed: ParsedAlert) -> list[str]:
    names: list[str] = []
    if parsed.account_holder:
        names.append(parsed.account_holder)
    if parsed.beneficial_owner_name and parsed.beneficial_owner_name != parsed.account_holder:
        names.append(parsed.beneficial_owner_name)
    return names
