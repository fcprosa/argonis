"""
End-to-end integration test: EvidencePipeline against ONE hardcoded alert.

Alert typology: structuring / smurfing (UK jurisdiction)
  - Four cash deposits just below the £10,000 reporting threshold
  - Account is 47 days old
  - Beneficial owner has Russian nationality
  - Adverse media hit on the company name
  - Activity far outside declared business purpose

Requires: ANTHROPIC_API_KEY environment variable.

Run:
    cd apps/api
    python -m pytest tests/test_pipeline.py -v -s
"""

from __future__ import annotations

import json
import os

import pytest

from app.pipeline.core import EvidencePipeline
from app.pipeline.models import EvidencePipelineResult

# ---------------------------------------------------------------------------
# Hardcoded test alert
# ---------------------------------------------------------------------------

HARDCODED_ALERT: dict[str, object] = {
    "alert_id": "AML-2026-00147",
    "alert_type": "structuring",
    "generated_at": "2026-03-15T09:14:00Z",
    "account_number": "4892-7731-0012",
    "account_holder": "Nexbridge Trading Ltd",
    "jurisdiction": "GB",
    "transactions": json.dumps([
        {
            "date": "2026-03-10",
            "amount": 9800,
            "currency": "GBP",
            "type": "cash_deposit",
            "branch": "London City",
        },
        {
            "date": "2026-03-11",
            "amount": 9750,
            "currency": "GBP",
            "type": "cash_deposit",
            "branch": "Canary Wharf",
        },
        {
            "date": "2026-03-12",
            "amount": 9900,
            "currency": "GBP",
            "type": "cash_deposit",
            "branch": "Stratford",
        },
        {
            "date": "2026-03-13",
            "amount": 9600,
            "currency": "GBP",
            "type": "cash_deposit",
            "branch": "Hackney",
        },
    ]),
    "counterparties": (
        "Multiple cash deposits, no single counterparty identified. "
        "Originator listed as unknown on all transactions."
    ),
    "account_age_days": 47,
    "prior_sar_count": 0,
    "beneficial_owner": "Mikhail Voronov (DOB: 1974-08-22, nationality: RU)",
    "business_type": "Import/export trading company",
    "expected_monthly_activity": "Business payments to EU suppliers, max GBP 50,000/month",
    "actual_activity_30d": (
        "GBP 39,050 in cash deposits across 4 branches in 4 consecutive days. "
        "No outgoing payments observed."
    ),
    "screening_hits": (
        "Nexbridge Trading Ltd — 1 adverse media hit: "
        "alleged involvement in VAT fraud scheme (source: FT, 2023-09-14)"
    ),
    "sanctions_hits": "None",
    "pep_hits": "None",
}


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
async def test_pipeline_end_to_end() -> None:
    """Run the full 5-step evidence pipeline and assert on output quality."""
    pipeline = EvidencePipeline(
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )
    result: EvidencePipelineResult = await pipeline.run(HARDCODED_ALERT)

    _assert_parse(result)
    _assert_analysis(result)
    _assert_evidence_package(result)
    _assert_narrative(result)
    _assert_cost(result)

    _print_results(result)


# ---------------------------------------------------------------------------
# Per-step assertions
# ---------------------------------------------------------------------------


def _assert_parse(result: EvidencePipelineResult) -> None:
    p = result.parsed_alert
    assert p.alert_id == "AML-2026-00147"
    assert p.transaction_count == 4, f"Expected 4 transactions, got {p.transaction_count}"
    assert p.total_amount == 39050, f"Expected total 39050 GBP, got {p.total_amount}"
    assert p.nationality == "RU", f"Expected RU nationality, got {p.nationality}"
    assert p.account_age_days == 47
    assert p.reporting_threshold == 10000
    print(f"\n[PARSE] alert_id={p.alert_id} txns={p.transaction_count} total={p.total_amount} {p.transactions[0].currency}")


def _assert_analysis(result: EvidencePipelineResult) -> None:
    a = result.analysis_result
    assert a.structuring.detected, "Structuring must be detected for 4 sub-threshold deposits"
    assert a.structuring.confidence >= 0.55, f"Structuring confidence too low: {a.structuring.confidence}"
    assert a.geographic_risk.detected, "Geographic risk must flag RU nationality"
    assert a.overall_risk_score >= 0.4, f"Risk score too low: {a.overall_risk_score}"
    assert a.recommended_action in ("investigate", "escalate", "file_sar"), (
        f"Expected escalation action, got: {a.recommended_action}"
    )
    print(
        f"\n[ANALYZE] risk={a.overall_risk_score:.3f} action={a.recommended_action} "
        f"structuring={a.structuring.detected} geo_risk={a.geographic_risk.detected}"
    )


def _assert_evidence_package(result: EvidencePipelineResult) -> None:
    items = result.evidence_items
    assert len(items) >= 10, f"Expected ≥10 evidence items, got {len(items)}"
    ids = {item.id for item in items}
    assert all(i.startswith("EVID-") for i in ids), "All evidence IDs must be EVID-XXX format"

    categories = {item.category for item in items}
    assert "transaction" in categories, "Must have transaction evidence"
    assert "pattern" in categories or "analysis" in categories, "Must have pattern/analysis evidence"
    print(f"\n[EVIDENCE] {len(items)} items, categories={sorted(categories)}")


def _assert_narrative(result: EvidencePipelineResult) -> None:
    n = result.narrative
    assert n.case_title, "case_title must not be empty"
    assert len(n.sections) == 4, f"Expected 4 sections, got {len(n.sections)}"

    expected_keys = {
        "subject_information",
        "suspicious_activity_summary",
        "detailed_narrative",
        "supporting_evidence",
    }
    actual_keys = {s.section_key for s in n.sections}
    assert actual_keys == expected_keys, f"Section keys mismatch: {actual_keys}"

    assert n.sar_required is True, (
        "SAR must be required for: structuring + RU nationality + adverse media + new account"
    )
    assert n.sar_grounds, "sar_grounds must be set when sar_required=True"

    # All cited IDs must be valid
    valid_ids = {item.id for item in result.evidence_items}
    for eid in n.evidence_ids_cited:
        assert eid in valid_ids, f"Narrative cited non-existent evidence ID: {eid}"

    print(
        f"\n[NARRATIVE] title={n.case_title!r} sar={n.sar_required} "
        f"action={n.recommended_action} cited={len(n.evidence_ids_cited)}"
    )
    for s in n.sections:
        print(f"  [{s.section_key}] {s.title} ({len(s.content)} chars)")


def _assert_cost(result: EvidencePipelineResult) -> None:
    usage = result.llm_usage
    assert usage is not None, "llm_usage must be populated"
    assert usage.input_tokens > 0
    assert usage.output_tokens > 0
    assert usage.cost_usd < 5.0, f"Cost exceeded $5 budget: ${usage.cost_usd:.4f}"
    assert usage.duration_ms is not None and usage.duration_ms > 0
    print(
        f"\n[COST] model={usage.model} in={usage.input_tokens} out={usage.output_tokens} "
        f"cost=${usage.cost_usd:.4f} duration={usage.duration_ms}ms"
    )


# ---------------------------------------------------------------------------
# Print helper
# ---------------------------------------------------------------------------


def _print_results(result: EvidencePipelineResult) -> None:
    print("\n" + "=" * 60)
    print("FULL NARRATIVE OUTPUT")
    print("=" * 60)
    for section in result.narrative.sections:
        print(f"\n### {section.title.upper()}")
        print(section.content)
    print("\n" + "=" * 60)
