"""
Investigation endpoint.

POST /investigate — Run the full evidence-first investigation pipeline.

RATE LIMITS (battle plan rule — "$500 in Claude credits in minutes"):
  • 10 investigations / minute / user
  • 100 investigations / hour / user
  • 500 investigations / day / organization

ANTI-ERROR: An errant loop calling /investigate burns $500 in Claude credits
in minutes. This is the most aggressively rate-limited endpoint in the system.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_user
from app.config import settings
from app.db import get_service_db
from app.middleware.rate_limit import (
    INVESTIGATE_ORG_DAY,
    INVESTIGATE_USER_HOUR,
    INVESTIGATE_USER_MINUTE,
    get_org_key,
    get_user_key,
    limiter,
)
from app.services.persist_investigation import persist_pipeline_result

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/investigate", tags=["investigations"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class InvestigateRequest(BaseModel):
    """Provide EITHER ``alert_id`` (existing alert) OR ``alert_data`` (raw)."""

    alert_id: str | None = Field(
        default=None, description="ID of an existing alert to investigate"
    )
    alert_data: dict[str, Any] | None = Field(
        default=None, description="Raw alert payload to investigate"
    )


class InvestigateResponse(BaseModel):
    case_id: str
    alert_id: str
    status: str  # "investigating"
    message: str


# ---------------------------------------------------------------------------
# Background task — runs the 5-step pipeline and persists results
# ---------------------------------------------------------------------------


async def _run_pipeline_background(
    case_id: str,
    alert_data: dict[str, Any],
    organization_id: str,
    user_id: str,
) -> None:
    """Execute the evidence pipeline and store every artefact in the DB."""
    from app.pipeline.core import EvidencePipeline

    db = await get_service_db()

    try:
        # Mark case as actively being processed
        await (
            db.table("cases")
            .update({"status": "in_review"})
            .eq("id", case_id)
            .execute()
        )

        # --- Run the full 5-step pipeline ---
        pipeline = EvidencePipeline(
            api_key=settings.anthropic_api_key or None,
            supabase_url=settings.supabase_url,
            supabase_key=settings.supabase_service_key,
            opensanctions_api_key=settings.opensanctions_api_key,
            serper_api_key=settings.serper_api_key,
        )
        result = await pipeline.run(alert_data)

        # --- Pipeline halted (e.g. empty OFAC SDN tables) -------------
        if result.halted:
            error_msgs = "; ".join(e.error_message for e in result.step_errors)
            logger.error("Pipeline halted for case %s: %s", case_id, error_msgs)

            failed_steps = [
                {
                    "organization_id": organization_id,
                    "case_id": case_id,
                    "name": "parse",
                    "description": "Parsed alert into structured data",
                    "status": "completed",
                    "source_data": result.parsed_alert.model_dump(mode="json"),
                    "confidence_score": 1.0,
                    "created_by": user_id,
                },
                {
                    "organization_id": organization_id,
                    "case_id": case_id,
                    "name": "gather",
                    "description": "Gathered KYC profiles, relationships, history",
                    "status": "completed",
                    "source_data": result.gathered_data.model_dump(mode="json"),
                    "confidence_score": 1.0,
                    "created_by": user_id,
                },
            ]
            for step_err in result.step_errors:
                failed_steps.append(
                    {
                        "organization_id": organization_id,
                        "case_id": case_id,
                        "name": step_err.step_name,
                        "description": step_err.error_message[:500],
                        "status": "failed",
                        "created_by": user_id,
                    }
                )
            await db.table("investigation_steps").insert(failed_steps).execute()
            await (
                db.table("cases")
                .update(
                    {
                        "status": "open",
                        "description": f"Pipeline halted: {error_msgs}"[:500],
                    }
                )
                .eq("id", case_id)
                .execute()
            )
            return

        await persist_pipeline_result(
            case_id=case_id,
            organization_id=organization_id,
            user_id=user_id,
            result=result,
            db=db,
        )

    except Exception as exc:
        logger.error(
            "Pipeline failed for case %s: %s", case_id, exc, exc_info=True
        )
        try:
            await (
                db.table("cases")
                .update(
                    {
                        "status": "open",
                        "description": f"Pipeline failed: {exc}",
                    }
                )
                .eq("id", case_id)
                .execute()
            )
            await (
                db.table("investigation_steps")
                .insert(
                    {
                        "organization_id": organization_id,
                        "case_id": case_id,
                        "name": "pipeline_error",
                        "description": str(exc)[:500],
                        "status": "failed",
                        "created_by": user_id,
                    }
                )
                .execute()
            )
        except Exception as store_exc:
            logger.error("Failed to persist error state: %s", store_exc)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=InvestigateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(INVESTIGATE_USER_MINUTE, key_func=get_user_key)
@limiter.limit(INVESTIGATE_USER_HOUR, key_func=get_user_key)
@limiter.limit(INVESTIGATE_ORG_DAY, key_func=get_org_key)
async def investigate(
    request: Request,
    body: InvestigateRequest,
    background_tasks: BackgroundTasks,
    auth: AuthContext = Depends(get_current_user),
) -> InvestigateResponse:
    """
    Run the full evidence-first investigation pipeline.

    Creates a **case** and launches the 5-step pipeline in the background:

    1. PARSE   — structured data extraction
    2. GATHER  — KYC, relationships, history
    3. SCREEN  — OFAC SDN + OpenSanctions + adverse media
    4. ANALYZE — pattern detection (structuring, layering, …)
    5. NARRATE — Claude generates evidence-backed narrative

    Returns immediately with ``case_id``.
    Poll **GET /cases/{case_id}** for results.

    **Rate-limited: 10/min, 100/hour per user; 500/day per org.**
    """
    if not body.alert_id and not body.alert_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either alert_id or alert_data",
        )

    if not settings.supabase_url or not settings.supabase_service_key:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    db = await get_service_db()

    # --- Pre-flight: refuse to start if OFAC SDN tables are empty ------
    ofac_count = await (
        db.table("ofac_sdn_entries")
        .select("id", count="exact")
        .limit(0)
        .execute()
    )
    if (ofac_count.count or 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "OFAC SDN tables are empty — screening cannot proceed safely. "
                "Run POST /screening/ofac/refresh before starting investigations."
            ),
        )

    # --- Resolve or create the alert -----------------------------------
    if body.alert_id:
        try:
            alert_result = await (
                db.table("alerts")
                .select("*")
                .eq("id", body.alert_id)
                .eq("organization_id", auth.organization_id)
                .single()
                .execute()
            )
        except Exception:
            raise HTTPException(status_code=404, detail="Alert not found")

        raw = alert_result.data.get("raw_data")
        alert_data: dict[str, Any] = raw or alert_result.data
        alert_id = body.alert_id
    else:
        assert body.alert_data is not None  # guaranteed by earlier check
        alert_row = {
            "organization_id": auth.organization_id,
            "title": body.alert_data.get("alert_type", "Investigation"),
            "description": "Auto-created from /investigate endpoint",
            "source": "api",
            "raw_data": body.alert_data,
            "created_by": auth.user_id,
        }
        alert_result = await db.table("alerts").insert(alert_row).execute()
        if not alert_result.data:
            raise HTTPException(status_code=500, detail="Failed to create alert")
        alert_id = alert_result.data[0]["id"]
        alert_data = body.alert_data

    # --- Create case ---------------------------------------------------
    case_row = {
        "organization_id": auth.organization_id,
        "alert_id": alert_id,
        "title": (
            f"Investigation: "
            f"{alert_data.get('alert_type', 'Unknown')} — "
            f"{alert_data.get('account_holder', 'Unknown')}"
        ),
        "description": "Pipeline running…",
        "status": "open",
        "assigned_to": auth.user_id,
        "created_by": auth.user_id,
    }
    case_result = await db.table("cases").insert(case_row).execute()
    if not case_result.data:
        raise HTTPException(status_code=500, detail="Failed to create case")

    case_id: str = case_result.data[0]["id"]

    # --- Kick off pipeline in background -------------------------------
    background_tasks.add_task(
        _run_pipeline_background,
        case_id=case_id,
        alert_data=alert_data,
        organization_id=auth.organization_id,
        user_id=auth.user_id,
    )

    logger.info(
        "Investigation queued: case=%s alert=%s user=%s",
        case_id,
        alert_id,
        auth.user_id,
    )

    return InvestigateResponse(
        case_id=case_id,
        alert_id=alert_id,
        status="investigating",
        message="Pipeline started. Poll GET /cases/{case_id} for results.",
    )
