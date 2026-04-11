"""
Golden-set regression tests for the evidence-first pipeline.

Parametrized over 5 canonical AML typologies. Each test:
  1. Inserts the fixture alert into Supabase (so Step 2 GATHER can query it).
  2. Runs the full 5-step pipeline (real Claude API call for Step 5).
  3. Asserts Step 4 deterministic detector results against expected.py.
  4. Asserts structural narrative properties (sections present, content length).
  5. Asserts evidence package size and LLM cost budget.
  6. Cleans up inserted rows on teardown.

Requires: ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY env vars.

Run:
    cd apps/api
    python -m pytest tests/test_golden_set.py -v -s
    python -m pytest tests/test_golden_set.py -k structuring -v -s  # single typology
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from supabase import AsyncClient

from app.config import settings
from app.pipeline.core import EvidencePipeline
from app.pipeline.models import EvidencePipelineResult
from tests.golden.conftest import cleanup_kyc_for_org, insert_kyc_for_fixture
from tests.golden.expected import (
    DETECTOR_NAMES,
    EXPECTATIONS,
    GoldenExpectation,
)

GOLDEN_DIR = Path(__file__).parent / "golden"

# These fixtures have dedicated tests with special setup requirements
_SPECIAL_TYPOLOGIES = {"partial_screening", "missing_kyc"}
TYPOLOGIES = sorted(k for k in EXPECTATIONS if k not in _SPECIAL_TYPOLOGIES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> dict[str, Any]:
    path = GOLDEN_DIR / f"{name}.json"
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=TYPOLOGIES)
def typology(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def alert_data(typology: str) -> dict[str, Any]:
    return _load_fixture(typology)


@pytest.fixture
def expectation(typology: str) -> GoldenExpectation:
    return EXPECTATIONS[typology]


@pytest.fixture
async def pipeline_result(
    db: AsyncClient,
    test_org: str,
    test_user: str,
    alert_data: dict[str, Any],
) -> EvidencePipelineResult:
    """Insert the alert + KYC profile, run the full pipeline, yield result, clean up."""
    # Insert matching KYC profile (if one exists for this fixture)
    account_holder = alert_data.get("account_holder", "")
    await insert_kyc_for_fixture(db, test_org, account_holder)

    alert_row = {
        "organization_id": test_org,
        "title": alert_data.get("alert_type", "golden-set"),
        "description": f"Golden-set test: {alert_data.get('alert_id', '')}",
        "source": "golden_set_test",
        "raw_data": alert_data,
        "created_by": test_user,
    }
    insert_result = await db.table("alerts").insert(alert_row).execute()
    alert_db_id: str = insert_result.data[0]["id"]

    pipeline = EvidencePipeline(
        api_key=settings.anthropic_api_key or None,
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_key,
        opensanctions_api_key=settings.opensanctions_api_key,
        serper_api_key=settings.serper_api_key,
    )
    result = await pipeline.run(alert_data)

    yield result  # type: ignore[misc]

    await db.table("alerts").delete().eq("id", alert_db_id).execute()
    await cleanup_kyc_for_org(db, test_org)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_golden_typology(
    typology: str,
    alert_data: dict[str, Any],
    expectation: GoldenExpectation,
    pipeline_result: EvidencePipelineResult,
) -> None:
    """Validate deterministic pipeline outputs for a single golden typology."""
    analysis = pipeline_result.analysis_result
    narrative = pipeline_result.narrative

    # ── Step 4: detector fired / not-fired ────────────────────────────────
    for detector_name in DETECTOR_NAMES:
        detection = getattr(analysis, detector_name)
        expected = expectation.detectors[detector_name]

        assert detection.detected == expected.should_fire, (
            f"[{typology}] {detector_name}: "
            f"expected detected={expected.should_fire}, "
            f"got detected={detection.detected}"
        )

        if expected.should_fire:
            assert expected.confidence_min <= detection.confidence <= expected.confidence_max, (
                f"[{typology}] {detector_name}: "
                f"confidence {detection.confidence:.3f} outside "
                f"[{expected.confidence_min}, {expected.confidence_max}]"
            )

    # ── Narrative sections ────────────────────────────────────────────────
    actual_keys = {s.section_key for s in narrative.sections}
    assert actual_keys == set(expectation.section_keys), (
        f"[{typology}] section_keys: expected {expectation.section_keys}, got {actual_keys}"
    )

    for section in narrative.sections:
        assert len(section.content) >= expectation.min_section_content_length, (
            f"[{typology}] section '{section.section_key}' content too short: "
            f"{len(section.content)} chars < {expectation.min_section_content_length} min"
        )

    # ── Evidence items ────────────────────────────────────────────────────
    assert len(pipeline_result.evidence_items) >= expectation.min_evidence_items, (
        f"[{typology}] evidence_items: "
        f"{len(pipeline_result.evidence_items)} < {expectation.min_evidence_items} min"
    )

    # ── LLM cost budget ──────────────────────────────────────────────────
    assert pipeline_result.llm_usage is not None, f"[{typology}] llm_usage is None"
    assert pipeline_result.llm_usage.cost_usd < expectation.max_cost_usd, (
        f"[{typology}] cost ${pipeline_result.llm_usage.cost_usd:.4f} "
        f"exceeds ${expectation.max_cost_usd} budget"
    )

    # ── Print summary (visible with -s) ───────────────────────────────────
    fired = [
        n for n in DETECTOR_NAMES if getattr(analysis, n).detected
    ]
    print(
        f"\n[GOLDEN {typology}] "
        f"detectors={fired} "
        f"risk={analysis.overall_risk_score:.3f} "
        f"action={analysis.recommended_action} "
        f"evidence={len(pipeline_result.evidence_items)} "
        f"cost=${pipeline_result.llm_usage.cost_usd:.4f}"
    )


# ---------------------------------------------------------------------------
# Partial screening test — deliberately broken OpenSanctions API key
# ---------------------------------------------------------------------------


@pytest.fixture
async def partial_screening_result(
    db: AsyncClient,
    test_org: str,
    test_user: str,
) -> EvidencePipelineResult:
    """Run partial_screening fixture with an invalid OpenSanctions key."""
    alert_data = _load_fixture("partial_screening")

    account_holder = alert_data.get("account_holder", "")
    await insert_kyc_for_fixture(db, test_org, account_holder)

    alert_row = {
        "organization_id": test_org,
        "title": alert_data.get("alert_type", "golden-set"),
        "description": f"Golden-set test: {alert_data.get('alert_id', '')}",
        "source": "golden_set_test",
        "raw_data": alert_data,
        "created_by": test_user,
    }
    insert_result = await db.table("alerts").insert(alert_row).execute()
    alert_db_id: str = insert_result.data[0]["id"]

    pipeline = EvidencePipeline(
        api_key=settings.anthropic_api_key or None,
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_key,
        opensanctions_api_key="INVALID_KEY_FOR_PARTIAL_SCREENING_TEST",
        serper_api_key=settings.serper_api_key,
    )
    result = await pipeline.run(alert_data)

    yield result  # type: ignore[misc]

    await db.table("alerts").delete().eq("id", alert_db_id).execute()
    await cleanup_kyc_for_org(db, test_org)


@pytest.mark.asyncio
async def test_partial_screening(
    partial_screening_result: EvidencePipelineResult,
) -> None:
    """Verify soft-fail behavior when OpenSanctions is unavailable."""
    result = partial_screening_result

    # Pipeline must complete (not halt)
    assert not result.halted, "Pipeline should NOT halt on OpenSanctions failure"
    assert result.narrative is not None, "Narrative must be generated"
    assert result.analysis_result is not None, "Analysis must run"

    # Screening bundle must be marked partial
    assert result.screening_bundle is not None
    assert result.screening_bundle.is_partial, "Screening should be partial"
    assert any(
        "OpenSanctions" in gap for gap in result.screening_bundle.coverage_gaps
    ), f"coverage_gaps should mention OpenSanctions: {result.screening_bundle.coverage_gaps}"

    # Narrative must carry partial screening flag
    assert result.narrative.is_partial_screening is True
    assert len(result.narrative.screening_gaps) > 0

    # All 4 standard sections must still be present
    actual_keys = {s.section_key for s in result.narrative.sections}
    for key in ("subject_information", "suspicious_activity_summary",
                "detailed_narrative", "supporting_evidence"):
        assert key in actual_keys, f"Missing expected section: {key}"

    # Cost must be within budget
    assert result.llm_usage is not None
    assert result.llm_usage.cost_usd < 5.0

    print(
        f"\n[GOLDEN partial_screening] "
        f"is_partial={result.screening_bundle.is_partial} "
        f"coverage_gaps={result.screening_bundle.coverage_gaps} "
        f"sections={len(result.narrative.sections)} "
        f"cost=${result.llm_usage.cost_usd:.4f}"
    )


# ---------------------------------------------------------------------------
# Missing KYC test — no kyc_profiles row exists for the account_holder
# ---------------------------------------------------------------------------

_KYC_WARNING_TEXT = (
    "Subject KYC profile was not found in the customer database at the time "
    "of investigation"
)


@pytest.fixture
async def missing_kyc_result(
    db: AsyncClient,
    test_org: str,
    test_user: str,
) -> EvidencePipelineResult:
    """Run missing_kyc fixture WITHOUT inserting a KYC profile."""
    alert_data = _load_fixture("missing_kyc")

    alert_row = {
        "organization_id": test_org,
        "title": alert_data.get("alert_type", "golden-set"),
        "description": f"Golden-set test: {alert_data.get('alert_id', '')}",
        "source": "golden_set_test",
        "raw_data": alert_data,
        "created_by": test_user,
    }
    insert_result = await db.table("alerts").insert(alert_row).execute()
    alert_db_id: str = insert_result.data[0]["id"]

    pipeline = EvidencePipeline(
        api_key=settings.anthropic_api_key or None,
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_key,
        opensanctions_api_key=settings.opensanctions_api_key,
        serper_api_key=settings.serper_api_key,
    )
    result = await pipeline.run(alert_data)

    yield result  # type: ignore[misc]

    await db.table("alerts").delete().eq("id", alert_db_id).execute()
    await cleanup_kyc_for_org(db, test_org)


@pytest.mark.asyncio
async def test_missing_kyc(
    missing_kyc_result: EvidencePipelineResult,
) -> None:
    """Verify graceful handling when no KYC profile exists."""
    result = missing_kyc_result

    # Pipeline must complete
    assert not result.halted, "Pipeline should not halt on missing KYC"
    assert result.narrative is not None, "Narrative must be generated"
    assert result.analysis_result is not None, "Analysis must run"

    # Step 2 must flag the synthetic profile and data gap
    assert result.gathered_data is not None
    kyc = result.gathered_data.kyc_profiles
    assert len(kyc) >= 1, "At least one (synthetic) KYC profile expected"
    assert kyc[0].is_synthetic is True, "KYC profile should be synthetic"
    assert kyc[0].source == "missing_kyc", f"source should be 'missing_kyc', got '{kyc[0].source}'"

    assert len(result.gathered_data.data_gaps) > 0, "data_gaps should be non-empty"
    assert any(
        "KYC_PROFILE_MISSING" in gap for gap in result.gathered_data.data_gaps
    ), f"data_gaps should mention KYC_PROFILE_MISSING: {result.gathered_data.data_gaps}"

    # Narrative Subject Information section must contain the warning
    subject_section = next(
        (s for s in result.narrative.sections if s.section_key == "subject_information"),
        None,
    )
    assert subject_section is not None, "subject_information section must exist"
    assert _KYC_WARNING_TEXT in subject_section.content, (
        f"Subject Information should contain KYC warning verbatim.\n"
        f"Expected substring: {_KYC_WARNING_TEXT!r}\n"
        f"Actual content: {subject_section.content[:500]!r}"
    )

    # All 4 standard sections must still be present
    actual_keys = {s.section_key for s in result.narrative.sections}
    for key in ("subject_information", "suspicious_activity_summary",
                "detailed_narrative", "supporting_evidence"):
        assert key in actual_keys, f"Missing expected section: {key}"

    # Cost within budget
    assert result.llm_usage is not None
    assert result.llm_usage.cost_usd < 5.0

    print(
        f"\n[GOLDEN missing_kyc] "
        f"is_synthetic={kyc[0].is_synthetic} "
        f"data_gaps={result.gathered_data.data_gaps} "
        f"sections={len(result.narrative.sections)} "
        f"cost=${result.llm_usage.cost_usd:.4f}"
    )
