"""
Tests for Step 1: PARSE

No LLM. No external calls. Pure deterministic parsing.
These tests run in milliseconds with no dependencies.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.pipeline.step1_parse import (
    _parse_beneficial_owner,
    _parse_transactions,
    parse_alert,
)


# ---------------------------------------------------------------------------
# parse_alert — happy path
# ---------------------------------------------------------------------------


def test_parse_alert_basic(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)

    assert parsed.alert_id == "AML-2026-00147"
    assert parsed.alert_type == "structuring"
    assert parsed.account_holder == "Nexbridge Trading Ltd"
    assert parsed.jurisdiction == "GB"
    assert parsed.account_age_days == 47
    assert parsed.prior_sar_count == 0


def test_parse_alert_transactions(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)

    assert parsed.transaction_count == 4
    assert len(parsed.transactions) == 4

    amounts = [t.amount for t in parsed.transactions]
    assert Decimal("9800") in amounts
    assert Decimal("9750") in amounts
    assert Decimal("9900") in amounts
    assert Decimal("9600") in amounts

    for txn in parsed.transactions:
        assert txn.currency == "GBP"
        assert txn.type == "cash_deposit"
        assert txn.branch is not None


def test_parse_alert_totals(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)

    expected_total = Decimal("9800") + Decimal("9750") + Decimal("9900") + Decimal("9600")
    assert parsed.total_amount == expected_total


def test_parse_alert_reporting_threshold_gb(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    assert parsed.reporting_threshold == Decimal("10000")


def test_parse_alert_beneficial_owner(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)

    assert parsed.beneficial_owner_name == "Mikhail Voronov"
    assert parsed.nationality == "RU"
    assert parsed.dob == date(1974, 8, 22)


def test_parse_alert_generated_at(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)
    assert parsed.generated_at.year == 2026
    assert parsed.generated_at.month == 3
    assert parsed.generated_at.day == 15


def test_parse_alert_screening_fields(raw_alert: dict[str, Any]) -> None:
    parsed = parse_alert(raw_alert)

    assert "Nexbridge" in parsed.screening_hits_raw
    assert "VAT fraud" in parsed.screening_hits_raw
    assert parsed.sanctions_hits_raw == "None"
    assert parsed.pep_hits_raw == "None"


# ---------------------------------------------------------------------------
# parse_alert — edge cases
# ---------------------------------------------------------------------------


def test_parse_alert_transactions_as_list(raw_alert: dict[str, Any]) -> None:
    """Transactions can be provided as a Python list, not only a JSON string."""
    alert = dict(raw_alert)
    alert["transactions"] = [
        {"date": "2026-03-10", "amount": 5000, "currency": "USD", "type": "cash_deposit"},
    ]
    parsed = parse_alert(alert)
    assert parsed.transaction_count == 1
    assert parsed.transactions[0].amount == Decimal("5000")


def test_parse_alert_missing_transactions(raw_alert: dict[str, Any]) -> None:
    alert = dict(raw_alert)
    del alert["transactions"]
    parsed = parse_alert(alert)
    assert parsed.transaction_count == 0
    assert parsed.total_amount == Decimal("0")


def test_parse_alert_invalid_generated_at(raw_alert: dict[str, Any]) -> None:
    """Invalid generated_at falls back to utcnow without raising."""
    alert = dict(raw_alert)
    alert["generated_at"] = "not-a-date"
    parsed = parse_alert(alert)
    assert isinstance(parsed.generated_at, datetime)


def test_parse_alert_unknown_jurisdiction_uses_default(raw_alert: dict[str, Any]) -> None:
    alert = dict(raw_alert)
    alert["jurisdiction"] = "XX"
    parsed = parse_alert(alert)
    assert parsed.reporting_threshold == Decimal("10000")


def test_parse_alert_jurisdiction_normalized_uppercase(raw_alert: dict[str, Any]) -> None:
    alert = dict(raw_alert)
    alert["jurisdiction"] = "gb"  # lowercase input
    parsed = parse_alert(alert)
    assert parsed.jurisdiction == "GB"


def test_parse_alert_no_beneficial_owner(raw_alert: dict[str, Any]) -> None:
    alert = dict(raw_alert)
    alert["beneficial_owner"] = ""
    parsed = parse_alert(alert)
    assert parsed.beneficial_owner_name == ""
    assert parsed.nationality is None
    assert parsed.dob is None


# ---------------------------------------------------------------------------
# _parse_beneficial_owner unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected_name, expected_nat, expected_dob",
    [
        (
            "Mikhail Voronov (DOB: 1974-08-22, nationality: RU)",
            "Mikhail Voronov",
            "RU",
            date(1974, 8, 22),
        ),
        ("Jane Smith", "Jane Smith", None, None),
        (
            "Ali Hassan (nationality: AE)",
            "Ali Hassan",
            "AE",
            None,
        ),
        (
            "John Doe (DOB: 1990-01-01, nationality: US)",
            "John Doe",
            "US",
            date(1990, 1, 1),
        ),
        ("", "", None, None),
    ],
)
def test_parse_beneficial_owner(
    raw: str,
    expected_name: str,
    expected_nat: str | None,
    expected_dob: date | None,
) -> None:
    name, nat, dob = _parse_beneficial_owner(raw)
    assert name == expected_name
    assert nat == expected_nat
    assert dob == expected_dob


# ---------------------------------------------------------------------------
# _parse_transactions unit tests
# ---------------------------------------------------------------------------


def test_parse_transactions_from_json_string() -> None:
    json_str = json.dumps([
        {"date": "2026-01-01", "amount": 1000, "currency": "GBP", "type": "cash_deposit"},
    ])
    txns = _parse_transactions(json_str)
    assert len(txns) == 1
    assert txns[0].amount == Decimal("1000")
    assert txns[0].currency == "GBP"
    assert txns[0].date == date(2026, 1, 1)


def test_parse_transactions_from_list() -> None:
    txns = _parse_transactions([
        {"date": "2026-01-01", "amount": "9999.99", "currency": "eur", "type": "wire"},
    ])
    assert txns[0].amount == Decimal("9999.99")
    assert txns[0].currency == "EUR"  # normalized to uppercase


def test_parse_transactions_skips_invalid_entries() -> None:
    txns = _parse_transactions([
        {"date": "2026-01-01", "amount": 100, "currency": "GBP", "type": "cash_deposit"},
        "not a dict",
        None,
    ])
    assert len(txns) == 1


def test_parse_transactions_bad_json_returns_empty() -> None:
    txns = _parse_transactions("{bad json}")
    assert txns == []


def test_parse_transactions_non_list_returns_empty() -> None:
    txns = _parse_transactions({"amount": 1000})
    assert txns == []


def test_parse_transactions_optional_branch() -> None:
    txns = _parse_transactions([
        {"date": "2026-01-01", "amount": 500, "currency": "GBP", "type": "cash_deposit"},
    ])
    assert txns[0].branch is None
