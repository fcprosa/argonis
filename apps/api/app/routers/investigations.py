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
from app.services.pipeline_events import log_pipeline_event
from app.middleware.rate_limit import (
    INVESTIGATE_ORG_DAY,
    INVESTIGATE_USER_HOUR,
    INVESTIGATE_USER_MINUTE,
    get_org_key,
    get_user_key,
    limiter,
)

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

        # --- Store investigation steps --------------------------------
        screening_source_data = result.screening_bundle.model_dump(mode="json")
        if result.screening_bundle.coverage_gaps:
            screening_source_data["coverage_gaps"] = result.screening_bundle.coverage_gaps

        screen_status = (
            "completed_with_warnings"
            if result.screening_bundle.is_partial
            else "completed"
        )
        screen_desc = (
            f"Screened {len(result.screening_bundle.entity_names)} entities — "
            f"{len(result.screening_bundle.hits)} hits"
        )
        if result.screening_bundle.is_partial:
            screen_desc += " (PARTIAL — some sources unavailable)"

        steps_rows = [
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
            {
                "organization_id": organization_id,
                "case_id": case_id,
                "name": "screen",
                "description": screen_desc,
                "status": screen_status,
                "source_data": screening_source_data,
                "confidence_score": 1.0,
                "created_by": user_id,
            },
            {
                "organization_id": organization_id,
                "case_id": case_id,
                "name": "analyze",
                "description": (
                    f"Risk: {result.analysis_result.recommended_action} "
                    f"(score {result.analysis_result.overall_risk_score:.3f})"
                ),
                "status": "completed",
                "source_data": result.analysis_result.model_dump(mode="json"),
                "confidence_score": result.analysis_result.overall_risk_score,
                "created_by": user_id,
            },
        ]
        steps_result = await db.table("investigation_steps").insert(steps_rows).execute()
        # Build step-name → DB id map for evidence_links foreign keys
        step_id_map: dict[str, Any] = {
            row["name"]: row["id"] for row in (steps_result.data or [])  # type: ignore[index]
        }
        # Map pipeline source labels → step names
        source_to_step = {
            "step1_parse": "parse",
            "step2_gather": "gather",
            "step3_screen": "screen",
            "step4_analyze": "analyze",
        }

        # --- Pipeline event: partial screening coverage -----------------
        if result.screening_bundle.is_partial:
            await log_pipeline_event(
                db,
                organization_id=organization_id,
                case_id=case_id,
                user_id=user_id,
                event_type="screening_partial",
                message=(
                    f"Screening coverage was partial: "
                    f"{len(result.screening_bundle.coverage_gaps)} gap(s)"
                ),
                details={
                    "coverage_gaps": result.screening_bundle.coverage_gaps,
                    "sources_queried": result.screening_bundle.sources_queried,
                    "source_results": [
                        sr.model_dump(mode="json")
                        for sr in result.screening_bundle.source_results
                    ],
                },
            )

        # --- Store screening results ----------------------------------
        screening_rows = [
            {
                "organization_id": organization_id,
                "case_id": case_id,
                "entity_name": hit.entity_name,
                "match_confidence": float(hit.match_confidence),
                "source_url": hit.source_url,
                "match_data": {
                    "list_name": hit.list_name,
                    "match_type": hit.match_type,
                    "snippet": hit.snippet,
                },
                "status": "pending",
            }
            for hit in result.screening_bundle.hits
        ]
        if screening_rows:
            await db.table("screening_results").insert(screening_rows).execute()

        # --- Create narrative -----------------------------------------
        version_result = await (
            db.table("narratives")
            .select("version")
            .eq("case_id", case_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        next_version = (
            (version_result.data[0]["version"] + 1) if version_result.data else 1
        )

        narrative_row = {
            "organization_id": organization_id,
            "case_id": case_id,
            "version": next_version,
            "title": result.narrative.case_title,
            "status": "draft",
            "created_by": user_id,
        }
        narrative_result = await db.table("narratives").insert(narrative_row).execute()
        narrative_id = narrative_result.data[0]["id"]

        # --- Create narrative sections (content already firewall-cleaned) -
        section_rows = [
            {
                "organization_id": organization_id,
                "narrative_id": narrative_id,
                "section_key": section.section_key,
                "title": section.title,
                "content": section.content,
                "order_index": idx,
                "approval_status": "pending",
            }
            for idx, section in enumerate(result.narrative.sections)
        ]
        section_id_map: dict[str, str] = {}
        if section_rows:
            section_result = await (
                db.table("narrative_sections").insert(section_rows).execute()
            )
            section_id_map = {
                row["section_key"]: row["id"]
                for row in (section_result.data or [])
            }

        # --- Evidence links: ONLY for IDs kept by the firewall --------
        evidence_by_id = {item.id: item for item in result.evidence_items}
        evidence_link_rows = []
        for fw in result.firewall_results:
            section_id = section_id_map.get(fw.section_key)
            if not section_id:
                continue
            for evid_id in fw.kept_ids:
                item = evidence_by_id.get(evid_id)
                if not item:
                    continue
                step_name = source_to_step.get(item.source)
                step_id = step_id_map.get(step_name) if step_name else None
                if step_id is None:
                    step_id = step_id_map.get("analyze")
                if step_id is None:
                    continue
                evidence_link_rows.append(
                    {
                        "organization_id": organization_id,
                        "narrative_id": narrative_id,
                        "section_id": section_id,
                        "sentence_text": (
                            f"[{item.category.upper()}] "
                            f"{item.description}: {item.value}"
                        )[:500],
                        "source_type": "investigation_step",
                        "investigation_step_id": step_id,
                        "evidence_ref": item.id,
                        "source_data": item.model_dump(mode="json"),
                        "created_by": user_id,
                    }
                )
        if evidence_link_rows:
            await db.table("evidence_links").insert(evidence_link_rows).execute()
        logger.info(
            "Stored %d evidence links for narrative=%s",
            len(evidence_link_rows),
            narrative_id,
        )

        # --- Firewall strip log (always written, even when strip_rate=0) -
        strip_log_rows = []
        for fw in result.firewall_results:
            section_id = section_id_map.get(fw.section_key)
            if not section_id:
                continue
            strip_log_rows.append(
                {
                    "case_id": case_id,
                    "section_id": section_id,
                    "stripped_evidence_ids": fw.stripped_ids,
                    "stripped_count": len(fw.stripped_ids),
                    "total_cited_count": len(fw.kept_ids) + len(fw.stripped_ids),
                }
            )
        if strip_log_rows:
            await db.table("firewall_strip_log").insert(strip_log_rows).execute()

        # --- Firewall anomaly logging ---------------------------------
        for fw in result.firewall_results:
            if fw.strip_rate > 0.2:
                logger.warning(
                    "Firewall high strip rate: case_id=%s section=%s "
                    "strip_rate=%.2f stripped_count=%d stripped_ids=%s",
                    case_id,
                    fw.section_key,
                    fw.strip_rate,
                    len(fw.stripped_ids),
                    fw.stripped_ids,
                )
        total_kept = sum(len(fw.kept_ids) for fw in result.firewall_results)
        total_stripped = sum(len(fw.stripped_ids) for fw in result.firewall_results)
        total_cited = total_kept + total_stripped
        if total_cited > 0 and total_stripped / total_cited > 0.3:
            logger.critical(
                "Narrative firewall stripped >30%% of citations — prompt needs "
                "review. case_id=%s strip_rate=%.2f stripped=%d total=%d",
                case_id,
                total_stripped / total_cited,
                total_stripped,
                total_cited,
            )

        # --- Log LLM usage -------------------------------------------
        if result.llm_usage:
            u = result.llm_usage
            await db.table("llm_usage_log").insert(
                {
                    "organization_id": organization_id,
                    "case_id": case_id,
                    "model": u.model,
                    "step": u.step,
                    "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens,
                    "cost_usd": str(u.cost_usd),
                    "duration_ms": u.duration_ms,
                }
            ).execute()
            logger.info(
                "LLM usage logged: in=%d out=%d cost=$%.4f",
                u.input_tokens,
                u.output_tokens,
                u.cost_usd,
            )

            # --- Cost anomaly detection (observability, never blocks) -
            from app.services.cost_monitor import check_cost_anomaly

            await check_cost_anomaly(
                case_id=case_id,
                cost_usd=u.cost_usd,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
            )

        # --- Mark case as ready for review ----------------------------
        await (
            db.table("cases")
            .update(
                {
                    "status": "in_review",
                    "description": (
                        f"Investigation complete. Narrative v{next_version} "
                        "ready for review."
                    ),
                }
            )
            .eq("id", case_id)
            .execute()
        )

        logger.info(
            "Pipeline completed: case=%s narrative=%s version=%d",
            case_id,
            narrative_id,
            next_version,
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

        alert_data: dict[str, Any] = alert_result.data.get("raw_data") or alert_result.data
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
