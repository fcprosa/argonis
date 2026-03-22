"""
Case endpoints.

GET /cases/{id}  — Case + all evidence (steps, screening, narratives, links)
GET /cases       — List cases for the organisation
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import AuthContext, get_current_user
from app.db import get_service_db
from app.ratelimit import rate_limit

router = APIRouter(prefix="/cases", tags=["cases"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CaseDetailResponse(BaseModel):
    """Full case payload with all related evidence."""

    case: dict[str, Any]
    investigation_steps: list[dict[str, Any]]
    screening_results: list[dict[str, Any]]
    narratives: list[dict[str, Any]]
    evidence_links: list[dict[str, Any]]


class CaseSummary(BaseModel):
    id: str
    organization_id: str
    alert_id: str | None = None
    title: str
    description: str | None = None
    status: str
    assigned_to: str | None = None
    created_by: str
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{case_id}", response_model=CaseDetailResponse)
async def get_case(
    case_id: str,
    auth: AuthContext = Depends(get_current_user),
    _rl: None = Depends(rate_limit(120, 60)),
) -> CaseDetailResponse:
    """
    Get a case with **all** associated evidence.

    Returns:
      - ``case`` — the case record
      - ``investigation_steps`` — parse / gather / screen / analyze results
      - ``screening_results`` — OFAC, OpenSanctions hits
      - ``narratives`` — each with embedded ``narrative_sections``
      - ``evidence_links`` — citation mappings for the narratives
    """
    db = await get_service_db()

    # --- Case itself ---
    try:
        case_result = await (
            db.table("cases")
            .select("*")
            .eq("id", case_id)
            .eq("organization_id", auth.organization_id)
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Case not found")

    # --- Investigation steps ---
    steps_result = await (
        db.table("investigation_steps")
        .select("*")
        .eq("case_id", case_id)
        .eq("organization_id", auth.organization_id)
        .order("created_at")
        .execute()
    )

    # --- Screening results ---
    screening_result = await (
        db.table("screening_results")
        .select("*")
        .eq("case_id", case_id)
        .eq("organization_id", auth.organization_id)
        .order("match_confidence", desc=True)
        .execute()
    )

    # --- Narratives (with sections embedded via PostgREST join) ---
    narratives_result = await (
        db.table("narratives")
        .select("*, narrative_sections(*)")
        .eq("case_id", case_id)
        .eq("organization_id", auth.organization_id)
        .order("version", desc=True)
        .execute()
    )

    # --- Evidence links for all narratives ---
    narrative_ids = [n["id"] for n in (narratives_result.data or [])]
    evidence_links: list[dict[str, Any]] = []
    if narrative_ids:
        el_result = await (
            db.table("evidence_links")
            .select("*")
            .in_("narrative_id", narrative_ids)
            .eq("organization_id", auth.organization_id)
            .execute()
        )
        evidence_links = el_result.data or []

    return CaseDetailResponse(
        case=case_result.data,
        investigation_steps=steps_result.data or [],
        screening_results=screening_result.data or [],
        narratives=narratives_result.data or [],
        evidence_links=evidence_links,
    )


@router.get("", response_model=list[CaseSummary])
async def list_cases(
    auth: AuthContext = Depends(get_current_user),
    _rl: None = Depends(rate_limit(60, 60)),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(open|in_review|escalated|closed)$",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[CaseSummary]:
    """List cases for the current organisation."""
    db = await get_service_db()

    query = (
        db.table("cases")
        .select("*")
        .eq("organization_id", auth.organization_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if status_filter:
        query = query.eq("status", status_filter)

    result = await query.execute()
    return [CaseSummary(**r) for r in (result.data or [])]
