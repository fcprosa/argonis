"""Persist a completed ``EvidencePipelineResult`` to Supabase (service role)."""

from __future__ import annotations

import logging
from typing import Any

from supabase import AsyncClient

from app.pipeline.models import EvidencePipelineResult
from app.services.pipeline_events import log_pipeline_event

logger = logging.getLogger(__name__)


async def persist_pipeline_result(
    case_id: str,
    organization_id: str,
    user_id: str,
    result: EvidencePipelineResult,
    db: AsyncClient,
) -> None:
    """Store investigation steps through case status update (success path only)."""
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
    step_id_map: dict[str, Any] = {
        row["name"]: row["id"] for row in (steps_result.data or [])  # type: ignore[index]
    }
    source_to_step = {
        "step1_parse": "parse",
        "step2_gather": "gather",
        "step3_screen": "screen",
        "step4_analyze": "analyze",
        "compliance_overlay": "analyze",
    }

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
                "coverage_gaps_debug": result.screening_bundle.coverage_gaps_debug,
                "sources_queried": result.screening_bundle.sources_queried,
                "source_results": [
                    sr.model_dump(mode="json")
                    for sr in result.screening_bundle.source_results
                ],
            },
        )

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
            row["section_key"]: row["id"] for row in (section_result.data or [])
        }

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

        from app.services.cost_monitor import check_cost_anomaly

        await check_cost_anomaly(
            case_id=case_id,
            cost_usd=u.cost_usd,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
        )

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
