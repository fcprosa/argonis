"""Shared fixtures for the evidence-first pipeline tests."""

from __future__ import annotations

import json
from typing import Any

import pytest


@pytest.fixture
def raw_alert() -> dict[str, Any]:
    """Hardcoded structuring/smurfing alert (AML-2026-00147, UK jurisdiction)."""
    return {
        "alert_id": "AML-2026-00147",
        "alert_type": "structuring",
        "generated_at": "2026-03-15T09:14:00Z",
        "account_number": "4892-7731-0012",
        "account_holder": "Nexbridge Trading Ltd",
        "jurisdiction": "GB",
        "transactions": json.dumps(
            [
                {"date": "2026-03-10", "amount": 9800, "currency": "GBP", "type": "cash_deposit", "branch": "London City"},
                {"date": "2026-03-11", "amount": 9750, "currency": "GBP", "type": "cash_deposit", "branch": "Canary Wharf"},
                {"date": "2026-03-12", "amount": 9900, "currency": "GBP", "type": "cash_deposit", "branch": "Stratford"},
                {"date": "2026-03-13", "amount": 9600, "currency": "GBP", "type": "cash_deposit", "branch": "Hackney"},
            ]
        ),
        "counterparties": "Multiple cash deposits, no single counterparty identified. Originator listed as unknown on all transactions.",
        "account_age_days": 47,
        "prior_sar_count": 0,
        "beneficial_owner": "Mikhail Voronov (DOB: 1974-08-22, nationality: RU)",
        "business_type": "Import/export trading company",
        "expected_monthly_activity": "Business payments to EU suppliers, max GBP 50,000/month",
        "actual_activity_30d": "GBP 39,050 in cash deposits across 4 branches in 4 consecutive days. No outgoing payments observed.",
        "screening_hits": "Nexbridge Trading Ltd — 1 adverse media hit: alleged involvement in VAT fraud scheme (source: FT, 2023-09-14)",
        "sanctions_hits": "None",
        "pep_hits": "None",
    }
