"""
Tests for Step 3: SCREEN

Tests the stub/alert-field path (no API key required).
Adverse media keyword detection always runs and is fully testable.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.pipeline.step1_parse import parse_alert
from app.pipeline.step3_screen import (
    _extract_entity_names,
    _screen_adverse_media,
    screen_entities,
)


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------


def test_extract_entity_names_includes_company_and_person(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    entities = _extract_entity_names(parsed)

    assert "Nexbridge Trading Ltd" in entities
    assert "Mikhail Voronov" in entities
    assert len(entities) == 2


def test_extract_entity_names_deduplicates_identical_names(raw_alert: dict[str, Any]) -> None:
    alert = dict(raw_alert)
    alert["beneficial_owner"] = "Nexbridge Trading Ltd"  # same as account_holder
    parsed = parse_alert(alert)
    entities = _extract_entity_names(parsed)

    assert entities.count("Nexbridge Trading Ltd") == 1


# ---------------------------------------------------------------------------
# Adverse media detection
# ---------------------------------------------------------------------------


def test_adverse_media_detects_vat_fraud(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    entities = _extract_entity_names(parsed)
    from datetime import datetime
    hits = _screen_adverse_media(parsed, entities, datetime.utcnow())

    assert len(hits) >= 1
    hit = hits[0]
    assert hit.list_name == "adverse_media"
    assert hit.match_type == "keyword"
    assert 0.0 <= hit.match_confidence <= 1.0
    assert hit.entity_name in entities


def test_adverse_media_extracts_source_url(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    entities = _extract_entity_names(parsed)
    from datetime import datetime
    hits = _screen_adverse_media(parsed, entities, datetime.utcnow())

    # The test alert says "source: FT" — should be captured
    hit = next((h for h in hits if h.source_url), None)
    assert hit is not None
    assert "FT" in (hit.source_url or "")


def test_no_adverse_media_when_clean(raw_alert: dict[str, Any]) -> None:
    alert = dict(raw_alert)
    alert["screening_hits"] = "No hits"
    alert["sanctions_hits"] = "None"
    alert["pep_hits"] = "None"
    alert["actual_activity_30d"] = "Normal business activity"
    parsed = parse_alert(alert)
    entities = _extract_entity_names(parsed)
    from datetime import datetime
    hits = _screen_adverse_media(parsed, entities, datetime.utcnow())
    assert hits == []


# ---------------------------------------------------------------------------
# screen_entities (no API key — stub path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_screen_entities_no_key_returns_bundle(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    bundle = await screen_entities(parsed)  # no opensanctions_api_key

    assert len(bundle.entity_names) == 2
    assert bundle.screened_at is not None
    assert len(bundle.sources_queried) >= 1


@pytest.mark.asyncio
async def test_screen_entities_adverse_media_always_included(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    bundle = await screen_entities(parsed)

    adverse_hits = [h for h in bundle.hits if h.list_name == "adverse_media"]
    assert len(adverse_hits) >= 1


@pytest.mark.asyncio
async def test_screen_entities_clean_alert_no_adverse(raw_alert: dict[str, Any]) -> None:
    alert = dict(raw_alert)
    alert["screening_hits"] = "No adverse media"
    alert["sanctions_hits"] = "None"
    alert["pep_hits"] = "None"
    alert["actual_activity_30d"] = "Normal operation"
    parsed = parse_alert(alert)
    bundle = await screen_entities(parsed)

    assert bundle.hits == []


@pytest.mark.asyncio
async def test_screen_entities_hit_confidence_in_range(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    bundle = await screen_entities(parsed)

    for hit in bundle.hits:
        assert 0.0 <= hit.match_confidence <= 1.0
        assert hit.entity_name in bundle.entity_names
        assert hit.match_type in ("exact", "fuzzy", "alias", "keyword")
