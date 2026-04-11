"""
End-to-end integration test: EvidencePipeline + DB persistence.

Alert typology: structuring / smurfing (US jurisdiction)
  - 12 cash deposits between $9,200 and $9,800 across 6 branches over 6 days
  - All amounts below the $10,000 BSA/AML CTR threshold
  - Beneficial owner: Thomas J. Mercer (DOB: 1985-03-14, nationality: US)
  - No prior SARs, no sanctions/PEP hits
  - Actual activity entirely inconsistent with stated business purpose

Requires: ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY env vars.

Run:
    cd apps/api
    python -m pytest tests/test_pipeline.py -v -s

DISCREPANCIES with task spec (actual code followed):
  - EvidencePipeline.run() takes alert: dict, not alert_id: str.
  - Returns EvidencePipelineResult, not PipelineResult.
  - No result.steps list; steps are persisted as investigation_steps rows (4 rows:
    parse, gather, screen, analyze). The 5th step (narrate) produces narrative rows.
  - No result.cost_usd / result.duration_seconds; cost lives in result.llm_usage.
  - DB client is app.db.get_service_db(), not app.db.supabase.
  - DB persistence is handled by _run_pipeline_background() in
    app.routers.investigations, not by the pipeline itself.
  - Phase 2 migration made section_id NULLABLE, not NOT NULL.
  - llm_usage_log.model contains the model constant from step5_narrate (currently
    "claude-opus-4-6"), satisfying the "contains claude" assertion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from supabase import AsyncClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"

EXPECTED_SECTION_KEYS = {
    "subject_information",
    "suspicious_activity_summary",
    "detailed_narrative",
    "supporting_evidence",
}

# HIGH 4: screen step may finish with partial coverage (e.g. Serper timeout).
VALID_STEP_STATUSES = {"completed", "completed_with_warnings"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def structuring_alert_data() -> dict[str, Any]:
    """Load the canned structuring-case alert from the JSON fixture."""
    path = FIXTURES_DIR / "structuring_alert.json"
    return json.loads(path.read_text())


@pytest.fixture
async def pipeline_case(
    db: AsyncClient,
    test_org: str,
    test_user: str,
    structuring_alert_data: dict[str, Any],
):
    """Insert an alert + case, run the full pipeline, persist results, yield IDs.

    Teardown deletes llm_usage_log rows that reference this case (the row
    survives org deletion because its FK is ON DELETE SET NULL).
    All other rows cascade-delete when the test_org fixture tears down.
    """
    from app.routers.investigations import _run_pipeline_background

    alert_row = {
        "organization_id": test_org,
        "title": structuring_alert_data.get("alert_type", "structuring"),
        "description": "Integration test alert",
        "source": "test",
        "raw_data": structuring_alert_data,
        "created_by": test_user,
    }
    alert_result = await db.table("alerts").insert(alert_row).execute()
    alert_id: str = alert_result.data[0]["id"]

    case_row = {
        "organization_id": test_org,
        "alert_id": alert_id,
        "title": (
            f"Integration test: {structuring_alert_data['alert_type']} — "
            f"{structuring_alert_data['account_holder']}"
        ),
        "description": "Pipeline integration test in progress…",
        "status": "open",
        "assigned_to": test_user,
        "created_by": test_user,
    }
    case_result = await db.table("cases").insert(case_row).execute()
    case_id: str = case_result.data[0]["id"]

    await _run_pipeline_background(
        case_id=case_id,
        alert_data=structuring_alert_data,
        organization_id=test_org,
        user_id=test_user,
    )

    yield {
        "case_id": case_id,
        "alert_id": alert_id,
        "org_id": test_org,
        "user_id": test_user,
    }

    await db.table("llm_usage_log").delete().eq("case_id", case_id).execute()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_end_to_end(
    db: AsyncClient,
    pipeline_case: dict[str, str],
) -> None:
    """Run the full 5-step evidence pipeline and verify every DB artefact."""
    case_id = pipeline_case["case_id"]
    org_id = pipeline_case["org_id"]

    # ── 1. Case status should be "in_review" (not "open", which means failure) ──
    case_row = (
        await db.table("cases")
        .select("status, description")
        .eq("id", case_id)
        .single()
        .execute()
    ).data
    assert case_row["status"] == "in_review", (
        f"Pipeline failed — case still '{case_row['status']}': {case_row['description']}"
    )

    # ── 2. Investigation steps: 4 rows (parse, gather, screen, analyze) ──
    steps = (
        await db.table("investigation_steps")
        .select("name, status")
        .eq("case_id", case_id)
        .order("created_at")
        .execute()
    ).data
    step_names = [s["name"] for s in steps]
    assert step_names == ["parse", "gather", "screen", "analyze"], (
        f"Expected [parse, gather, screen, analyze], got {step_names}"
    )
    for step in steps:
        assert step["status"] in VALID_STEP_STATUSES, (
            f"Step '{step['name']}' has status '{step['status']}', "
            f"expected one of {VALID_STEP_STATUSES}"
        )

    partial_steps = [s for s in steps if s["status"] == "completed_with_warnings"]
    assert len(partial_steps) >= 1, (
        "Expected at least one step with completed_with_warnings status "
        "(partial screening coverage should be exercised by this fixture)"
    )

    # ── 3. Narrative + sections ──────────────────────────────────────────
    narrative = (
        await db.table("narratives")
        .select("id, title, version")
        .eq("case_id", case_id)
        .single()
        .execute()
    ).data
    narrative_id = narrative["id"]
    assert narrative["title"], "Narrative title must not be empty"
    assert narrative["version"] == 1

    sections = (
        await db.table("narrative_sections")
        .select("section_key, content")
        .eq("narrative_id", narrative_id)
        .order("order_index")
        .execute()
    ).data
    actual_keys = {s["section_key"] for s in sections}
    assert actual_keys == EXPECTED_SECTION_KEYS, (
        f"Section keys mismatch: expected {EXPECTED_SECTION_KEYS}, got {actual_keys}"
    )
    for section in sections:
        assert len(section["content"]) > 50, (
            f"Section '{section['section_key']}' content too short "
            f"({len(section['content'])} chars)"
        )

    # ── 4. Evidence links ────────────────────────────────────────────────
    evidence_links = (
        await db.table("evidence_links")
        .select("id, evidence_ref, section_id, investigation_step_id")
        .eq("narrative_id", narrative_id)
        .execute()
    ).data
    assert len(evidence_links) >= 1, "Expected at least one evidence_link row"
    for link in evidence_links:
        assert link["evidence_ref"] is not None, (
            f"evidence_link {link['id']} has null evidence_ref"
        )
        assert link["investigation_step_id"] is not None, (
            f"evidence_link {link['id']} has null investigation_step_id"
        )

    # ── 5. LLM usage log ────────────────────────────────────────────────
    usage_rows = (
        await db.table("llm_usage_log")
        .select("model, step, input_tokens, output_tokens, cost_usd, duration_ms")
        .eq("case_id", case_id)
        .execute()
    ).data
    assert len(usage_rows) == 1, (
        f"Expected exactly 1 llm_usage_log row, got {len(usage_rows)}"
    )
    usage = usage_rows[0]
    assert "claude" in usage["model"], (
        f"Expected model containing 'claude', got '{usage['model']}'"
    )
    assert usage["step"] == "narrate"
    assert usage["input_tokens"] > 0, "input_tokens must be > 0"
    assert usage["output_tokens"] > 0, "output_tokens must be > 0"
    cost = float(usage["cost_usd"])
    assert 0 < cost < 5.0, f"Cost ${cost:.4f} outside expected range (0, 5.0)"
    assert usage["duration_ms"] is not None and usage["duration_ms"] > 0

    # ── 6. Print summary (visible with pytest -s) ────────────────────────
    print(f"\n{'=' * 60}")
    print("PIPELINE INTEGRATION TEST — PASSED")
    print(f"{'=' * 60}")
    print(f"  case_id:          {case_id}")
    print(f"  narrative_id:     {narrative_id}")
    print(f"  steps:            {step_names}")
    print(f"  sections:         {sorted(actual_keys)}")
    print(f"  evidence_links:   {len(evidence_links)}")
    print(
        f"  llm: model={usage['model']} "
        f"in={usage['input_tokens']} out={usage['output_tokens']} "
        f"cost=${cost:.4f} duration={usage['duration_ms']}ms"
    )
    print(f"{'=' * 60}")
