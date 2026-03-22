"""
Tests for Step 2: GATHER

Tests the stub path (no DB required). The stub is the primary path for
local development and CI. DB path is exercised only in integration tests
against a live Supabase instance.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.pipeline.step1_parse import parse_alert
from app.pipeline.step2_gather import _gather_stub, gather_data


# ---------------------------------------------------------------------------
# Stub path tests (no DB — always runs)
# ---------------------------------------------------------------------------


def test_stub_produces_kyc_profiles(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)

    assert len(gathered.kyc_profiles) >= 1

    # Company profile
    company = next((k for k in gathered.kyc_profiles if k.entity_type == "organization"), None)
    assert company is not None
    assert company.entity_name == "Nexbridge Trading Ltd"
    assert company.registration_country == "GB"
    assert "standard" in company.kyc_tier.lower()


def test_stub_creates_person_profile_for_beneficial_owner(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)

    person = next((k for k in gathered.kyc_profiles if k.entity_type == "person"), None)
    assert person is not None
    assert person.entity_name == "Mikhail Voronov"
    assert person.registration_country == "RU"
    assert person.kyc_tier == "enhanced"  # non-domestic BO = EDD


def test_stub_source_metadata(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)

    assert gathered.source_metadata["source"] == "stub"
    assert "queried_at" in gathered.source_metadata


def test_stub_empty_relationships_and_history(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)

    assert gathered.account_relationships == []
    assert gathered.historical_alerts == []


def test_stub_no_beneficial_owner(raw_alert: dict[str, Any]) -> None:
    """When beneficial_owner is empty, only the company profile is created."""
    alert = dict(raw_alert)
    alert["beneficial_owner"] = ""
    parsed = parse_alert(alert)
    gathered = _gather_stub(parsed)

    assert all(k.entity_type == "organization" for k in gathered.kyc_profiles)


# ---------------------------------------------------------------------------
# gather_data without DB falls back to stub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gather_data_no_db_uses_stub(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = await gather_data(parsed)  # no supabase_url/key

    assert gathered.source_metadata["source"] == "stub"
    assert len(gathered.kyc_profiles) >= 1
