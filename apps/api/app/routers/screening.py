"""
Screening API endpoints.

Endpoints:
  POST /screening/screen          — Screen a single name
  POST /screening/batch           — Batch screen multiple names
  POST /screening/adverse-media   — Search adverse media for a name
  POST /screening/ofac/refresh    — Refresh OFAC SDN data (cron endpoint)
  GET  /screening/ofac/status     — OFAC SDN staleness + counts (JWT required)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_user
from app.config import settings
from app.db import get_service_db
from app.screening import (
    AdverseMediaResponse,
    ScreeningResponse,
    batch_screen,
    screen,
)
from app.screening.adverse_media import search_adverse_media
from app.screening.ofac import (
    ALT_CSV_URL,
    SDN_CSV_URL,
    download_sdn_csv,
    load_sdn_to_db,
    parse_alt_csv,
    parse_sdn_csv,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/screening", tags=["screening"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ScreenRequest(BaseModel):
    name: str = Field(min_length=1, description="Entity name to screen")
    dob: str | None = Field(default=None, description="Date of birth (ISO 8601)")
    nationality: str | None = Field(default=None, description="ISO 3166-1 alpha-2 country code")
    entity_type: str | None = Field(default=None, description="'person' or 'organization'")
    organization_id: str | None = None
    case_id: str | None = None


class BatchScreenRequest(BaseModel):
    names: list[str] = Field(min_length=1, max_length=50, description="Entity names to screen (max 50)")
    dob: str | None = None
    nationality: str | None = None
    organization_id: str | None = None
    case_id: str | None = None


class AdverseMediaRequest(BaseModel):
    name: str = Field(min_length=1)
    nationality: str | None = None
    max_queries: int = Field(default=3, ge=1, le=5)
    organization_id: str | None = None
    case_id: str | None = None


class RefreshResponse(BaseModel):
    status: str
    message: str
    entries_count: int = 0
    alternates_count: int = 0


class OfacStatusResponse(BaseModel):
    entries_count: int
    alternates_count: int
    last_refreshed_at: str | None
    staleness_hours: float | None
    is_stale: bool
    is_empty: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/screen", response_model=ScreeningResponse)
async def screen_entity(req: ScreenRequest) -> ScreeningResponse:
    """
    Screen a single entity against OFAC SDN + OpenSanctions.

    Returns: {entity_name, results[], sources_queried, has_match, highest_confidence}
    Each result includes: {matched, confidence, matched_entry, source_url, list_name}
    """
    return await screen(
        name=req.name,
        dob=req.dob,
        nationality=req.nationality,
        entity_type=req.entity_type,
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_key,
        opensanctions_api_key=settings.opensanctions_api_key,
        organization_id=req.organization_id,
        case_id=req.case_id,
    )


@router.post("/batch", response_model=dict[str, ScreeningResponse])
async def batch_screen_entities(
    req: BatchScreenRequest,
) -> dict[str, ScreeningResponse]:
    """
    Batch screen multiple entities in a single request.

    Uses OpenSanctions batch API for efficiency — don't hit API per name.
    """
    return await batch_screen(
        names=req.names,
        dob=req.dob,
        nationality=req.nationality,
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_key,
        opensanctions_api_key=settings.opensanctions_api_key,
        organization_id=req.organization_id,
        case_id=req.case_id,
    )


@router.post("/adverse-media", response_model=AdverseMediaResponse)
async def search_media(req: AdverseMediaRequest) -> AdverseMediaResponse:
    """
    Search for adverse media about an entity.

    Uses Serper.dev API (Google search results).
    Limit: 3-5 queries per investigation.
    Claude summarizes relevance of each article.
    Stores article URLs — analysts MUST click through and verify.
    """
    if not settings.serper_api_key:
        raise HTTPException(
            status_code=503,
            detail="Serper.dev not configured (SERPER_API_KEY required)",
        )

    return await search_adverse_media(
        name=req.name,
        serper_api_key=settings.serper_api_key,
        anthropic_api_key=settings.anthropic_api_key or None,
        nationality=req.nationality,
        max_queries=req.max_queries,
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_key,
        organization_id=req.organization_id,
        case_id=req.case_id,
    )


# ---------------------------------------------------------------------------
# OFAC SDN refresh — synchronous, transactional, audited
# ---------------------------------------------------------------------------


@router.post("/ofac/refresh", response_model=RefreshResponse)
async def refresh_ofac_sdn(
    auth: AuthContext = Depends(get_current_user),
) -> RefreshResponse:
    """
    Refresh OFAC SDN data.

    Downloads the SDN + ALT CSV files from Treasury.gov, parses them fully,
    then upserts into Supabase. The download + parse step happens BEFORE any
    DB writes — if the download fails, existing data is preserved.

    Logs a row in ofac_refresh_log for audit trail.
    """
    if not settings.supabase_url or not settings.supabase_service_key:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    # ── Phase 1: download + parse (no DB writes yet) ──────────────────
    try:
        logger.info(
            "ofac_refresh: downloading SDN CSV from %s (triggered_by=%s)",
            SDN_CSV_URL,
            auth.user_id,
        )
        sdn_raw = await download_sdn_csv(SDN_CSV_URL)
        alt_raw = await download_sdn_csv(ALT_CSV_URL)
    except Exception as exc:
        logger.error("ofac_refresh: download failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to download OFAC SDN data from Treasury: {exc}",
        )

    try:
        sdn_entries = parse_sdn_csv(sdn_raw)
        alt_entries = parse_alt_csv(alt_raw)
    except Exception as exc:
        logger.error("ofac_refresh: CSV parse failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to parse OFAC SDN CSV: {exc}",
        )

    if len(sdn_entries) == 0:
        raise HTTPException(
            status_code=502,
            detail="OFAC SDN CSV parsed but contained zero entries — aborting to protect existing data",
        )

    logger.info(
        "ofac_refresh: parsed %d SDN entries, %d alternates — proceeding to DB load",
        len(sdn_entries),
        len(alt_entries),
    )

    # ── Phase 2: upsert into DB ──────────────────────────────────────
    try:
        counts = await load_sdn_to_db(
            settings.supabase_url,
            settings.supabase_service_key,
            sdn_entries,
            alt_entries,
        )
    except Exception as exc:
        logger.error("ofac_refresh: DB load failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to load OFAC SDN data into database: {exc}",
        )

    entries_loaded = counts.get("entries", 0)
    alts_loaded = counts.get("alternates", 0)
    logger.info(
        "ofac_refresh: loaded %d entries, %d alternates into DB",
        entries_loaded,
        alts_loaded,
    )

    # ── Phase 3: audit log ───────────────────────────────────────────
    try:
        db = await get_service_db()
        await db.table("ofac_refresh_log").insert(
            {
                "entries_count": entries_loaded,
                "alternates_count": alts_loaded,
                "source_url": SDN_CSV_URL,
                "triggered_by": auth.user_id,
            }
        ).execute()
    except Exception as exc:
        logger.warning("ofac_refresh: failed to write audit log: %s", exc)

    return RefreshResponse(
        status="completed",
        message=f"OFAC SDN refresh complete: {entries_loaded} entries, {alts_loaded} alternates loaded.",
        entries_count=entries_loaded,
        alternates_count=alts_loaded,
    )


# ---------------------------------------------------------------------------
# OFAC SDN status — staleness + health reporting
# ---------------------------------------------------------------------------

STALENESS_THRESHOLD_HOURS = 168.0  # 7 days


@router.get("/ofac/status", response_model=OfacStatusResponse)
async def ofac_status(
    auth: AuthContext = Depends(get_current_user),
) -> OfacStatusResponse:
    """
    OFAC SDN health check: row counts, last refresh timestamp, staleness.

    is_stale is true when data hasn't been refreshed in 7+ days.
    is_empty is true when the entries table has zero rows (critical).
    """
    if not settings.supabase_url or not settings.supabase_service_key:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    db = await get_service_db()

    entries_result = await (
        db.table("ofac_sdn_entries")
        .select("id", count="exact")
        .limit(0)
        .execute()
    )
    entries_count = entries_result.count or 0

    alts_result = await (
        db.table("ofac_sdn_alternates")
        .select("id", count="exact")
        .limit(0)
        .execute()
    )
    alternates_count = alts_result.count or 0

    # Get last refresh from the refresh log (most recent)
    last_refresh_result = await (
        db.table("ofac_refresh_log")
        .select("refreshed_at")
        .order("refreshed_at", desc=True)
        .limit(1)
        .execute()
    )

    last_refreshed_at: str | None = None
    staleness_hours: float | None = None
    is_stale = True  # Default to stale if no refresh data

    if last_refresh_result.data:
        last_refreshed_at = last_refresh_result.data[0]["refreshed_at"]
        refreshed_dt = datetime.fromisoformat(last_refreshed_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        staleness_hours = (now - refreshed_dt).total_seconds() / 3600.0
        is_stale = staleness_hours > STALENESS_THRESHOLD_HOURS

    return OfacStatusResponse(
        entries_count=entries_count,
        alternates_count=alternates_count,
        last_refreshed_at=last_refreshed_at,
        staleness_hours=round(staleness_hours, 2) if staleness_hours is not None else None,
        is_stale=is_stale,
        is_empty=entries_count == 0,
    )
