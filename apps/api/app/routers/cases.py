"""
Case endpoints.

GET /cases/{id}  — Case + all evidence (steps, screening, narratives, links)
GET /cases       — List cases for the organisation
"""

from __future__ import annotations

from decimal import Decimal
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
    risk_score: float | None = None
    recommended_action: str | None = None


class CaseMetadataResponse(BaseModel):
    duration_s: float
    cost_usd: float
    model: str
    total_stripped_citations: int
    coverage_gaps: list[str]
    data_gaps: list[str]


async def _screening_flags_for_case(
    db: Any, case_id: str, organization_id: str
) -> tuple[bool, list[str]]:
    res = await (
        db.table("investigation_steps")
        .select("status, source_data")
        .eq("case_id", case_id)
        .eq("organization_id", organization_id)
        .eq("name", "screen")
        .limit(1)
        .execute()
    )
    if not res.data:
        return False, []
    step = res.data[0]
    if step.get("status") != "completed_with_warnings":
        return False, []
    src = step.get("source_data") or {}
    gaps = src.get("coverage_gaps") or []
    if isinstance(gaps, list):
        return True, [str(x) for x in gaps]
    return True, []


async def _latest_analyze_risk_by_case(
    db: Any, organization_id: str, case_ids: list[str]
) -> dict[str, tuple[float | None, str | None]]:
    """Map case_id → (overall_risk_score, recommended_action) from latest analyze step."""
    if not case_ids:
        return {}
    res = await (
        db.table("investigation_steps")
        .select("case_id, confidence_score, source_data, created_at")
        .eq("organization_id", organization_id)
        .eq("name", "analyze")
        .in_("case_id", case_ids)
        .execute()
    )
    best: dict[str, dict[str, Any]] = {}
    for row in res.data or []:
        cid = str(row["case_id"])
        prev = best.get(cid)
        t_new = str(row.get("created_at") or "")
        if prev is None or t_new > str(prev.get("created_at") or ""):
            best[cid] = row
    out: dict[str, tuple[float | None, str | None]] = {}
    for cid, row in best.items():
        sd = row.get("source_data") or {}
        raw_score = row.get("confidence_score")
        if raw_score is None:
            raw_score = sd.get("overall_risk_score")
        risk: float | None
        if raw_score is None:
            risk = None
        else:
            risk = float(raw_score)
        action = sd.get("recommended_action")
        act_str = action if isinstance(action, str) else None
        out[cid] = (risk, act_str)
    return out


async def _gather_data_gaps(db: Any, case_id: str, organization_id: str) -> list[str]:
    res = await (
        db.table("investigation_steps")
        .select("source_data")
        .eq("case_id", case_id)
        .eq("organization_id", organization_id)
        .eq("name", "gather")
        .limit(1)
        .execute()
    )
    if not res.data:
        return []
    src = res.data[0].get("source_data") or {}
    gaps = src.get("data_gaps") or []
    if isinstance(gaps, list):
        return [str(x) for x in gaps]
    return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{case_id}/metadata", response_model=CaseMetadataResponse)
async def get_case_metadata(
    case_id: str,
    auth: AuthContext = Depends(get_current_user),
    _rl: None = Depends(rate_limit(120, 60)),
) -> CaseMetadataResponse:
    """Aggregate LLM usage, firewall strip counts, and screening/gather gaps."""
    db = await get_service_db()
    try:
        await (
            db.table("cases")
            .select("id")
            .eq("id", case_id)
            .eq("organization_id", auth.organization_id)
            .single()
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc

    llm_res = await (
        db.table("llm_usage_log")
        .select("cost_usd, duration_ms, model, created_at")
        .eq("case_id", case_id)
        .eq("organization_id", auth.organization_id)
        .order("created_at")
        .execute()
    )
    rows = llm_res.data or []
    cost = Decimal("0")
    duration_ms_total = 0
    model = "unknown"
    for row in rows:
        cost += Decimal(str(row.get("cost_usd") or "0"))
        duration_ms_total += int(row.get("duration_ms") or 0)
        if row.get("model"):
            model = str(row["model"])

    fw_res = await (
        db.table("firewall_strip_log")
        .select("stripped_count")
        .eq("case_id", case_id)
        .execute()
    )
    stripped = sum(int(r.get("stripped_count") or 0) for r in (fw_res.data or []))

    is_partial, coverage_gaps = await _screening_flags_for_case(
        db, case_id, auth.organization_id
    )
    data_gaps = await _gather_data_gaps(db, case_id, auth.organization_id)

    return CaseMetadataResponse(
        duration_s=duration_ms_total / 1000.0,
        cost_usd=float(cost),
        model=model,
        total_stripped_citations=stripped,
        coverage_gaps=coverage_gaps,
        data_gaps=data_gaps,
    )


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

    is_partial, gaps = await _screening_flags_for_case(
        db, case_id, auth.organization_id
    )
    narratives_out: list[dict[str, Any]] = []
    for nar in narratives_result.data or []:
        row = dict(nar)
        row["is_partial_screening"] = is_partial
        row["screening_gaps"] = list(gaps)
        narratives_out.append(row)

    return CaseDetailResponse(
        case=case_result.data,
        investigation_steps=steps_result.data or [],
        screening_results=screening_result.data or [],
        narratives=narratives_out,
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
    rows = result.data or []
    case_ids = [str(r["id"]) for r in rows]
    risk_map = await _latest_analyze_risk_by_case(db, auth.organization_id, case_ids)
    summaries: list[CaseSummary] = []
    for r in rows:
        cid = str(r["id"])
        risk_score, recommended_action = risk_map.get(cid, (None, None))
        summaries.append(
            CaseSummary(
                **r,
                risk_score=risk_score,
                recommended_action=recommended_action,
            )
        )
    return summaries
