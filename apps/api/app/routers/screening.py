"""
Screening API endpoints.

Endpoints:
  POST /screening/screen          — Screen a single name
  POST /screening/batch           — Batch screen multiple names
  POST /screening/adverse-media   — Search adverse media for a name
  POST /screening/ofac/refresh    — Refresh OFAC SDN data (cron endpoint)
  GET  /screening/ofac/status     — OFAC SDN metadata (last refresh, counts)
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.screening import (
    AdverseMediaResponse,
    ScreeningResponse,
    batch_screen,
    screen,
)
from app.screening.adverse_media import search_adverse_media
from app.screening.ofac import get_sdn_meta, refresh_sdn

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


@router.post("/ofac/refresh", response_model=RefreshResponse)
async def refresh_ofac_sdn(background_tasks: BackgroundTasks) -> RefreshResponse:
    """
    Trigger OFAC SDN data refresh.

    Downloads the latest SDN + ALT CSV files from Treasury.gov and
    reloads into Supabase. Call weekly via cron.

    This runs as a background task — returns immediately.
    """
    if not settings.supabase_url or not settings.supabase_service_key:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured",
        )

    background_tasks.add_task(
        refresh_sdn,
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_key,
    )

    return RefreshResponse(
        status="accepted",
        message="OFAC SDN refresh started in background. Check /screening/ofac/status for progress.",
    )


@router.get("/ofac/status")
async def ofac_status() -> dict:
    """
    Get OFAC SDN metadata: last refresh timestamp, entry counts.

    Use this to verify the SDN data is loaded and fresh.
    """
    if not settings.supabase_url or not settings.supabase_service_key:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    return await get_sdn_meta(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_key,
    )
