"""
Step 4: ANALYZE — Deterministic financial crime pattern detection.

Pure Python. No LLM. No external calls. No hallucination possible.

Each detector returns PatternDetection(detected, confidence, evidence[]).
Evidence items are verbatim data points — amounts, dates, counts, etc.
The overall risk score is a weighted sum of per-pattern confidence values.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.pipeline.models import (
    AnalysisResult,
    GatheredData,
    ParsedAlert,
    PatternDetection,
)

# ---------------------------------------------------------------------------
# Thresholds and constants
# ---------------------------------------------------------------------------

# Transactions within this % below reporting threshold trigger structuring check
_STRUCTURING_PROXIMITY_PCT = Decimal("0.20")

# Velocity: ≥2 transactions per calendar day is suspicious
_VELOCITY_THRESHOLD_PER_DAY = 2

# Accounts younger than this are considered new/high-risk
_NEW_ACCOUNT_RISK_DAYS = 90

# FATF grey/black list + FinCEN high-risk jurisdictions (ISO alpha-2)
_HIGH_RISK_JURISDICTIONS = frozenset(
    [
        "AF", "BY", "BI", "CF", "CG", "CD", "CU", "ER", "ET",
        "GN", "GW", "HT", "IR", "IQ", "LY", "ML", "MM", "NI",
        "KP", "RU", "SO", "SS", "SD", "SY", "VE", "YE", "ZW",
    ]
)

# Pattern weights for overall risk score
_PATTERN_WEIGHTS: dict[str, float] = {
    "structuring": 0.35,
    "layering": 0.20,
    "funnel": 0.15,
    "velocity": 0.15,
    "geographic_risk": 0.15,
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze(parsed: ParsedAlert, gathered: GatheredData) -> AnalysisResult:
    """Run all five pattern detectors. Fully deterministic."""
    structuring = _detect_structuring(parsed)
    layering = _detect_layering(parsed, gathered)
    funnel = _detect_funnel(parsed)
    velocity = _detect_velocity(parsed)
    geo_risk = _detect_geographic_risk(parsed, gathered)

    detections = {
        "structuring": structuring,
        "layering": layering,
        "funnel": funnel,
        "velocity": velocity,
        "geographic_risk": geo_risk,
    }

    overall_score = sum(
        _PATTERN_WEIGHTS[k] * d.confidence if d.detected else 0.0
        for k, d in detections.items()
    )

    high_risk = _collect_high_risk_indicators(detections, parsed)
    recommended_action = _recommend_action(overall_score)

    return AnalysisResult(
        structuring=structuring,
        layering=layering,
        funnel=funnel,
        velocity=velocity,
        geographic_risk=geo_risk,
        overall_risk_score=round(min(1.0, overall_score), 3),
        high_risk_indicators=high_risk,
        recommended_action=recommended_action,
    )


# ---------------------------------------------------------------------------
# Pattern detectors
# ---------------------------------------------------------------------------


def _detect_structuring(parsed: ParsedAlert) -> PatternDetection:
    """
    Structuring / smurfing: multiple transactions just below the CTR threshold,
    often across different branches, in close temporal proximity.

    FATF Guidance: Transactions ≥80% of threshold AND multiple occurrences.
    """
    threshold = parsed.reporting_threshold
    lower_bound = threshold * (1 - _STRUCTURING_PROXIMITY_PCT)
    evidence: list[str] = []

    sub_threshold = [
        t for t in parsed.transactions
        if lower_bound <= t.amount < threshold
    ]

    if len(sub_threshold) < 2:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    currency = sub_threshold[0].currency
    amounts_str = ", ".join(f"{t.amount} {currency}" for t in sub_threshold)
    evidence.append(
        f"{len(sub_threshold)} transactions between {lower_bound:.0f}–{threshold:.0f} {currency}: {amounts_str}"
    )

    # Temporal proximity
    dates = sorted(t.date for t in sub_threshold)
    if len(dates) > 1:
        span = (dates[-1] - dates[0]).days
        evidence.append(
            f"Transactions span {span} calendar day(s): {dates[0].isoformat()} to {dates[-1].isoformat()}"
        )

    # Multi-branch increases suspicion significantly
    branches = {t.branch for t in sub_threshold if t.branch}
    if len(branches) > 1:
        evidence.append(
            f"Deposits spread across {len(branches)} different branches: {', '.join(sorted(branches))}"
        )

    # Confidence formula: base 0.55 + per-transaction bonus + branch bonus
    confidence = min(
        1.0,
        0.55
        + 0.08 * (len(sub_threshold) - 1)
        + (0.15 if len(branches) > 1 else 0.0),
    )
    return PatternDetection(detected=True, confidence=round(confidence, 3), evidence=evidence)


def _detect_layering(parsed: ParsedAlert, gathered: GatheredData) -> PatternDetection:
    """
    Layering: movement of funds through intermediaries or accounts to obscure
    the audit trail. Key indicators: unknown counterparties, linked accounts.
    """
    evidence: list[str] = []

    if "unknown" in parsed.counterparties.lower():
        evidence.append(
            "All counterparties listed as 'unknown' — no verifiable origin of funds"
        )

    if gathered.account_relationships:
        n = len(gathered.account_relationships)
        evidence.append(f"{n} linked account relationship(s) identified")

    if not evidence:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    confidence = min(0.75, 0.40 + 0.15 * len(evidence))
    return PatternDetection(detected=True, confidence=round(confidence, 3), evidence=evidence)


def _detect_funnel(parsed: ParsedAlert) -> PatternDetection:
    """
    Funnel / one-directional flow: all transactions are inbound (cash deposits),
    with no outbound payments — inconsistent with legitimate business activity.
    """
    evidence: list[str] = []

    inbound_types = {"cash_deposit", "deposit", "credit"}
    outbound_types = {"wire_transfer", "withdrawal", "payment", "debit", "transfer"}

    inbound = [t for t in parsed.transactions if t.type in inbound_types]
    outbound = [t for t in parsed.transactions if t.type in outbound_types]

    if not inbound:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    if not outbound:
        evidence.append(
            f"{len(inbound)} inbound deposits with zero outbound payments in the transaction window"
        )
        if "no outgoing" in parsed.actual_activity_30d.lower():
            evidence.append(f"Alert confirms: no outgoing payments in 30-day window")

    if not evidence:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    confidence = 0.55 + (0.10 if len(inbound) >= 3 else 0.0)
    return PatternDetection(detected=True, confidence=round(confidence, 3), evidence=evidence)


def _detect_velocity(parsed: ParsedAlert) -> PatternDetection:
    """
    Velocity anomaly: transaction frequency or volume far exceeds expected
    activity profile.
    """
    evidence: list[str] = []

    if not parsed.transactions:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    dates = sorted(t.date for t in parsed.transactions)
    span_days = max(1, (dates[-1] - dates[0]).days + 1)
    txn_per_day = len(parsed.transactions) / span_days

    if txn_per_day >= _VELOCITY_THRESHOLD_PER_DAY:
        evidence.append(
            f"{len(parsed.transactions)} transactions over {span_days} day(s) "
            f"= {txn_per_day:.1f} transactions/day"
        )

    max_expected = _extract_max_amount(parsed.expected_monthly_activity)
    if max_expected and max_expected > 0:
        pct = float(parsed.total_amount / max_expected * 100)
        if pct >= 50:
            currency = parsed.transactions[0].currency if parsed.transactions else "GBP"
            evidence.append(
                f"Volume {parsed.total_amount} {currency} = {pct:.0f}% of declared monthly maximum ({max_expected:.0f})"
            )

    if not evidence:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    confidence = min(0.85, 0.50 + 0.12 * len(evidence))
    return PatternDetection(detected=True, confidence=round(confidence, 3), evidence=evidence)


def _detect_geographic_risk(parsed: ParsedAlert, gathered: GatheredData) -> PatternDetection:
    """
    Geographic risk: connection to FATF high-risk or sanctioned jurisdictions.
    """
    evidence: list[str] = []

    nat = (parsed.nationality or "").upper()
    if nat and nat in _HIGH_RISK_JURISDICTIONS:
        evidence.append(
            f"Beneficial owner nationality {nat} is on the FATF high-risk / sanctioned jurisdictions list"
        )

    for kyc in gathered.kyc_profiles:
        rc = (kyc.registration_country or "").upper()
        if rc and rc in _HIGH_RISK_JURISDICTIONS:
            evidence.append(
                f"Entity '{kyc.entity_name}' registered in high-risk jurisdiction: {rc}"
            )

    if not evidence:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    confidence = min(0.90, 0.60 + 0.15 * (len(evidence) - 1))
    return PatternDetection(detected=True, confidence=round(confidence, 3), evidence=evidence)


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _collect_high_risk_indicators(
    detections: dict[str, PatternDetection],
    parsed: ParsedAlert,
) -> list[str]:
    indicators: list[str] = []

    for d in detections.values():
        if d.detected and d.confidence >= 0.60:
            indicators.extend(d.evidence)

    if parsed.account_age_days < _NEW_ACCOUNT_RISK_DAYS:
        indicators.append(
            f"Account is only {parsed.account_age_days} days old "
            f"(high-risk threshold: <{_NEW_ACCOUNT_RISK_DAYS} days)"
        )

    if parsed.prior_sar_count > 0:
        indicators.append(
            f"Account has {parsed.prior_sar_count} prior Suspicious Activity Report(s)"
        )

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for item in indicators:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _recommend_action(overall_score: float) -> str:
    """Map risk score to recommended action. Deterministic thresholds."""
    if overall_score >= 0.70:
        return "file_sar"
    if overall_score >= 0.50:
        return "escalate"
    if overall_score >= 0.30:
        return "investigate"
    if overall_score >= 0.10:
        return "monitor"
    return "dismiss"


def _extract_max_amount(text: str) -> Decimal | None:
    """Extract the largest monetary amount from a text string."""
    cleaned = re.sub(r"[£$€¥]", "", text)
    matches = re.findall(r"[\d,]+(?:\.\d+)?", cleaned)
    amounts: list[Decimal] = []
    for m in matches:
        try:
            amounts.append(Decimal(m.replace(",", "")))
        except Exception:
            pass
    return max(amounts) if amounts else None
