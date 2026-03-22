"""
Tests for Step 4: ANALYZE

Fully deterministic. No LLM, no external calls.
Tests every pattern detector individually and the aggregate result.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from app.pipeline.step1_parse import parse_alert
from app.pipeline.step2_gather import _gather_stub
from app.pipeline.step4_analyze import (
    _detect_funnel,
    _detect_geographic_risk,
    _detect_layering,
    _detect_structuring,
    _detect_velocity,
    _extract_max_amount,
    _recommend_action,
    analyze,
)
from app.pipeline.models import GatheredData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gathered_empty() -> GatheredData:
    return GatheredData(
        kyc_profiles=[],
        account_relationships=[],
        historical_alerts=[],
        source_metadata={"source": "test"},
    )


# ---------------------------------------------------------------------------
# Structuring detector
# ---------------------------------------------------------------------------


def test_structuring_detected_on_canonical_alert(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    result = _detect_structuring(parsed)

    assert result.detected is True
    assert result.confidence >= 0.70  # 4 transactions + multi-branch
    assert len(result.evidence) >= 2
    # Evidence must cite actual amounts
    assert any("9800" in e or "9750" in e or "9900" in e or "9600" in e for e in result.evidence)


def test_structuring_multi_branch_increases_confidence(raw_alert: dict[str, Any]) -> None:
    """Same amounts, single branch vs multi-branch — multi-branch should score higher."""
    parsed_multi = parse_alert(raw_alert)  # 4 different branches
    result_multi = _detect_structuring(parsed_multi)

    alert_single = dict(raw_alert)
    alert_single["transactions"] = json.dumps([
        {"date": "2026-03-10", "amount": 9800, "currency": "GBP", "type": "cash_deposit", "branch": "London City"},
        {"date": "2026-03-11", "amount": 9750, "currency": "GBP", "type": "cash_deposit", "branch": "London City"},
        {"date": "2026-03-12", "amount": 9900, "currency": "GBP", "type": "cash_deposit", "branch": "London City"},
        {"date": "2026-03-13", "amount": 9600, "currency": "GBP", "type": "cash_deposit", "branch": "London City"},
    ])
    parsed_single = parse_alert(alert_single)
    result_single = _detect_structuring(parsed_single)

    assert result_multi.confidence > result_single.confidence


def test_structuring_not_detected_on_single_transaction(raw_alert: dict[str, Any]) -> None:
    alert = dict(raw_alert)
    alert["transactions"] = json.dumps([
        {"date": "2026-03-10", "amount": 9800, "currency": "GBP", "type": "cash_deposit"},
    ])
    parsed = parse_alert(alert)
    result = _detect_structuring(parsed)
    assert result.detected is False


def test_structuring_not_detected_above_threshold(raw_alert: dict[str, Any]) -> None:
    """Transactions above the threshold are NOT structuring."""
    alert = dict(raw_alert)
    alert["transactions"] = json.dumps([
        {"date": "2026-03-10", "amount": 15000, "currency": "GBP", "type": "cash_deposit"},
        {"date": "2026-03-11", "amount": 12000, "currency": "GBP", "type": "cash_deposit"},
    ])
    parsed = parse_alert(alert)
    result = _detect_structuring(parsed)
    assert result.detected is False


def test_structuring_not_detected_far_below_threshold(raw_alert: dict[str, Any]) -> None:
    """Small transactions well below the threshold are NOT structuring."""
    alert = dict(raw_alert)
    alert["transactions"] = json.dumps([
        {"date": "2026-03-10", "amount": 1000, "currency": "GBP", "type": "cash_deposit"},
        {"date": "2026-03-11", "amount": 1500, "currency": "GBP", "type": "cash_deposit"},
    ])
    parsed = parse_alert(alert)
    result = _detect_structuring(parsed)
    assert result.detected is False


def test_structuring_evidence_is_non_empty_strings(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    result = _detect_structuring(parsed)
    assert all(isinstance(e, str) and e for e in result.evidence)


# ---------------------------------------------------------------------------
# Layering detector
# ---------------------------------------------------------------------------


def test_layering_detected_on_unknown_counterparty(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _make_gathered_empty()
    result = _detect_layering(parsed, gathered)

    assert result.detected is True
    assert any("unknown" in e.lower() for e in result.evidence)


def test_layering_not_detected_on_known_counterparty(raw_alert: dict[str, Any]) -> None:
    alert = dict(raw_alert)
    alert["counterparties"] = "ABC Suppliers Ltd, XYZ Corp"
    parsed = parse_alert(alert)
    gathered = _make_gathered_empty()
    result = _detect_layering(parsed, gathered)
    assert result.detected is False


# ---------------------------------------------------------------------------
# Funnel detector
# ---------------------------------------------------------------------------


def test_funnel_detected_on_canonical_alert(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    result = _detect_funnel(parsed)

    assert result.detected is True
    assert result.confidence >= 0.55
    assert any("outgoing" in e.lower() or "outbound" in e.lower() for e in result.evidence)


def test_funnel_not_detected_when_outbound_exists(raw_alert: dict[str, Any]) -> None:
    alert = dict(raw_alert)
    alert["transactions"] = json.dumps([
        {"date": "2026-03-10", "amount": 9800, "currency": "GBP", "type": "cash_deposit"},
        {"date": "2026-03-11", "amount": 5000, "currency": "GBP", "type": "wire_transfer"},
    ])
    parsed = parse_alert(alert)
    result = _detect_funnel(parsed)
    assert result.detected is False


# ---------------------------------------------------------------------------
# Velocity detector
# ---------------------------------------------------------------------------


def test_velocity_detected_on_canonical_alert(raw_alert: dict[str, Any]) -> None:
    # 4 txns over 4 days = 1/day (below freq threshold), but volume is 78% of monthly max
    parsed = parse_alert(raw_alert)
    result = _detect_velocity(parsed)

    assert result.detected is True
    assert result.confidence >= 0.50
    # Evidence cites either frequency or volume anomaly
    assert len(result.evidence) >= 1


def test_velocity_not_detected_on_single_transaction(raw_alert: dict[str, Any]) -> None:
    alert = dict(raw_alert)
    alert["transactions"] = json.dumps([
        {"date": "2026-03-10", "amount": 100, "currency": "GBP", "type": "cash_deposit"},
    ])
    alert["expected_monthly_activity"] = "Max GBP 10,000/month"
    parsed = parse_alert(alert)
    result = _detect_velocity(parsed)
    assert result.detected is False


# ---------------------------------------------------------------------------
# Geographic risk detector
# ---------------------------------------------------------------------------


def test_geographic_risk_detected_russian_nationality(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _make_gathered_empty()
    result = _detect_geographic_risk(parsed, gathered)

    assert result.detected is True
    assert result.confidence >= 0.60
    assert any("RU" in e for e in result.evidence)


def test_geographic_risk_not_detected_low_risk_nationality(raw_alert: dict[str, Any]) -> None:
    alert = dict(raw_alert)
    alert["beneficial_owner"] = "John Smith (DOB: 1980-01-01, nationality: GB)"
    parsed = parse_alert(alert)
    gathered = _make_gathered_empty()
    result = _detect_geographic_risk(parsed, gathered)
    assert result.detected is False


# ---------------------------------------------------------------------------
# Full analyze() — aggregate result
# ---------------------------------------------------------------------------


def test_analyze_canonical_alert_high_risk(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    result = analyze(parsed, gathered)

    assert result.overall_risk_score >= 0.60
    assert result.recommended_action in ("escalate", "file_sar")
    assert result.structuring.detected is True
    assert result.geographic_risk.detected is True


def test_analyze_risk_score_in_range(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    result = analyze(parsed, gathered)

    assert 0.0 <= result.overall_risk_score <= 1.0


def test_analyze_high_risk_indicators_non_empty(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    result = analyze(parsed, gathered)

    assert len(result.high_risk_indicators) >= 1


def test_analyze_high_risk_indicators_are_strings(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    result = analyze(parsed, gathered)

    for indicator in result.high_risk_indicators:
        assert isinstance(indicator, str) and indicator


def test_analyze_new_account_in_high_risk_indicators(raw_alert: dict[str, Any]) -> None:
    """47-day-old account should appear in high_risk_indicators."""
    parsed = parse_alert(raw_alert)
    gathered = _gather_stub(parsed)
    result = analyze(parsed, gathered)

    assert any("47" in i or "day" in i.lower() for i in result.high_risk_indicators)


def test_analyze_low_risk_alert_recommends_dismiss() -> None:
    raw = {
        "alert_id": "AML-TEST-LOW",
        "alert_type": "unusual",
        "generated_at": "2026-01-01T00:00:00Z",
        "account_number": "0000-0000",
        "account_holder": "Clean Corp Ltd",
        "jurisdiction": "GB",
        "transactions": json.dumps([
            {"date": "2026-01-01", "amount": 500, "currency": "GBP", "type": "wire_transfer"},
        ]),
        "counterparties": "Known supplier, UK Ltd",
        "account_age_days": 500,
        "prior_sar_count": 0,
        "beneficial_owner": "Jane Doe (DOB: 1980-05-01, nationality: GB)",
        "business_type": "Retail",
        "expected_monthly_activity": "Max GBP 10,000",
        "actual_activity_30d": "Normal payments to suppliers",
        "screening_hits": "No hits",
        "sanctions_hits": "None",
        "pep_hits": "None",
    }
    parsed = parse_alert(raw)
    gathered = GatheredData(
        kyc_profiles=[],
        account_relationships=[],
        historical_alerts=[],
        source_metadata={"source": "test"},
    )
    result = analyze(parsed, gathered)
    assert result.recommended_action in ("dismiss", "monitor")
    assert result.overall_risk_score < 0.40


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Business payments, max GBP 50,000/month", Decimal("50000")),
        ("Up to £100,000 per month", Decimal("100000")),
        ("$10,000 limit", Decimal("10000")),
        ("no numbers here", None),
        ("", None),
    ],
)
def test_extract_max_amount(text: str, expected: Decimal | None) -> None:
    assert _extract_max_amount(text) == expected


@pytest.mark.parametrize(
    "score, expected_action",
    [
        (0.80, "file_sar"),
        (0.70, "file_sar"),
        (0.65, "escalate"),
        (0.50, "escalate"),
        (0.40, "investigate"),
        (0.30, "investigate"),
        (0.15, "monitor"),
        (0.05, "dismiss"),
        (0.00, "dismiss"),
    ],
)
def test_recommend_action(score: float, expected_action: str) -> None:
    assert _recommend_action(score) == expected_action
