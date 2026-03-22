"""
Alert endpoints.

POST /alerts        — Create a single alert
POST /alerts/batch  — Batch upload alerts (max 100)
GET  /alerts/{id}   — Get a single alert

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
    severity: str = Field(
        default="medium", pattern="^(low|medium|high|critical)$"
    )
    source: str = Field(min_length=1, max_length=200)
    raw_data: dict[str, Any] | None = None


class AlertBatchCreate(BaseModel):
    alerts: list[AlertCreate] = Field(min_length=1, max_length=100)


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

    return AlertResponse(**result.data[0])


@router.post(
    "/batch",
    response_model=list[AlertResponse],
    status_code=status.HTTP_201_CREATED,
)
async def batch_create_alerts(
    body: AlertBatchCreate,
    auth: AuthContext = Depends(get_current_user),
    _rl: None = Depends(rate_limit(10, 60)),
) -> list[AlertResponse]:
    """Batch upload alerts (max 100 per request)."""
    db = await get_service_db()

    rows = [
        {
            "organization_id": auth.organization_id,
            "title": a.title,
            "description": a.description,
            "severity": a.severity,
            "source": a.source,
            "raw_data": a.raw_data,
            "created_by": auth.user_id,
        }
        for a in body.alerts
    ]

    result = await db.table("alerts").insert(rows).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create alerts")

    return [AlertResponse(**r) for r in result.data]


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

    return AlertResponse(**result.data)


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
    return [AlertResponse(**r) for r in (result.data or [])]
