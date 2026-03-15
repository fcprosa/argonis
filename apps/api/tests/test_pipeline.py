"""
End-to-end integration test: InvestigationPipeline against ONE hardcoded alert.

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

from app.agent.core import InvestigationPipeline, PipelineResult
from app.agent.models import InvestigationSummary

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
    """Run the full 4-step pipeline and assert on structured output quality."""
    pipeline = InvestigationPipeline()
    result: PipelineResult = await pipeline.run(HARDCODED_ALERT)

    _assert_triage(result)
    _assert_entity_extraction(result)
    _assert_risk_assessment(result)
    _assert_investigation_summary(result)
    _assert_token_usage(result)

    # Print full results for manual review when running with -s
    _print_results(result)


# ---------------------------------------------------------------------------
# Per-step assertions
# ---------------------------------------------------------------------------

def _assert_triage(result: PipelineResult) -> None:
    t = result.alert_triage

    assert t.severity in ("high", "critical"), (
        f"Structuring alert with adverse media should be high/critical, got: {t.severity}"
    )
    assert 0.0 <= t.confidence_score <= 1.0, (
        f"confidence_score out of range: {t.confidence_score}"
    )
    assert t.risk_type, "risk_type must not be empty"
    assert t.summary, "summary must not be empty"
    # Structuring-specific: structured deposits just under threshold = immediate action
    assert t.requires_immediate_action is True, (
        "Four sub-threshold cash deposits + adverse media should require immediate action"
    )

    print(
        f"\n[TRIAGE] severity={t.severity}  risk={t.risk_type}  "
        f"confidence={t.confidence_score:.2f}  immediate={t.requires_immediate_action}"
    )
    print(f"         {t.summary}")


def _assert_entity_extraction(result: PipelineResult) -> None:
    e = result.entity_extraction

    entity_names = [ent.name for ent in e.entities]
    assert any("Voronov" in n or "Nexbridge" in n for n in entity_names), (
        f"Must extract Voronov or Nexbridge as entities, got: {entity_names}"
    )

    # All four transactions are GBP
    gbp_amounts = [a for a in e.amounts if a.currency == "GBP"]
    assert len(gbp_amounts) >= 4, (
        f"Expected ≥4 GBP transaction amounts, got: {len(gbp_amounts)}"
    )

    # GB jurisdiction must be identified
    assert "GB" in e.jurisdictions, (
        f"GB must be in jurisdictions, got: {e.jurisdictions}"
    )

    print(
        f"\n[ENTITIES] {len(e.entities)} entities  "
        f"{len(e.amounts)} amounts  "
        f"jurisdictions={e.jurisdictions}"
    )
    for ent in e.entities:
        print(f"  • {ent.name} ({ent.entity_type}) — {ent.role}")


def _assert_risk_assessment(result: PipelineResult) -> None:
    r = result.risk_assessment

    assert r.overall_risk_score >= 0.6, (
        f"Structuring alert should score ≥0.6, got {r.overall_risk_score:.2f}"
    )
    assert r.recommended_action in ("investigate", "escalate", "file_sar"), (
        f"Expected investigate/escalate/file_sar for this alert, got: {r.recommended_action}"
    )
    assert len(r.risk_factors) >= 3, (
        f"Expected ≥3 risk factors for structuring+adverse media+new account, "
        f"got {len(r.risk_factors)}"
    )

    # Every risk factor must have evidence
    for rf in r.risk_factors:
        assert rf.evidence, f"Risk factor '{rf.factor}' has no evidence"
        assert 0.0 <= rf.score <= 1.0

    print(
        f"\n[RISK] score={r.overall_risk_score:.2f}  "
        f"action={r.recommended_action}  "
        f"factors={len(r.risk_factors)}"
    )
    for rf in r.risk_factors:
        print(f"  • {rf.factor} ({rf.score:.2f}): {rf.evidence[:80]}…")
    print(f"  rationale: {r.rationale}")


def _assert_investigation_summary(result: PipelineResult) -> None:
    s: InvestigationSummary = result.investigation_summary

    assert s.case_title, "case_title must not be empty"
    assert len(s.case_title) <= 80, f"case_title too long ({len(s.case_title)} chars)"
    assert len(s.key_findings) >= 3, (
        f"Expected ≥3 key findings for this complex alert, got {len(s.key_findings)}"
    )
    assert len(s.evidence_items) >= len(s.key_findings), (
        "Every key finding must have at least one corresponding evidence_item"
    )
    assert len(s.next_steps) >= 2, (
        f"Expected ≥2 next steps, got {len(s.next_steps)}"
    )

    # Structuring alert should recommend SAR under POCA 2002
    assert s.sar_required is True, (
        "Structuring with adverse media in UK jurisdiction should require SAR"
    )
    assert s.sar_grounds, "sar_grounds must be set when sar_required=True"

    # All evidence items must have source citations
    for ei in s.evidence_items:
        assert ei.source, f"Evidence item '{ei.description[:40]}' has no source"
        assert 0.0 <= ei.confidence <= 1.0

    print(f"\n[SUMMARY] '{s.case_title}'")
    print(f"  SAR required: {s.sar_required}")
    if s.sar_grounds:
        print(f"  Grounds: {s.sar_grounds}")
    print(f"  Key findings ({len(s.key_findings)}):")
    for f_ in s.key_findings:
        print(f"    • {f_}")
    print(f"  Next steps ({len(s.next_steps)}):")
    for step in s.next_steps:
        print(f"    → {step}")


def _assert_token_usage(result: PipelineResult) -> None:
    u = result.token_usage

    assert u.total > 0, "Token usage must be positive"
    assert u.total_input > 0, "Input tokens must be positive"
    assert u.total_output > 0, "Output tokens must be positive"

    # Each step must have been recorded
    expected_steps = {
        "alert_triage",
        "entity_extraction",
        "risk_assessment",
        "investigation_summary",
    }
    assert expected_steps == set(u.steps.keys()), (
        f"Missing steps in token usage: {expected_steps - set(u.steps.keys())}"
    )

    print(f"\n[TOKENS]\n{u.summary()}")


def _print_results(result: PipelineResult) -> None:
    print("\n" + "=" * 60)
    print("FULL PIPELINE RESULT")
    print("=" * 60)
    print("\nAlert triage:")
    print(result.alert_triage.model_dump_json(indent=2))
    print("\nEntity extraction:")
    print(result.entity_extraction.model_dump_json(indent=2))
    print("\nRisk assessment:")
    print(result.risk_assessment.model_dump_json(indent=2))
    print("\nInvestigation summary:")
    print(result.investigation_summary.model_dump_json(indent=2))
