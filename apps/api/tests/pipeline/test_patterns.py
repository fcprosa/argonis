"""
Tests for app.pipeline.patterns — standalone pattern detection functions.

Each function is tested in isolation with raw inputs (no ParsedAlert).
These are unit tests for the core pattern detection logic.

NO LLM. NO external calls. Fully deterministic.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.pipeline.models import (
    AccountRelationship,
    EvidenceFact,
    KYCProfile,
    ParsedTransaction,
)
from app.pipeline.patterns import (
    HIGH_RISK_JURISDICTIONS,
    LAYERING_RAPID_WINDOW_DAYS,
    STRUCTURING_PROXIMITY_PCT,
    VELOCITY_SPIKE_MULTIPLIER,
    funnel_check,
    geographic_risk,
    layering_check,
    structuring_check,
    velocity_check,
)

# ---------------------------------------------------------------------------
# Fixtures — raw ParsedTransaction lists (no ParsedAlert dependency)
# ---------------------------------------------------------------------------

GBP = "GBP"
USD = "USD"
THRESHOLD_GBP = Decimal("10000")


def _txn(
    txn_id: str,
    amount: float | int,
    txn_date: str,
    currency: str = GBP,
    txn_type: str = "cash_deposit",
    branch: str | None = None,
    counterparty: str | None = None,
) -> ParsedTransaction:
    return ParsedTransaction(
        txn_id=txn_id,
        date=date.fromisoformat(txn_date),
        amount=Decimal(str(amount)),
        currency=currency,
        type=txn_type,
        branch=branch,
        counterparty=counterparty,
    )


# Four canonical sub-threshold deposits (the AML-2026-00147 pattern)
CANONICAL_STRUCTURING_TXNS = [
    _txn("alert-txn-000", 9800, "2026-03-10", branch="London City"),
    _txn("alert-txn-001", 9750, "2026-03-11", branch="Canary Wharf"),
    _txn("alert-txn-002", 9900, "2026-03-12", branch="Stratford"),
    _txn("alert-txn-003", 9600, "2026-03-13", branch="Hackney"),
]


# ===========================================================================
# structuring_check
# ===========================================================================


class TestStructuringCheck:

    def test_detected_on_four_sub_threshold_deposits(self) -> None:
        result = structuring_check(CANONICAL_STRUCTURING_TXNS, THRESHOLD_GBP, GBP)

        assert result.detected is True
        assert result.confidence >= 0.70
        assert len(result.evidence) >= 2  # per-txn facts + span + multi-branch

    def test_each_qualifying_txn_gets_its_own_evidence_fact(self) -> None:
        result = structuring_check(CANONICAL_STRUCTURING_TXNS, THRESHOLD_GBP, GBP)

        txn_facts = [e for e in result.evidence if e.amount is not None]
        assert len(txn_facts) == 4

        amounts = {e.amount for e in txn_facts}
        assert Decimal("9800") in amounts
        assert Decimal("9750") in amounts
        assert Decimal("9900") in amounts
        assert Decimal("9600") in amounts

    def test_txn_id_propagated_from_input(self) -> None:
        result = structuring_check(CANONICAL_STRUCTURING_TXNS, THRESHOLD_GBP, GBP)

        txn_ids = {e.txn_id for e in result.evidence if e.amount is not None}
        assert "alert-txn-000" in txn_ids
        assert "alert-txn-003" in txn_ids

    def test_date_field_populated_on_txn_facts(self) -> None:
        result = structuring_check(CANONICAL_STRUCTURING_TXNS, THRESHOLD_GBP, GBP)

        txn_facts = [e for e in result.evidence if e.amount is not None]
        assert all(e.date is not None for e in txn_facts)
        dates = {e.date for e in txn_facts}
        assert "2026-03-10" in dates

    def test_multi_branch_fact_included(self) -> None:
        result = structuring_check(CANONICAL_STRUCTURING_TXNS, THRESHOLD_GBP, GBP)

        branch_fact = next(
            (e for e in result.evidence if "branch" in e.detail.lower()), None
        )
        assert branch_fact is not None
        assert branch_fact.amount is None  # summary fact, not a txn
        assert "London City" in branch_fact.detail or "4" in branch_fact.detail

    def test_multi_branch_higher_confidence_than_single_branch(self) -> None:
        single_branch = [
            _txn(f"t{i}", amt, f"2026-03-{10 + i:02d}", branch="London City")
            for i, amt in enumerate([9800, 9750, 9900, 9600])
        ]
        multi = structuring_check(CANONICAL_STRUCTURING_TXNS, THRESHOLD_GBP, GBP)
        single = structuring_check(single_branch, THRESHOLD_GBP, GBP)

        assert multi.confidence > single.confidence

    def test_temporal_span_fact_included(self) -> None:
        result = structuring_check(CANONICAL_STRUCTURING_TXNS, THRESHOLD_GBP, GBP)

        span_fact = next(
            (e for e in result.evidence if "day" in e.detail.lower() and e.amount is None
             and "branch" not in e.detail.lower()),
            None,
        )
        assert span_fact is not None

    def test_not_detected_single_transaction(self) -> None:
        result = structuring_check(
            [_txn("t0", 9800, "2026-03-10")], THRESHOLD_GBP, GBP
        )
        assert result.detected is False
        assert result.evidence == []

    def test_not_detected_above_threshold(self) -> None:
        txns = [
            _txn("t0", 15000, "2026-03-10"),
            _txn("t1", 12000, "2026-03-11"),
        ]
        assert structuring_check(txns, THRESHOLD_GBP, GBP).detected is False

    def test_not_detected_well_below_threshold(self) -> None:
        txns = [
            _txn("t0", 1000, "2026-03-10"),
            _txn("t1", 1500, "2026-03-11"),
        ]
        assert structuring_check(txns, THRESHOLD_GBP, GBP).detected is False

    def test_not_detected_empty_transactions(self) -> None:
        assert structuring_check([], THRESHOLD_GBP, GBP).detected is False

    def test_confidence_increases_with_more_transactions(self) -> None:
        two_txns = CANONICAL_STRUCTURING_TXNS[:2]
        four_txns = CANONICAL_STRUCTURING_TXNS

        r2 = structuring_check(two_txns, THRESHOLD_GBP, GBP)
        r4 = structuring_check(four_txns, THRESHOLD_GBP, GBP)

        assert r4.confidence >= r2.confidence

    def test_detail_contains_threshold_percentage(self) -> None:
        result = structuring_check(CANONICAL_STRUCTURING_TXNS, THRESHOLD_GBP, GBP)

        txn_facts = [e for e in result.evidence if e.amount is not None]
        # 9800 / 10000 = 98.0%
        assert any("98.0%" in e.detail for e in txn_facts)

    def test_works_with_usd_threshold(self) -> None:
        txns = [
            _txn("t0", 9500, "2026-01-01", currency="USD"),
            _txn("t1", 9200, "2026-01-02", currency="USD"),
        ]
        result = structuring_check(txns, Decimal("10000"), "USD")
        assert result.detected is True
        assert all("USD" in e.detail for e in result.evidence if e.amount is not None)


# ===========================================================================
# velocity_check
# ===========================================================================


class TestVelocityCheck:

    def test_detected_by_volume_vs_monthly_max(self) -> None:
        # 39,050 GBP over 4 days vs 50,000/month max → 78% of monthly max
        result = velocity_check(
            CANONICAL_STRUCTURING_TXNS,
            expected_monthly_max=Decimal("50000"),
            currency=GBP,
        )
        assert result.detected is True
        assert any("78%" in e.detail for e in result.evidence)

    def test_volume_fact_has_total_amount(self) -> None:
        result = velocity_check(
            CANONICAL_STRUCTURING_TXNS,
            expected_monthly_max=Decimal("50000"),
            currency=GBP,
        )
        vol_fact = next(
            (e for e in result.evidence if "monthly" in e.detail.lower()), None
        )
        assert vol_fact is not None
        assert vol_fact.amount == Decimal("39050")

    def test_detected_by_rate_spike_vs_baseline(self) -> None:
        # Baseline = 100 GBP/day; current rate = 9800 GBP/day → 98× spike
        txns = [_txn("t0", 9800, "2026-03-10")]
        result = velocity_check(
            txns,
            expected_monthly_max=Decimal("3000"),   # 100/day baseline
            currency=GBP,
            baseline_daily_avg=Decimal("100"),
        )
        assert result.detected is True
        assert any("rate_spike" in e.txn_id for e in result.evidence)

    def test_rate_spike_evidence_includes_all_transactions(self) -> None:
        txns = [
            _txn("t0", 9800, "2026-03-10"),
            _txn("t1", 9750, "2026-03-11"),
        ]
        result = velocity_check(
            txns,
            currency=GBP,
            baseline_daily_avg=Decimal("100"),  # triggers rate spike
        )
        txn_facts = [e for e in result.evidence if e.amount is not None]
        txn_ids = {e.txn_id for e in txn_facts}
        assert "t0" in txn_ids
        assert "t1" in txn_ids

    def test_not_detected_small_volume(self) -> None:
        txns = [_txn("t0", 100, "2026-03-10")]
        result = velocity_check(
            txns,
            expected_monthly_max=Decimal("10000"),
            currency=GBP,
        )
        assert result.detected is False

    def test_not_detected_empty_transactions(self) -> None:
        assert velocity_check([], expected_monthly_max=Decimal("50000"), currency=GBP).detected is False

    def test_not_detected_without_any_baseline(self) -> None:
        # No expected_monthly_max and no baseline_daily_avg → can't trigger
        txns = [_txn("t0", 9800, "2026-03-10")]
        result = velocity_check(txns, currency=GBP)
        assert result.detected is False

    def test_confidence_in_range(self) -> None:
        result = velocity_check(
            CANONICAL_STRUCTURING_TXNS,
            expected_monthly_max=Decimal("50000"),
            currency=GBP,
        )
        assert 0.0 <= result.confidence <= 1.0

    def test_txn_facts_have_amount_and_date(self) -> None:
        result = velocity_check(
            CANONICAL_STRUCTURING_TXNS,
            expected_monthly_max=Decimal("50000"),
            currency=GBP,
        )
        txn_facts = [e for e in result.evidence if e.amount is not None and e.date is not None]
        assert len(txn_facts) >= 1


# ===========================================================================
# geographic_risk
# ===========================================================================


class TestGeographicRisk:

    def test_detected_russian_nationality(self) -> None:
        result = geographic_risk(CANONICAL_STRUCTURING_TXNS, nationality="RU")
        assert result.detected is True
        assert result.confidence >= 0.60

    def test_evidence_fact_for_nationality(self) -> None:
        result = geographic_risk([], nationality="RU")

        nat_facts = [e for e in result.evidence if "nationality" in e.txn_id]
        assert len(nat_facts) == 1
        assert nat_facts[0].amount is None
        assert nat_facts[0].date is None
        assert "RU" in nat_facts[0].detail

    def test_txn_id_includes_jurisdiction_code(self) -> None:
        result = geographic_risk([], nationality="IR")
        assert any("IR" in e.txn_id for e in result.evidence)

    def test_detected_via_kyc_registration_country(self) -> None:
        kyc = KYCProfile(
            entity_name="Shadow Corp",
            entity_type="organization",
            registration_country="KP",  # North Korea
            source="stub",
        )
        result = geographic_risk([], nationality="GB", kyc_profiles=[kyc])
        assert result.detected is True
        assert any("KP" in e.detail for e in result.evidence)

    def test_both_nationality_and_kyc_increases_confidence(self) -> None:
        kyc = KYCProfile(
            entity_name="Shadow Corp",
            entity_type="organization",
            registration_country="SY",
            source="stub",
        )
        result_both = geographic_risk([], nationality="RU", kyc_profiles=[kyc])
        result_nat_only = geographic_risk([], nationality="RU")

        assert result_both.confidence > result_nat_only.confidence

    def test_not_detected_low_risk_nationality(self) -> None:
        result = geographic_risk([], nationality="GB")
        assert result.detected is False

    def test_not_detected_none_nationality_no_kyc(self) -> None:
        result = geographic_risk([], nationality=None)
        assert result.detected is False

    def test_not_detected_empty_string_nationality(self) -> None:
        result = geographic_risk([], nationality="")
        assert result.detected is False

    def test_not_detected_low_risk_kyc_country(self) -> None:
        kyc = KYCProfile(
            entity_name="Safe Corp",
            entity_type="organization",
            registration_country="DE",
            source="stub",
        )
        result = geographic_risk([], nationality=None, kyc_profiles=[kyc])
        assert result.detected is False

    def test_confidence_capped_at_0_90(self) -> None:
        kycs = [
            KYCProfile(entity_name=f"Corp{i}", entity_type="organization",
                       registration_country="RU", source="stub")
            for i in range(10)
        ]
        result = geographic_risk([], nationality="KP", kyc_profiles=kycs)
        assert result.confidence <= 0.90

    @pytest.mark.parametrize("country", ["RU", "IR", "KP", "SY", "VE", "BY"])
    def test_known_high_risk_jurisdictions_detected(self, country: str) -> None:
        result = geographic_risk([], nationality=country)
        assert result.detected is True, f"{country} should be high-risk"

    def test_all_high_risk_jurisdictions_constant_populated(self) -> None:
        assert len(HIGH_RISK_JURISDICTIONS) >= 20


# ===========================================================================
# funnel_check
# ===========================================================================


class TestFunnelCheck:

    def test_detected_on_all_inbound(self) -> None:
        result = funnel_check(
            CANONICAL_STRUCTURING_TXNS,
            activity_30d_text="No outgoing payments observed.",
        )
        assert result.detected is True
        assert result.confidence >= 0.55

    def test_one_fact_per_inbound_transaction(self) -> None:
        result = funnel_check(CANONICAL_STRUCTURING_TXNS)
        txn_facts = [e for e in result.evidence if e.amount is not None]
        assert len(txn_facts) == 4

    def test_txn_ids_on_inbound_facts(self) -> None:
        result = funnel_check(CANONICAL_STRUCTURING_TXNS)
        txn_facts = [e for e in result.evidence if e.amount is not None]
        assert all(e.txn_id.startswith("alert-txn-") for e in txn_facts)

    def test_no_outbound_summary_fact_included(self) -> None:
        result = funnel_check(CANONICAL_STRUCTURING_TXNS)
        summary = next(e for e in result.evidence if e.txn_id == "pattern:funnel:no_outbound")
        assert "zero outbound" in summary.detail.lower()

    def test_30d_corroboration_fact_added_when_present(self) -> None:
        result = funnel_check(
            CANONICAL_STRUCTURING_TXNS,
            activity_30d_text="GBP 39,050 in deposits. No outgoing payments observed.",
        )
        confirm_fact = next(
            (e for e in result.evidence if e.txn_id == "pattern:funnel:confirmed_30d"), None
        )
        assert confirm_fact is not None

    def test_30d_corroboration_not_added_when_absent(self) -> None:
        result = funnel_check(CANONICAL_STRUCTURING_TXNS, activity_30d_text="Normal activity")
        confirm_fact = next(
            (e for e in result.evidence if e.txn_id == "pattern:funnel:confirmed_30d"), None
        )
        assert confirm_fact is None

    def test_not_detected_when_outbound_present(self) -> None:
        txns = [
            _txn("t0", 9800, "2026-03-10", txn_type="cash_deposit"),
            _txn("t1", 5000, "2026-03-11", txn_type="wire_transfer"),
        ]
        assert funnel_check(txns).detected is False

    def test_not_detected_empty_transactions(self) -> None:
        assert funnel_check([]).detected is False

    def test_not_detected_only_outbound(self) -> None:
        txns = [
            _txn("t0", 5000, "2026-03-10", txn_type="wire_transfer"),
            _txn("t1", 3000, "2026-03-11", txn_type="payment"),
        ]
        assert funnel_check(txns).detected is False

    def test_higher_confidence_for_three_or_more_inbound(self) -> None:
        two = CANONICAL_STRUCTURING_TXNS[:2]
        four = CANONICAL_STRUCTURING_TXNS

        r2 = funnel_check(two)
        r4 = funnel_check(four)

        assert r4.confidence >= r2.confidence

    def test_facts_have_amount_and_date(self) -> None:
        result = funnel_check(CANONICAL_STRUCTURING_TXNS)
        txn_facts = [e for e in result.evidence if e.amount is not None]
        assert all(e.date is not None for e in txn_facts)


# ===========================================================================
# layering_check
# ===========================================================================


class TestLayeringCheck:

    def test_detected_on_unknown_counterparty(self) -> None:
        result = layering_check(
            CANONICAL_STRUCTURING_TXNS,
            counterparties_text="Originator listed as unknown on all transactions.",
        )
        assert result.detected is True
        assert any("unknown" in e.detail.lower() for e in result.evidence)

    def test_unknown_counterparty_fact_has_no_amount(self) -> None:
        result = layering_check(
            [],
            counterparties_text="unknown counterparty",
        )
        fact = next(e for e in result.evidence if "unknown" in e.detail.lower())
        assert fact.amount is None
        assert fact.date is None
        assert fact.txn_id == "pattern:layering:unknown_counterparty"

    def test_detected_on_rapid_in_and_out(self) -> None:
        txns = [
            _txn("t0", 9800, "2026-03-10", txn_type="cash_deposit"),
            _txn("t1", 9500, "2026-03-11", txn_type="wire_transfer"),  # 1-day gap
        ]
        result = layering_check(txns, counterparties_text="known supplier")
        assert result.detected is True

        rapid_facts = [e for e in result.evidence if e.amount == Decimal("9800")]
        assert len(rapid_facts) >= 1
        assert any("rapid" in e.detail.lower() or "gap" in e.detail.lower() for e in rapid_facts)

    def test_rapid_in_out_fact_carries_inbound_txn_id(self) -> None:
        txns = [
            _txn("inbound-001", 9800, "2026-03-10", txn_type="cash_deposit"),
            _txn("outbound-001", 9500, "2026-03-11", txn_type="wire_transfer"),
        ]
        result = layering_check(txns, counterparties_text="known")
        rapid_facts = [e for e in result.evidence if e.txn_id == "inbound-001"]
        assert len(rapid_facts) == 1

    def test_no_rapid_in_out_when_gap_exceeds_window(self) -> None:
        txns = [
            _txn("t0", 9800, "2026-03-01", txn_type="cash_deposit"),
            _txn("t1", 9500, "2026-03-10", txn_type="wire_transfer"),  # 9-day gap
        ]
        result = layering_check(txns, counterparties_text="known supplier")
        # Only unknown-counterparty indicator is absent; gap too wide for rapid movement
        rapid_facts = [e for e in result.evidence if e.amount == Decimal("9800")]
        assert len(rapid_facts) == 0

    def test_detected_via_linked_accounts(self) -> None:
        rel = AccountRelationship(
            source_customer_id="1111",
            related_customer_id="2222",
            relationship_type="beneficial_owner",
            source="stub",
        )
        result = layering_check([], counterparties_text="known", account_relationships=[rel])
        assert result.detected is True
        linked_fact = next(
            e for e in result.evidence if e.txn_id == "pattern:layering:linked_accounts"
        )
        assert "1" in linked_fact.detail  # "1 linked account"

    def test_not_detected_clean_known_counterparty_no_outbound(self) -> None:
        # All inbound, known counterparty, no linked accounts → layering NOT triggered
        result = layering_check(
            CANONICAL_STRUCTURING_TXNS,
            counterparties_text="ABC Suppliers Ltd",
            account_relationships=[],
        )
        assert result.detected is False

    def test_not_detected_empty_inputs(self) -> None:
        result = layering_check([], counterparties_text="")
        assert result.detected is False

    def test_confidence_increases_with_multiple_indicators(self) -> None:
        rel = AccountRelationship(
            source_customer_id="X", related_customer_id="Y",
            relationship_type="beneficial_owner", source="stub",
        )
        # Unknown counterparty only
        r1 = layering_check([], counterparties_text="unknown")
        # Unknown + linked account
        r2 = layering_check([], counterparties_text="unknown", account_relationships=[rel])
        assert r2.confidence >= r1.confidence

    def test_confidence_in_range(self) -> None:
        result = layering_check(
            CANONICAL_STRUCTURING_TXNS,
            counterparties_text="unknown",
        )
        assert 0.0 <= result.confidence <= 1.0

    def test_rapid_window_constant_is_positive(self) -> None:
        assert LAYERING_RAPID_WINDOW_DAYS > 0


# ===========================================================================
# Cross-cutting: EvidenceFact structure
# ===========================================================================


class TestEvidenceFactStructure:
    """Verify that every pattern function returns well-formed EvidenceFact objects."""

    def test_all_facts_have_non_empty_txn_id(self) -> None:
        for check_fn, kwargs in [
            (structuring_check, {"transactions": CANONICAL_STRUCTURING_TXNS, "threshold": THRESHOLD_GBP, "currency": GBP}),
            (velocity_check, {"transactions": CANONICAL_STRUCTURING_TXNS, "expected_monthly_max": Decimal("50000"), "currency": GBP}),
            (geographic_risk, {"transactions": [], "nationality": "RU"}),
            (funnel_check, {"transactions": CANONICAL_STRUCTURING_TXNS}),
            (layering_check, {"transactions": [], "counterparties_text": "unknown"}),
        ]:
            result = check_fn(**kwargs)  # type: ignore[operator]
            for fact in result.evidence:
                assert fact.txn_id, f"{check_fn.__name__}: txn_id must not be empty"

    def test_all_facts_have_non_empty_detail(self) -> None:
        for check_fn, kwargs in [
            (structuring_check, {"transactions": CANONICAL_STRUCTURING_TXNS, "threshold": THRESHOLD_GBP, "currency": GBP}),
            (funnel_check, {"transactions": CANONICAL_STRUCTURING_TXNS}),
            (layering_check, {"transactions": [], "counterparties_text": "unknown"}),
            (geographic_risk, {"transactions": [], "nationality": "RU"}),
        ]:
            result = check_fn(**kwargs)  # type: ignore[operator]
            for fact in result.evidence:
                assert fact.detail.strip(), f"{check_fn.__name__}: detail must not be empty"

    def test_confidence_always_in_0_to_1_range(self) -> None:
        results = [
            structuring_check(CANONICAL_STRUCTURING_TXNS, THRESHOLD_GBP, GBP),
            velocity_check(CANONICAL_STRUCTURING_TXNS, Decimal("50000"), GBP),
            geographic_risk([], "RU"),
            funnel_check(CANONICAL_STRUCTURING_TXNS),
            layering_check([], "unknown"),
        ]
        for r in results:
            assert 0.0 <= r.confidence <= 1.0

    def test_not_detected_always_returns_empty_evidence(self) -> None:
        results = [
            structuring_check([], THRESHOLD_GBP, GBP),
            velocity_check([], currency=GBP),
            geographic_risk([], nationality="GB"),
            funnel_check([]),
            layering_check([], ""),
        ]
        for r in results:
            assert r.detected is False
            assert r.evidence == []
