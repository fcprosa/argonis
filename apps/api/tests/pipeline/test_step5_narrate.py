"""
Tests for Step 5: NARRATE

build_evidence_package() is deterministic — tested without API key.
narrate() calls the LLM — skipped unless ANTHROPIC_API_KEY is set.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.pipeline.models import EvidenceItem
from app.pipeline.step1_parse import parse_alert
from app.pipeline.step2_gather import _gather_stub
from app.pipeline.step3_screen import screen_entities
from app.pipeline.step4_analyze import analyze
from app.pipeline.step5_narrate import build_evidence_package, narrate


# ---------------------------------------------------------------------------
# build_evidence_package — deterministic, no LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evidence_package_has_items(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    screening = await screen_entities(parsed)
    analysis = analyze(parsed, gathered)

    items = build_evidence_package(parsed, gathered, screening, analysis)

    assert len(items) >= 10  # always has transactions + metadata + patterns


@pytest.mark.asyncio
async def test_evidence_ids_are_unique(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    screening = await screen_entities(parsed)
    analysis = analyze(parsed, gathered)

    items = build_evidence_package(parsed, gathered, screening, analysis)
    ids = [item.id for item in items]
    assert len(ids) == len(set(ids)), "Evidence IDs must be unique"


@pytest.mark.asyncio
async def test_evidence_ids_format(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    screening = await screen_entities(parsed)
    analysis = analyze(parsed, gathered)

    items = build_evidence_package(parsed, gathered, screening, analysis)
    import re
    pattern = re.compile(r"^EVID-\d{3}$")
    for item in items:
        assert pattern.match(item.id), f"Invalid ID format: {item.id}"


@pytest.mark.asyncio
async def test_evidence_package_includes_all_transactions(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    screening = await screen_entities(parsed)
    analysis = analyze(parsed, gathered)

    items = build_evidence_package(parsed, gathered, screening, analysis)
    txn_items = [i for i in items if i.category == "transaction"]
    assert len(txn_items) == 4  # 4 deposits in the test alert


@pytest.mark.asyncio
async def test_evidence_package_includes_structuring_pattern(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    screening = await screen_entities(parsed)
    analysis = analyze(parsed, gathered)

    items = build_evidence_package(parsed, gathered, screening, analysis)
    pattern_items = [i for i in items if i.category == "pattern"]
    assert any("structuring" in i.description.lower() for i in pattern_items)


@pytest.mark.asyncio
async def test_evidence_package_includes_screening_hits(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    screening = await screen_entities(parsed)
    analysis = analyze(parsed, gathered)

    items = build_evidence_package(parsed, gathered, screening, analysis)
    screening_items = [i for i in items if i.category == "screening"]
    assert len(screening_items) >= 1


@pytest.mark.asyncio
async def test_evidence_confidence_in_range(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    screening = await screen_entities(parsed)
    analysis = analyze(parsed, gathered)

    items = build_evidence_package(parsed, gathered, screening, analysis)
    for item in items:
        assert 0.0 <= item.confidence <= 1.0, f"{item.id} confidence out of range"


@pytest.mark.asyncio
async def test_evidence_values_are_non_empty(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    screening = await screen_entities(parsed)
    analysis = analyze(parsed, gathered)

    items = build_evidence_package(parsed, gathered, screening, analysis)
    for item in items:
        assert item.value.strip(), f"{item.id} has empty value"


# ---------------------------------------------------------------------------
# narrate() — requires ANTHROPIC_API_KEY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
async def test_narrate_produces_output(raw_alert: dict[str, Any]) -> None:
    import anthropic

    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    screening = await screen_entities(parsed)
    analysis = analyze(parsed, gathered)
    evidence = build_evidence_package(parsed, gathered, screening, analysis)

    client = anthropic.AsyncAnthropic()
    output = await narrate(parsed, evidence, client)

    assert output.case_title
    assert len(output.case_title) <= 80
    assert len(output.sections) >= 4

    section_keys = {s.section_key for s in output.sections}
    assert "executive_summary" in section_keys
    assert "findings" in section_keys

    assert output.recommended_action in (
        "dismiss", "monitor", "investigate", "escalate", "file_sar"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
async def test_narrate_cites_only_valid_evidence_ids(raw_alert: dict[str, Any]) -> None:
    import anthropic

    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    screening = await screen_entities(parsed)
    analysis = analyze(parsed, gathered)
    evidence = build_evidence_package(parsed, gathered, screening, analysis)
    valid_ids = {item.id for item in evidence}

    client = anthropic.AsyncAnthropic()
    output = await narrate(parsed, evidence, client)

    # All cited IDs must exist in the evidence package
    for eid in output.evidence_ids_cited:
        assert eid in valid_ids, f"Narrative cited non-existent evidence ID: {eid}"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
async def test_narrate_sar_required_for_structuring_alert(raw_alert: dict[str, Any]) -> None:
    import anthropic

    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    screening = await screen_entities(parsed)
    analysis = analyze(parsed, gathered)
    evidence = build_evidence_package(parsed, gathered, screening, analysis)

    client = anthropic.AsyncAnthropic()
    output = await narrate(parsed, evidence, client)

    assert output.sar_required is True
    assert output.sar_grounds, "sar_grounds must be set when sar_required=True"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
async def test_narrate_sections_contain_citations(raw_alert: dict[str, Any]) -> None:
    import anthropic
    import re

    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    screening = await screen_entities(parsed)
    analysis = analyze(parsed, gathered)
    evidence = build_evidence_package(parsed, gathered, screening, analysis)

    client = anthropic.AsyncAnthropic()
    output = await narrate(parsed, evidence, client)

    citation_pattern = re.compile(r"\[EVID-\d{3}\]")
    all_content = " ".join(s.content for s in output.sections)
    citations_found = citation_pattern.findall(all_content)

    assert len(citations_found) >= 3, (
        "Narrative should contain multiple evidence citations"
    )
