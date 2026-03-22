"""
Audit trail endpoint.

GET /audit/{case_id} — Full audit trail for a case and all related records.

The ``audit_log`` table is populated by PostgreSQL triggers on every
INSERT / UPDATE / DELETE across all business tables. This endpoint
aggregates the entries for a given case and everything linked to it:
investigation steps, screening results, narratives, sections, evidence links.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import AuthContext, get_current_user
from app.db import get_service_db
from app.ratelimit import rate_limit

router = APIRouter(prefix="/audit", tags=["audit"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AuditEntry(BaseModel):
    id: str
    user_id: str | None = None
    action: str
    table_name: str
    record_id: str
    old_data: dict[str, Any] | None = None
    new_data: dict[str, Any] | None = None
    created_at: str


class AuditTrailResponse(BaseModel):
    case_id: str
    entries: list[AuditEntry]
    total_count: int


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/{case_id}", response_model=AuditTrailResponse)
async def get_audit_trail(
    case_id: str,
    auth: AuthContext = Depends(get_current_user),
    _rl: None = Depends(rate_limit(60, 60)),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AuditTrailResponse:
    """
    Full audit trail for a case.

    Includes INSERT / UPDATE / DELETE events for the case itself **and**
    all related records (investigation steps, screening results, narratives,
    narrative sections, evidence links).

    Ordered by ``created_at DESC`` (most recent first).
    """
    db = await get_service_db()
    org_id = auth.organization_id

    # --- Verify the case belongs to this organisation ---
    try:
        await (
            db.table("cases")
            .select("id")
            .eq("id", case_id)
            .eq("organization_id", org_id)
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Case not found")

    # --- Collect all record IDs keyed by table name ---
    related: dict[str, list[str]] = {"cases": [case_id]}

    for table in ("investigation_steps", "screening_results", "narratives"):
        result = await (
            db.table(table)
            .select("id")
            .eq("case_id", case_id)
            .eq("organization_id", org_id)
            .execute()
        )
        related[table] = [r["id"] for r in (result.data or [])]

    # Sections and evidence_links hang off narratives
    narrative_ids = related.get("narratives", [])
    for sub_table in ("narrative_sections", "evidence_links"):
        ids: list[str] = []
        if narrative_ids:
            result = await (
                db.table(sub_table)
                .select("id")
                .in_("narrative_id", narrative_ids)
                .eq("organization_id", org_id)
                .execute()
            )
            ids = [r["id"] for r in (result.data or [])]
        related[sub_table] = ids

    # --- Query audit_log per table (one query per table) ---
    all_entries: list[dict[str, Any]] = []

    for table_name, record_ids in related.items():
        if not record_ids:
            continue
        audit_result = await (
            db.table("audit_log")
            .select("*")
            .eq("table_name", table_name)
            .in_("record_id", record_ids)
            .eq("organization_id", org_id)
            .order("created_at", desc=True)
            .execute()
        )
        all_entries.extend(audit_result.data or [])

    # --- Sort, paginate, return ---
    all_entries.sort(key=lambda e: e["created_at"], reverse=True)
    total_count = len(all_entries)
    page = all_entries[offset : offset + limit]

    return AuditTrailResponse(
        case_id=case_id,
        entries=[
            AuditEntry(
                id=e["id"],
                user_id=e.get("user_id"),
                action=e["action"],
                table_name=e["table_name"],
                record_id=e["record_id"],
                old_data=e.get("old_data"),
                new_data=e.get("new_data"),
                created_at=e["created_at"],
            )
            for e in page
        ],
        total_count=total_count,
    )
