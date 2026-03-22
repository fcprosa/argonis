"""
End-to-end integration test: EvidencePipeline.

Runs all 5 steps against the canonical structuring alert.
Requires ANTHROPIC_API_KEY. Steps 1-4 also tested independently in other files.

Run:
    cd apps/api
    python -m pytest tests/pipeline/test_e2e.py -v -s
"""

from __future__ import annotations

import os
import re
from typing import Any

import pytest

from app.pipeline.core import EvidencePipeline
from app.pipeline.models import EvidencePipelineResult


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
async def test_evidence_pipeline_e2e(raw_alert: dict[str, Any]) -> None:
    """Full 5-step pipeline on the canonical structuring/smurfing alert."""
    pipeline = EvidencePipeline()
    result: EvidencePipelineResult = await pipeline.run(raw_alert)

    _assert_parse(result)
    _assert_gather(result)
    _assert_screen(result)
    _assert_analyze(result)
    _assert_evidence_package(result)
    _assert_narrative(result)

    _print_result(result)


# ---------------------------------------------------------------------------
# Per-step assertions
# ---------------------------------------------------------------------------


def _assert_parse(result: EvidencePipelineResult) -> None:
    p = result.parsed_alert

    assert p.alert_id == "AML-2026-00147"
    assert p.transaction_count == 4
    assert p.jurisdiction == "GB"
    assert p.beneficial_owner_name == "Mikhail Voronov"
    assert p.nationality == "RU"

    print(
        f"\n[PARSE] alert={p.alert_id} txns={p.transaction_count} "
        f"total={p.total_amount} {p.transactions[0].currency} "
        f"jurisdiction={p.jurisdiction}"
    )


def _assert_gather(result: EvidencePipelineResult) -> None:
    g = result.gathered_data

    assert len(g.kyc_profiles) >= 1
    assert any(k.entity_name == "Nexbridge Trading Ltd" for k in g.kyc_profiles)
    assert any(k.entity_name == "Mikhail Voronov" for k in g.kyc_profiles)

    print(
        f"[GATHER] kyc_profiles={len(g.kyc_profiles)} "
        f"relationships={len(g.account_relationships)} "
        f"source={g.source_metadata.get('source')}"
    )


def _assert_screen(result: EvidencePipelineResult) -> None:
    s = result.screening_bundle

    assert "Nexbridge Trading Ltd" in s.entity_names
    assert len(s.sources_queried) >= 1

    adverse = [h for h in s.hits if h.list_name == "adverse_media"]
    assert len(adverse) >= 1, "Adverse media hit on Nexbridge must be detected"

    for hit in s.hits:
        assert 0.0 <= hit.match_confidence <= 1.0

    print(
        f"[SCREEN] entities={s.entity_names} hits={len(s.hits)} "
        f"sources={s.sources_queried}"
    )


def _assert_analyze(result: EvidencePipelineResult) -> None:
    a = result.analysis_result

    assert a.structuring.detected is True, "Structuring must be detected"
    assert a.structuring.confidence >= 0.70

    assert a.geographic_risk.detected is True, "Russian BO nationality = geographic risk"

    assert a.overall_risk_score >= 0.60
    assert a.recommended_action in ("escalate", "file_sar")
    assert len(a.high_risk_indicators) >= 2

    print(
        f"[ANALYZE] score={a.overall_risk_score:.3f} action={a.recommended_action} "
        f"structuring={a.structuring.confidence:.0%} "
        f"geo_risk={a.geographic_risk.detected}"
    )


def _assert_evidence_package(result: EvidencePipelineResult) -> None:
    items = result.evidence_items
    ids = [item.id for item in items]

    assert len(items) >= 15
    assert len(ids) == len(set(ids)), "Evidence IDs must be unique"

    # Must cover all source steps
    sources = {item.source for item in items}
    assert "step1_parse" in sources
    assert "step2_gather" in sources
    assert "step3_screen" in sources
    assert "step4_analyze" in sources

    # Must have transaction items for all 4 deposits
    txn_items = [i for i in items if i.category == "transaction"]
    assert len(txn_items) == 4

    print(f"[EVIDENCE] total_items={len(items)} sources={sources}")


def _assert_narrative(result: EvidencePipelineResult) -> None:
    n = result.narrative

    assert n.case_title
    assert len(n.case_title) <= 80

    section_keys = {s.section_key for s in n.sections}
    assert "executive_summary" in section_keys
    assert "findings" in section_keys
    assert "conclusion" in section_keys

    # SAR required for this alert (structuring + adverse media + new account)
    assert n.sar_required is True, "SAR must be required for this structuring alert"
    assert n.sar_grounds, "sar_grounds must be set when sar_required=True"

    assert n.recommended_action in ("escalate", "file_sar")

    # All cited IDs must exist in the evidence package
    valid_ids = {item.id for item in result.evidence_items}
    for eid in n.evidence_ids_cited:
        assert eid in valid_ids, f"Narrative cited non-existent evidence ID: {eid}"

    # Verify inline citations appear in section text
    citation_pattern = re.compile(r"\[EVID-\d{3}\]")
    all_text = " ".join(s.content for s in n.sections)
    found = citation_pattern.findall(all_text)
    assert len(found) >= 5, "Expected multiple [EVID-XXX] citations in narrative text"

    print(
        f"\n[NARRATIVE] '{n.case_title}'"
        f"\n  SAR={n.sar_required}  action={n.recommended_action}"
        f"\n  sections={section_keys}"
        f"\n  cited_ids={len(n.evidence_ids_cited)}"
        f"\n  inline_citations={len(found)}"
    )
    if n.sar_grounds:
        print(f"  sar_grounds: {n.sar_grounds}")

    print(f"\n  Sections:")
    for section in n.sections:
        print(f"  [{section.section_key}] {section.title}")
        print(f"    {section.content[:200]}…")


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------


def _print_result(result: EvidencePipelineResult) -> None:
    print("\n" + "=" * 70)
    print("EVIDENCE PIPELINE — FULL RESULT")
    print("=" * 70)

    print("\n── Step 1: Parsed Alert ──")
    p = result.parsed_alert
    for txn in p.transactions:
        print(f"  {txn.date}  {txn.amount} {txn.currency}  {txn.type}  branch={txn.branch}")

    print("\n── Step 4: Analysis ──")
    a = result.analysis_result
    for name in ["structuring", "layering", "funnel", "velocity", "geographic_risk"]:
        d = getattr(a, name)
        if d.detected:
            print(f"  ✓ {name} ({d.confidence:.0%})")
            for ev in d.evidence:
                print(f"    • {ev}")

    print(f"\n  Risk score: {a.overall_risk_score:.0%}")
    print(f"  Recommended action: {a.recommended_action}")

    print("\n── Step 5: Narrative ──")
    n = result.narrative
    print(f"  Case title: {n.case_title}")
    print(f"  SAR required: {n.sar_required}")
    if n.sar_grounds:
        print(f"  SAR grounds: {n.sar_grounds}")
    for section in n.sections:
        print(f"\n  [{section.section_key.upper()}] {section.title}")
        print(f"  {section.content}")
