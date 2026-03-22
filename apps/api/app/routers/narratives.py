"""
Narrative endpoints.

GET  /narratives/{id}                     — Narrative + sections + evidence links
PUT  /narratives/{id}/sections/{section}  — Edit a specific section
POST /narratives/{id}/approve             — Per-section approval (reviewers only)
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_user, require_role
from app.db import get_service_db
from app.ratelimit import rate_limit

router = APIRouter(prefix="/narratives", tags=["narratives"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SectionResponse(BaseModel):
    id: str
    section_key: str
    title: str
    content: str
    order_index: int
    approval_status: str
    approved_by: str | None = None
    approved_at: str | None = None


class NarrativeDetailResponse(BaseModel):
    id: str
    case_id: str
    version: int
    title: str
    status: str
    sections: list[SectionResponse]
    evidence_links: list[dict]
    created_by: str
    created_at: str
    updated_at: str


class SectionEditRequest(BaseModel):
    content: str = Field(min_length=0, description="New section content")
    title: str | None = Field(
        default=None, description="Optionally update the section title"
    )


class SectionApprovalRequest(BaseModel):
    """Per-section approval payload."""

    section_keys: list[str] = Field(
        min_length=1, description="Section keys to approve/reject"
    )
    action: str = Field(
        pattern="^(approve|reject)$", description="'approve' or 'reject'"
    )
    comment: str | None = Field(
        default=None, description="Optional reviewer comment"
    )


class ApprovalResponse(BaseModel):
    narrative_id: str
    narrative_status: str
    sections_updated: list[str]
    message: str


# ---------------------------------------------------------------------------
# GET  /narratives/{id}
# ---------------------------------------------------------------------------


@router.get("/{narrative_id}", response_model=NarrativeDetailResponse)
async def get_narrative(
    narrative_id: str,
    auth: AuthContext = Depends(get_current_user),
    _rl: None = Depends(rate_limit(120, 60)),
) -> NarrativeDetailResponse:
    """
    Get a narrative with all its sections and evidence links.

    Each section includes:
      - ``content`` (prose with inline ``[EVID-XXX]`` citations)
      - ``approval_status`` (pending | approved | rejected)

    Evidence links map each ``[EVID-XXX]`` citation to a source record.
    """
    db = await get_service_db()

    # --- Narrative ---
    try:
        nar = await (
            db.table("narratives")
            .select("*")
            .eq("id", narrative_id)
            .eq("organization_id", auth.organization_id)
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Narrative not found")

    # --- Sections ---
    sections_result = await (
        db.table("narrative_sections")
        .select("*")
        .eq("narrative_id", narrative_id)
        .eq("organization_id", auth.organization_id)
        .order("order_index")
        .execute()
    )

    # --- Evidence links ---
    el_result = await (
        db.table("evidence_links")
        .select("*")
        .eq("narrative_id", narrative_id)
        .eq("organization_id", auth.organization_id)
        .execute()
    )

    sections = [
        SectionResponse(
            id=s["id"],
            section_key=s["section_key"],
            title=s["title"],
            content=s["content"],
            order_index=s["order_index"],
            approval_status=s["approval_status"],
            approved_by=s.get("approved_by"),
            approved_at=s.get("approved_at"),
        )
        for s in (sections_result.data or [])
    ]

    n = nar.data
    return NarrativeDetailResponse(
        id=n["id"],
        case_id=n["case_id"],
        version=n["version"],
        title=n["title"],
        status=n["status"],
        sections=sections,
        evidence_links=el_result.data or [],
        created_by=n["created_by"],
        created_at=n["created_at"],
        updated_at=n["updated_at"],
    )


# ---------------------------------------------------------------------------
# PUT  /narratives/{id}/sections/{section}
# ---------------------------------------------------------------------------


@router.put(
    "/{narrative_id}/sections/{section_key}",
    response_model=SectionResponse,
)
async def edit_section(
    narrative_id: str,
    section_key: str,
    body: SectionEditRequest,
    auth: AuthContext = Depends(get_current_user),
    _rl: None = Depends(rate_limit(30, 60)),
) -> SectionResponse:
    """
    Edit a specific narrative section.

    Only allowed on narratives in ``draft`` or ``in_review`` status.
    Editing **resets** the section's ``approval_status`` to ``pending``.
    """
    db = await get_service_db()

    # Verify narrative exists and is editable
    try:
        nar = await (
            db.table("narratives")
            .select("id, status, organization_id")
            .eq("id", narrative_id)
            .eq("organization_id", auth.organization_id)
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Narrative not found")

    if nar.data["status"] == "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot edit an approved narrative. Create a new version.",
        )

    # Update the section — reset approval on edit
    update_data: dict = {
        "content": body.content,
        "approval_status": "pending",
    }
    if body.title is not None:
        update_data["title"] = body.title

    section_result = await (
        db.table("narrative_sections")
        .update(update_data)
        .eq("narrative_id", narrative_id)
        .eq("section_key", section_key)
        .eq("organization_id", auth.organization_id)
        .execute()
    )

    if not section_result.data:
        raise HTTPException(
            status_code=404, detail=f"Section '{section_key}' not found"
        )

    s = section_result.data[0]
    return SectionResponse(
        id=s["id"],
        section_key=s["section_key"],
        title=s["title"],
        content=s["content"],
        order_index=s["order_index"],
        approval_status=s["approval_status"],
        approved_by=s.get("approved_by"),
        approved_at=s.get("approved_at"),
    )


# ---------------------------------------------------------------------------
# POST /narratives/{id}/approve
# ---------------------------------------------------------------------------


@router.post("/{narrative_id}/approve", response_model=ApprovalResponse)
async def approve_narrative(
    narrative_id: str,
    body: SectionApprovalRequest,
    auth: AuthContext = Depends(require_role("admin", "reviewer")),
    _rl: None = Depends(rate_limit(30, 60)),
) -> ApprovalResponse:
    """
    Approve or reject narrative sections (reviewers and admins only).

    Workflow:
      - When **all** sections are approved → narrative status → ``approved``
      - When **any** section is rejected → narrative status → ``rejected``
      - Otherwise → ``in_review``
    """
    db = await get_service_db()

    # Verify narrative exists
    try:
        await (
            db.table("narratives")
            .select("id")
            .eq("id", narrative_id)
            .eq("organization_id", auth.organization_id)
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Narrative not found")

    # Update each requested section
    now_iso = datetime.now(timezone.utc).isoformat()
    updated_keys: list[str] = []

    for key in body.section_keys:
        update_data = {
            "approval_status": (
                "approved" if body.action == "approve" else "rejected"
            ),
            "approved_by": auth.user_id,
            "approved_at": now_iso,
        }

        result = await (
            db.table("narrative_sections")
            .update(update_data)
            .eq("narrative_id", narrative_id)
            .eq("section_key", key)
            .eq("organization_id", auth.organization_id)
            .execute()
        )
        if result.data:
            updated_keys.append(key)

    if not updated_keys:
        raise HTTPException(
            status_code=404, detail="No matching sections found"
        )

    # --- Derive overall narrative status from sections ---
    all_sections = await (
        db.table("narrative_sections")
        .select("approval_status")
        .eq("narrative_id", narrative_id)
        .execute()
    )

    statuses = [s["approval_status"] for s in (all_sections.data or [])]

    if all(s == "approved" for s in statuses):
        narrative_status = "approved"
    elif any(s == "rejected" for s in statuses):
        narrative_status = "rejected"
    elif any(s == "approved" for s in statuses):
        narrative_status = "in_review"
    else:
        narrative_status = "draft"

    await (
        db.table("narratives")
        .update({"status": narrative_status})
        .eq("id", narrative_id)
        .execute()
    )

    return ApprovalResponse(
        narrative_id=narrative_id,
        narrative_status=narrative_status,
        sections_updated=updated_keys,
        message=(
            f"{len(updated_keys)} section(s) {body.action}d. "
            f"Narrative status: {narrative_status}."
        ),
    )
