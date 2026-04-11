"""
Helper for writing pipeline_events rows.

pipeline_events is the application-level meta-event table, distinct
from audit_log (which is trigger-written row-level DML). Any Python
code that needs to log "something non-row-level happened during a
pipeline run" should call `log_pipeline_event()` instead of writing
to audit_log directly.

Event types must match the pipeline_event_type enum in migration
20260416000000_pipeline_events.sql. Adding a new event type requires
a new migration.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from supabase import AsyncClient

logger = logging.getLogger(__name__)

PipelineEventType = Literal[
    "screening_partial",
    "screening_source_failed",
    "kyc_missing",
    "ofac_unavailable",
    "firewall_strip",
    "pipeline_failed",
    "pipeline_halted",
]


async def log_pipeline_event(
    db: AsyncClient,
    *,
    organization_id: str,
    case_id: str,
    event_type: PipelineEventType,
    message: str,
    details: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> None:
    """Insert a single pipeline_events row.

    Never raises. Errors are logged and swallowed — a failure to write
    an observability row must not crash the pipeline. The pipeline's
    primary persistence path (investigation_steps, narratives, etc.)
    is already committed by the time this is called.
    """
    row: dict[str, Any] = {
        "organization_id": organization_id,
        "case_id": case_id,
        "event_type": event_type,
        "message": message,
        "details": details or {},
    }
    if user_id is not None:
        row["user_id"] = user_id

    try:
        await db.table("pipeline_events").insert(row).execute()
    except Exception as exc:
        logger.warning(
            "failed to write pipeline_event type=%s case_id=%s: %s",
            event_type,
            case_id,
            exc,
        )
