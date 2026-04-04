"""
Alert endpoints.

POST /alerts        — Create a single alert (raw, for system use)
POST /alerts/batch  — Batch import from CSV: creates cases directly
GET  /alerts/{id}   — Get a single alert
GET  /alerts        — List alerts

All endpoints require Supabase JWT auth. All actions logged via DB triggers.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_user
from app.db import get_service_db
from app.ratelimit import rate_limit

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AlertCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    source: str = Field(min_length=1, max_length=200)
    raw_data: dict[str, Any] | None = None


class AlertResponse(BaseModel):
    id: str
    organization_id: str
    title: str
    description: str | None = None
    status: str
    severity: str
    source: str
    raw_data: dict[str, Any] | None = None
    created_by: str | None = None
    created_at: str
    updated_at: str


# Batch import schema — maps to what the CSV upload page sends.
# Each item becomes a case row (not an alert row) so it appears in
# the Alert Queue immediately after import.
class AlertImport(BaseModel):
    customer_name: str = Field(min_length=1, max_length=300)
    alert_type: str = Field(min_length=1, max_length=200)
    risk_score: float | None = Field(default=None, ge=0.0, le=1.0)
    status: str | None = Field(
        default=None, pattern="^(open|in_review|escalated|closed)$"
    )
    created_at: str | None = None  # ISO 8601; omit to use DB default (NOW())
    case_id: str | None = None  # external reference (e.g. "AML-2026-00201")


class AlertBatchImport(BaseModel):
    alerts: list[AlertImport] = Field(min_length=1, max_length=100)


class BatchImportResponse(BaseModel):
    imported: int
    case_ids: list[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: AlertCreate,
    auth: AuthContext = Depends(get_current_user),
    _rl: None = Depends(rate_limit(30, 60)),
) -> AlertResponse:
    """Create a single alert."""
    db = await get_service_db()

    row = {
        "organization_id": auth.organization_id,
        "title": body.title,
        "description": body.description,
        "severity": body.severity,
        "source": body.source,
        "raw_data": body.raw_data,
        "created_by": auth.user_id,
    }

    result = await db.table("alerts").insert(row).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create alert")

    return AlertResponse.model_validate(result.data[0])


@router.post(
    "/batch",
    response_model=BatchImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def batch_import_alerts(
    body: AlertBatchImport,
    auth: AuthContext = Depends(get_current_user),
    _rl: None = Depends(rate_limit(10, 60)),
) -> BatchImportResponse:
    """
    Batch import alerts from CSV upload.

    Each item is inserted as a ``cases`` row so it appears in the Alert Queue
    immediately.  The optional ``case_id`` field is treated as an external
    reference (e.g. "AML-2026-00201") and stored in the case description.
    When not supplied, a sequential ``CASE-NNN`` reference is generated using
    the org's current case count as the base.
    """
    db = await get_service_db()

    # Count existing cases for this org so generated refs don't collide.
    count_res = await (
        db.table("cases")
        .select("id", count="exact")  # type: ignore[call-arg]
        .eq("organization_id", auth.organization_id)
        .execute()
    )
    base = (count_res.count or 0) + 1

    rows: list[dict[str, Any]] = []
    for i, alert in enumerate(body.alerts):
        ext_ref = alert.case_id or f"CASE-{base + i:03d}"

        # Title follows the same convention as investigation-generated cases.
        title = f"Investigation: {alert.alert_type} — {alert.customer_name}"

        # Pack the external ref and risk score into description so they survive
        # without a schema change.  Format: "[EXT-REF] | score: 0.92"
        desc_parts: list[str] = [f"[{ext_ref}]"]
        if alert.risk_score is not None:
            desc_parts.append(f"score {alert.risk_score:.2f}")

        row: dict[str, Any] = {
            "organization_id": auth.organization_id,
            "title": title,
            "description": " | ".join(desc_parts),
            "status": alert.status or "open",
            "created_by": auth.user_id,
        }
        if alert.created_at:
            row["created_at"] = alert.created_at

        rows.append(row)

    result = await db.table("cases").insert(rows).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to import alerts")

    data: list[dict[str, Any]] = result.data  # type: ignore[assignment]
    case_ids = [str(r["id"]) for r in data]
    return BatchImportResponse(imported=len(case_ids), case_ids=case_ids)


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: str,
    auth: AuthContext = Depends(get_current_user),
    _rl: None = Depends(rate_limit(120, 60)),
) -> AlertResponse:
    """Get a single alert by ID."""
    db = await get_service_db()

    try:
        result = await (
            db.table("alerts")
            .select("*")
            .eq("id", alert_id)
            .eq("organization_id", auth.organization_id)
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert_data: dict[str, Any] = result.data  # type: ignore[assignment]
    return AlertResponse.model_validate(alert_data)


@router.get("", response_model=list[AlertResponse])
async def list_alerts(
    auth: AuthContext = Depends(get_current_user),
    _rl: None = Depends(rate_limit(60, 60)),
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(new|reviewing|escalated|closed)$"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AlertResponse]:
    """List alerts for the current organization."""
    db = await get_service_db()

    query = (
        db.table("alerts")
        .select("*")
        .eq("organization_id", auth.organization_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if status_filter:
        query = query.eq("status", status_filter)

    result = await query.execute()
    rows: list[dict[str, Any]] = result.data or []  # type: ignore[assignment]
    return [AlertResponse.model_validate(r) for r in rows]
