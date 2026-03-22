"""
Transaction pattern detection — deterministic Python functions.

NO LLM. NO external calls. NO hallucination possible.

Each function is standalone and independently testable:
  - Takes raw data types (transactions, amounts, strings)
  - Returns PatternDetection(detected, confidence, evidence)
  - Evidence is a list of EvidenceFact with txn_id / amount / date / detail

Public API
----------
    structuring_check(transactions, threshold, currency)
    velocity_check(transactions, expected_monthly_max, currency, baseline_daily_avg)
    geographic_risk(transactions, nationality, kyc_profiles)
    funnel_check(transactions, activity_30d_text)
    layering_check(transactions, counterparties_text, account_relationships)

If a check returns detected=False, the narrative WILL NOT mention that pattern.
This is the anti-hallucination guarantee for pattern detection.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.pipeline.models import (
    AccountRelationship,
    EvidenceFact,
    KYCProfile,
    ParsedTransaction,
    PatternDetection,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# FATF grey/black list + FinCEN-designated high-risk jurisdictions (ISO alpha-2)
HIGH_RISK_JURISDICTIONS: frozenset[str] = frozenset(
    [
        "AF", "BY", "BI", "CF", "CG", "CD", "CU", "ER", "ET",
        "GN", "GW", "HT", "IR", "IQ", "LY", "ML", "MM", "NI",
        "KP", "RU", "SO", "SS", "SD", "SY", "VE", "YE", "ZW",
    ]
)

# Transactions within this percentage BELOW the CTR threshold are considered
# structuring candidates (FATF guidance: ≥80% of threshold = suspicious proximity)
STRUCTURING_PROXIMITY_PCT: Decimal = Decimal("0.20")  # 20% below threshold

# Velocity: flag if daily rate ≥ this multiple of the expected baseline
VELOCITY_SPIKE_MULTIPLIER: float = 2.0

# Layering: in-and-out within this many days = rapid movement indicator
LAYERING_RAPID_WINDOW_DAYS: int = 2

_INBOUND_TYPES = frozenset({"cash_deposit", "deposit", "credit"})
_OUTBOUND_TYPES = frozenset({"wire_transfer", "withdrawal", "payment", "debit", "transfer"})


# ---------------------------------------------------------------------------
# 1. structuring_check
# ---------------------------------------------------------------------------


def structuring_check(
    transactions: list[ParsedTransaction],
    threshold: Decimal,
    currency: str,
) -> PatternDetection:
    """
    Detect structuring (smurfing): multiple deposits deliberately kept just
    below the CTR / STR reporting threshold.

    Criteria (FATF Recommendation 20 / FinCEN structuring guidance):
      - ≥ 2 transactions in the band [threshold × 0.80, threshold)
      - Bonus confidence for: more transactions, multi-branch spread,
        tight temporal clustering (≤ 7 days)

    Args:
        transactions: Transaction list from the parsed alert.
        threshold:    Jurisdiction-specific reporting threshold (e.g. 10 000).
        currency:     ISO 4217 code for human-readable evidence strings.

    Returns:
        PatternDetection with one EvidenceFact per qualifying transaction
        plus summary facts for multi-branch / temporal span.
    """
    lower_bound = threshold * (1 - STRUCTURING_PROXIMITY_PCT)
    candidates = [t for t in transactions if lower_bound <= t.amount < threshold]

    if len(candidates) < 2:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    evidence: list[EvidenceFact] = []

    # One fact per qualifying transaction
    for txn in candidates:
        evidence.append(
            EvidenceFact(
                txn_id=txn.txn_id,
                amount=txn.amount,
                date=txn.date.isoformat(),
                detail=(
                    f"Deposit of {txn.amount} {currency} on {txn.date.isoformat()}"
                    f"{f' at {txn.branch}' if txn.branch else ''} — "
                    f"{txn.amount / threshold * 100:.1f}% of the {threshold:,.0f} {currency} reporting threshold"
                ),
            )
        )

    # Temporal span fact
    dates = sorted(t.date for t in candidates)
    span_days = (dates[-1] - dates[0]).days
    evidence.append(
        EvidenceFact(
            txn_id="pattern:structuring:temporal_span",
            amount=None,
            date=None,
            detail=(
                f"{len(candidates)} sub-threshold deposits over {span_days} calendar day(s) "
                f"({dates[0].isoformat()} → {dates[-1].isoformat()})"
            ),
        )
    )

    # Multi-branch fact (strong structuring indicator)
    branches = {t.branch for t in candidates if t.branch}
    if len(branches) > 1:
        evidence.append(
            EvidenceFact(
                txn_id="pattern:structuring:multi_branch",
                amount=None,
                date=None,
                detail=(
                    f"Deposits spread across {len(branches)} different branches: "
                    f"{', '.join(sorted(branches))}"
                ),
            )
        )

    # Confidence: base 0.55 + per-extra-transaction bonus + multi-branch bonus
    confidence = min(
        1.0,
        0.55
        + 0.08 * (len(candidates) - 1)
        + (0.15 if len(branches) > 1 else 0.0),
    )
    return PatternDetection(detected=True, confidence=round(confidence, 3), evidence=evidence)


# ---------------------------------------------------------------------------
# 2. velocity_check
# ---------------------------------------------------------------------------


def velocity_check(
    transactions: list[ParsedTransaction],
    expected_monthly_max: Decimal | None = None,
    currency: str = "",
    baseline_daily_avg: Decimal | None = None,
) -> PatternDetection:
    """
    Detect velocity anomalies: sudden spikes in transaction frequency or
    volume versus the expected or historical baseline.

    Two independent triggers (either alone is sufficient):
      A. Frequency spike: current txns/day ≥ VELOCITY_SPIKE_MULTIPLIER × baseline
      B. Volume spike: period total ≥ 50% of declared monthly maximum

    Args:
        transactions:       Alert transaction list.
        expected_monthly_max: Maximum declared monthly volume (from KYC/onboarding).
        currency:           ISO 4217 code for evidence strings.
        baseline_daily_avg: Historical 90-day average daily volume. When None,
                            derived from expected_monthly_max / 30. When both
                            are None, only the volume-vs-monthly-max check runs.

    Returns:
        PatternDetection. Evidence includes per-transaction facts for the window
        plus summary comparison facts.
    """
    if not transactions:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    evidence: list[EvidenceFact] = []

    dates = sorted(t.date for t in transactions)
    window_days = max(1, (dates[-1] - dates[0]).days + 1)
    total_volume = sum(t.amount for t in transactions)
    current_daily_avg = total_volume / window_days

    # Resolve baseline
    effective_baseline = baseline_daily_avg
    if effective_baseline is None and expected_monthly_max and expected_monthly_max > 0:
        effective_baseline = expected_monthly_max / 30

    # --- Trigger A: frequency / rate spike ---
    if effective_baseline and effective_baseline > 0:
        spike_ratio = float(current_daily_avg / effective_baseline)
        if spike_ratio >= VELOCITY_SPIKE_MULTIPLIER:
            # Per-transaction evidence for the spike window
            for txn in transactions:
                evidence.append(
                    EvidenceFact(
                        txn_id=txn.txn_id,
                        amount=txn.amount,
                        date=txn.date.isoformat(),
                        detail=(
                            f"{txn.amount} {currency} on {txn.date.isoformat()} "
                            f"(part of {window_days}-day window with "
                            f"{spike_ratio:.1f}× normal daily rate)"
                        ),
                    )
                )
            evidence.append(
                EvidenceFact(
                    txn_id="pattern:velocity:rate_spike",
                    amount=None,
                    date=None,
                    detail=(
                        f"Daily average {current_daily_avg:.0f} {currency} over {window_days} day(s) "
                        f"is {spike_ratio:.1f}× the baseline of {effective_baseline:.0f} {currency}/day"
                    ),
                )
            )

    # --- Trigger B: volume vs declared monthly maximum ---
    if expected_monthly_max and expected_monthly_max > 0:
        pct = float(total_volume / expected_monthly_max * 100)
        if pct >= 50:
            evidence.append(
                EvidenceFact(
                    txn_id="pattern:velocity:volume_vs_expected",
                    amount=total_volume,
                    date=None,
                    detail=(
                        f"Total {total_volume} {currency} in {window_days} day(s) = "
                        f"{pct:.0f}% of declared monthly maximum "
                        f"({expected_monthly_max:,.0f} {currency})"
                    ),
                )
            )
            # Include transactions even if rate spike wasn't triggered
            if not any(e.txn_id.startswith("pattern:velocity:rate_spike") for e in evidence):
                for txn in transactions:
                    existing_ids = {e.txn_id for e in evidence}
                    if txn.txn_id not in existing_ids:
                        evidence.append(
                            EvidenceFact(
                                txn_id=txn.txn_id,
                                amount=txn.amount,
                                date=txn.date.isoformat(),
                                detail=(
                                    f"{txn.amount} {currency} on {txn.date.isoformat()} "
                                    f"(contributing to {pct:.0f}% of monthly maximum)"
                                ),
                            )
                        )

    if not evidence:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    confidence = min(0.85, 0.50 + 0.12 * min(len(evidence), 3))
    return PatternDetection(detected=True, confidence=round(confidence, 3), evidence=evidence)


# ---------------------------------------------------------------------------
# 3. geographic_risk
# ---------------------------------------------------------------------------


def geographic_risk(
    transactions: list[ParsedTransaction],
    nationality: str | None = None,
    kyc_profiles: list[KYCProfile] | None = None,
) -> PatternDetection:
    """
    Detect geographic risk: connection to FATF high-risk or sanctioned
    jurisdictions via entity nationality or KYC registration country.

    Args:
        transactions:  Alert transaction list (checked for counterparty country
                       if that field becomes available in future).
        nationality:   Beneficial owner nationality (ISO alpha-2).
        kyc_profiles:  KYC records from Step 2 GATHER (checked for registration_country).

    Returns:
        PatternDetection. Evidence is entity-level facts (txn_id carries a
        semantic identifier like "entity:RU").
    """
    evidence: list[EvidenceFact] = []

    # --- Beneficial owner nationality ---
    nat = (nationality or "").upper().strip()
    if nat and nat in HIGH_RISK_JURISDICTIONS:
        evidence.append(
            EvidenceFact(
                txn_id=f"entity:nationality:{nat}",
                amount=None,
                date=None,
                detail=(
                    f"Beneficial owner nationality {nat} is on the FATF "
                    f"high-risk / sanctioned jurisdictions list"
                ),
            )
        )

    # --- KYC registration countries ---
    for kyc in (kyc_profiles or []):
        rc = (kyc.registration_country or "").upper().strip()
        if rc and rc in HIGH_RISK_JURISDICTIONS:
            evidence.append(
                EvidenceFact(
                    txn_id=f"entity:registration:{rc}:{kyc.entity_name}",
                    amount=None,
                    date=None,
                    detail=(
                        f"Entity '{kyc.entity_name}' registered in "
                        f"high-risk jurisdiction: {rc}"
                    ),
                )
            )

    # --- Transaction-level counterparty jurisdictions (future-proof) ---
    # When transactions carry counterparty_country, check those too.
    # For now this is a no-op — structure is in place for when the field exists.

    if not evidence:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    # Each independent high-risk connection adds 0.15 to base 0.60
    confidence = min(0.90, 0.60 + 0.15 * (len(evidence) - 1))
    return PatternDetection(detected=True, confidence=round(confidence, 3), evidence=evidence)


# ---------------------------------------------------------------------------
# 4. funnel_check
# ---------------------------------------------------------------------------


def funnel_check(
    transactions: list[ParsedTransaction],
    activity_30d_text: str = "",
) -> PatternDetection:
    """
    Detect funnel / one-directional flow: exclusively inbound transactions
    with no corresponding outbound payments — inconsistent with legitimate
    business activity.

    Classic placement/layering indicator: cash is deposited (placed) but
    never legitimately disbursed.

    Args:
        transactions:      Alert transaction list.
        activity_30d_text: Free-text 30-day activity summary from the alert
                           (checked for "no outgoing" / "no outbound" language).

    Returns:
        PatternDetection. Evidence includes one fact per inbound transaction
        plus a "no outbound observed" summary fact.
    """
    inbound = [t for t in transactions if t.type in _INBOUND_TYPES]
    outbound = [t for t in transactions if t.type in _OUTBOUND_TYPES]

    if not inbound or outbound:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    evidence: list[EvidenceFact] = []

    # One fact per inbound transaction
    for txn in inbound:
        evidence.append(
            EvidenceFact(
                txn_id=txn.txn_id,
                amount=txn.amount,
                date=txn.date.isoformat(),
                detail=(
                    f"Inbound {txn.type.replace('_', ' ')} of "
                    f"{txn.amount} {txn.currency} on {txn.date.isoformat()}"
                    f"{f' at {txn.branch}' if txn.branch else ''}"
                ),
            )
        )

    # Summary: zero outbound confirmed
    evidence.append(
        EvidenceFact(
            txn_id="pattern:funnel:no_outbound",
            amount=None,
            date=None,
            detail=(
                f"{len(inbound)} inbound deposit(s) with zero outbound payments in the transaction window"
            ),
        )
    )

    # Corroborated by alert's 30-day activity field
    if any(phrase in activity_30d_text.lower() for phrase in ("no outgoing", "no outbound")):
        evidence.append(
            EvidenceFact(
                txn_id="pattern:funnel:confirmed_30d",
                amount=None,
                date=None,
                detail=f"Alert 30-day summary corroborates: no outgoing payments observed",
            )
        )

    # Confidence: base 0.55, +0.10 for ≥3 inbound, +0.05 if corroborated
    confidence = (
        0.55
        + (0.10 if len(inbound) >= 3 else 0.0)
        + (0.05 if len(evidence) > len(inbound) + 1 else 0.0)
    )
    return PatternDetection(detected=True, confidence=round(min(0.90, confidence), 3), evidence=evidence)


# ---------------------------------------------------------------------------
# 5. layering_check
# ---------------------------------------------------------------------------


def layering_check(
    transactions: list[ParsedTransaction],
    counterparties_text: str = "",
    account_relationships: list[AccountRelationship] | None = None,
) -> PatternDetection:
    """
    Detect layering: rapid movement of funds to obscure origin and audit trail.

    Three independent indicators (any combination raises suspicion):
      A. Rapid in-and-out: inbound followed by outbound within LAYERING_RAPID_WINDOW_DAYS
      B. Unknown / unverifiable counterparties (deliberate opacity)
      C. Multiple linked accounts (complex routing)

    Args:
        transactions:          Alert transaction list.
        counterparties_text:   Free-text counterparty field from the alert.
        account_relationships: Related accounts from Step 2 GATHER.

    Returns:
        PatternDetection. Evidence includes transaction pairs for rapid in/out,
        entity facts for unknown counterparties and linked accounts.
    """
    evidence: list[EvidenceFact] = []

    inbound = sorted([t for t in transactions if t.type in _INBOUND_TYPES], key=lambda t: t.date)
    outbound = sorted([t for t in transactions if t.type in _OUTBOUND_TYPES], key=lambda t: t.date)

    # --- Indicator A: rapid in-and-out pairs ---
    seen_pairs: set[tuple[str, str]] = set()
    for in_txn in inbound:
        for out_txn in outbound:
            gap = abs((out_txn.date - in_txn.date).days)
            if gap <= LAYERING_RAPID_WINDOW_DAYS:
                pair_key = (in_txn.txn_id, out_txn.txn_id)
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    evidence.append(
                        EvidenceFact(
                            txn_id=in_txn.txn_id,
                            amount=in_txn.amount,
                            date=in_txn.date.isoformat(),
                            detail=(
                                f"Inbound {in_txn.amount} {in_txn.currency} on {in_txn.date.isoformat()} "
                                f"followed by outbound {out_txn.amount} {out_txn.currency} "
                                f"on {out_txn.date.isoformat()} — "
                                f"gap of {gap} day(s) (rapid fund movement)"
                            ),
                        )
                    )

    # --- Indicator B: unknown / unverifiable counterparties ---
    if "unknown" in counterparties_text.lower():
        evidence.append(
            EvidenceFact(
                txn_id="pattern:layering:unknown_counterparty",
                amount=None,
                date=None,
                detail=(
                    "All counterparties listed as 'unknown' — "
                    "funds origin cannot be verified, obscuring the audit trail"
                ),
            )
        )

    # --- Indicator C: multiple linked accounts ---
    rels = account_relationships or []
    if rels:
        evidence.append(
            EvidenceFact(
                txn_id="pattern:layering:linked_accounts",
                amount=None,
                date=None,
                detail=(
                    f"{len(rels)} linked account relationship(s) identified — "
                    f"potential multi-hop layering conduit"
                ),
            )
        )

    if not evidence:
        return PatternDetection(detected=False, confidence=0.0, evidence=[])

    # Base confidence by indicator count; rapid in-out pairs add most weight
    rapid_pair_count = len(seen_pairs)
    confidence = min(
        0.85,
        0.35
        + (0.15 * rapid_pair_count)
        + (0.20 if "unknown" in counterparties_text.lower() else 0.0)
        + (0.10 if rels else 0.0),
    )
    return PatternDetection(detected=True, confidence=round(confidence, 3), evidence=evidence)
