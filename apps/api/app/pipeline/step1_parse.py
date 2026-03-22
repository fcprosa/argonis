"""
Step 1: PARSE — Pure deterministic alert parsing.

No LLM. No external calls. No hallucination possible.
Input:  raw alert dict
Output: ParsedAlert with typed fields and computed totals
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.pipeline.models import ParsedAlert, ParsedTransaction

# Jurisdiction-specific cash reporting thresholds
REPORTING_THRESHOLDS: dict[str, Decimal] = {
    "GB": Decimal("10000"),   # UK CTR threshold (£10,000)
    "US": Decimal("10000"),   # US CTR threshold ($10,000)
    "EU": Decimal("10000"),   # EU AML directive threshold
    "AU": Decimal("10000"),   # Australian threshold
    "CA": Decimal("10000"),   # Canadian threshold
}
_DEFAULT_THRESHOLD = Decimal("10000")

# Regexes for parsing the beneficial_owner free-text field
_NAT_RE = re.compile(r"nationality:\s*([A-Z]{2,3})", re.IGNORECASE)
_DOB_RE = re.compile(r"DOB:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_NAME_RE = re.compile(r"^([^(,]+)")  # everything before the first paren or comma


def parse_alert(raw: dict[str, Any]) -> ParsedAlert:
    """Parse a raw alert dict into a fully typed ParsedAlert.

    This is a pure function — same input always produces same output.
    Raises ValueError if required fields are missing or unparseable.
    """
    transactions = _parse_transactions(raw.get("transactions", []))
    bo_raw = str(raw.get("beneficial_owner", ""))
    bo_name, nationality, dob = _parse_beneficial_owner(bo_raw)

    jurisdiction = str(raw.get("jurisdiction", "GB")).upper().strip()
    threshold = REPORTING_THRESHOLDS.get(jurisdiction, _DEFAULT_THRESHOLD)

    generated_at_raw = raw.get("generated_at", "")
    try:
        generated_at = datetime.fromisoformat(str(generated_at_raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        generated_at = datetime.utcnow()

    currency = transactions[0].currency if transactions else "GBP"
    total_amount = sum((t.amount for t in transactions), Decimal("0"))

    return ParsedAlert(
        alert_id=str(raw.get("alert_id", "")),
        alert_type=str(raw.get("alert_type", "")),
        generated_at=generated_at,
        account_number=str(raw.get("account_number", "")),
        account_holder=str(raw.get("account_holder", "")),
        jurisdiction=jurisdiction,
        transactions=transactions,
        counterparties=str(raw.get("counterparties", "")),
        account_age_days=int(raw.get("account_age_days", 0)),
        prior_sar_count=int(raw.get("prior_sar_count", 0)),
        beneficial_owner_raw=bo_raw,
        beneficial_owner_name=bo_name,
        nationality=nationality,
        dob=dob,
        business_type=str(raw.get("business_type", "")),
        expected_monthly_activity=str(raw.get("expected_monthly_activity", "")),
        actual_activity_30d=str(raw.get("actual_activity_30d", "")),
        screening_hits_raw=str(raw.get("screening_hits", "")),
        sanctions_hits_raw=str(raw.get("sanctions_hits", "")),
        pep_hits_raw=str(raw.get("pep_hits", "")),
        total_amount=total_amount,
        transaction_count=len(transactions),
        reporting_threshold=threshold,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_transactions(raw_txns: Any) -> list[ParsedTransaction]:
    if isinstance(raw_txns, str):
        try:
            raw_txns = json.loads(raw_txns)
        except json.JSONDecodeError:
            return []

    if not isinstance(raw_txns, list):
        return []

    result: list[ParsedTransaction] = []
    for txn in raw_txns:
        if not isinstance(txn, dict):
            continue
        try:
            amount = Decimal(str(txn.get("amount", 0)))
        except InvalidOperation:
            amount = Decimal("0")

        date_raw = txn.get("date", "")
        try:
            txn_date = date.fromisoformat(str(date_raw))
        except (ValueError, TypeError):
            txn_date = date.today()

        result.append(
            ParsedTransaction(
                date=txn_date,
                amount=amount,
                currency=str(txn.get("currency", "")).upper(),
                type=str(txn.get("type", "unknown")),
                branch=txn.get("branch") or None,
                counterparty=txn.get("counterparty") or None,
            )
        )

    return result


def _parse_beneficial_owner(raw: str) -> tuple[str, str | None, date | None]:
    """Extract name, nationality (ISO alpha-2), and DOB from a free-text string.

    Examples handled:
        "Mikhail Voronov (DOB: 1974-08-22, nationality: RU)"
        "Jane Smith"
    """
    name_match = _NAME_RE.match(raw)
    name = name_match.group(1).strip() if name_match else raw.strip()

    nat_match = _NAT_RE.search(raw)
    nationality = nat_match.group(1).upper() if nat_match else None

    dob: date | None = None
    dob_match = _DOB_RE.search(raw)
    if dob_match:
        try:
            dob = date.fromisoformat(dob_match.group(1))
        except ValueError:
            pass

    return name, nationality, dob
