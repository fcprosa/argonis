"""
Step 4: ANALYZE — Orchestrates the deterministic pattern detectors.

Each detector lives in patterns.py and operates on raw data types.
This module extracts the right data from ParsedAlert / GatheredData
and passes it to each detector, then aggregates the results.

NO LLM. NO external calls. NO hallucination possible.
If a pattern is not detected here, it will not appear in the narrative.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.pipeline.models import (
    AnalysisResult,
    EvidenceFact,
    GatheredData,
    ParsedAlert,
    PatternDetection,
)
from app.pipeline.patterns import (
    funnel_check,
    geographic_risk,
    layering_check,
    structuring_check,
    velocity_check,
)

# ---------------------------------------------------------------------------
# Constants (kept here for the aggregation / recommendation logic)
# ---------------------------------------------------------------------------

_NEW_ACCOUNT_RISK_DAYS = 90

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
    """Run all five pattern detectors and return a single AnalysisResult."""
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
# Thin wrappers: extract data from ParsedAlert / GatheredData → patterns.py
# ---------------------------------------------------------------------------


def _detect_structuring(parsed: ParsedAlert) -> PatternDetection:
    currency = parsed.transactions[0].currency if parsed.transactions else "GBP"
    return structuring_check(
        transactions=parsed.transactions,
        threshold=parsed.reporting_threshold,
        currency=currency,
    )


def _detect_layering(parsed: ParsedAlert, gathered: GatheredData) -> PatternDetection:
    return layering_check(
        transactions=parsed.transactions,
        counterparties_text=parsed.counterparties,
        account_relationships=gathered.account_relationships,
    )


def _detect_funnel(parsed: ParsedAlert) -> PatternDetection:
    return funnel_check(
        transactions=parsed.transactions,
        activity_30d_text=parsed.actual_activity_30d,
    )


def _detect_velocity(parsed: ParsedAlert) -> PatternDetection:
    currency = parsed.transactions[0].currency if parsed.transactions else "GBP"
    max_expected = _extract_max_amount(parsed.expected_monthly_activity)
    return velocity_check(
        transactions=parsed.transactions,
        expected_monthly_max=max_expected,
        currency=currency,
    )


def _detect_geographic_risk(parsed: ParsedAlert, gathered: GatheredData) -> PatternDetection:
    return geographic_risk(
        transactions=parsed.transactions,
        nationality=parsed.nationality,
        kyc_profiles=gathered.kyc_profiles,
    )


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _collect_high_risk_indicators(
    detections: dict[str, PatternDetection],
    parsed: ParsedAlert,
) -> list[str]:
    """Return a deduplicated list of high-confidence indicator strings."""
    indicators: list[str] = []

    for d in detections.values():
        if d.detected and d.confidence >= 0.60:
            indicators.extend(ev.detail for ev in d.evidence)

    if parsed.account_age_days < _NEW_ACCOUNT_RISK_DAYS:
        indicators.append(
            f"Account is only {parsed.account_age_days} days old "
            f"(high-risk threshold: <{_NEW_ACCOUNT_RISK_DAYS} days)"
        )

    if parsed.prior_sar_count > 0:
        indicators.append(
            f"Account has {parsed.prior_sar_count} prior Suspicious Activity Report(s)"
        )

    seen: set[str] = set()
    unique: list[str] = []
    for item in indicators:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _recommend_action(overall_score: float) -> str:
    """Deterministic action recommendation from risk score."""
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
    """Extract the largest monetary amount from a free-text string."""
    cleaned = re.sub(r"[£$€¥]", "", text)
    matches = re.findall(r"[\d,]+(?:\.\d+)?", cleaned)
    amounts: list[Decimal] = []
    for m in matches:
        try:
            amounts.append(Decimal(m.replace(",", "")))
        except Exception:
            pass
    return max(amounts) if amounts else None
