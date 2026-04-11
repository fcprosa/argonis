"""
Step 2: GATHER — Pull KYC, transaction history, and account relationships.

Deterministic: DB queries + stub fallback. No LLM. No hallucination possible.

Data source priority:
  1. kyc_profiles table (real onboarding data from POST /kyc/profiles)
  2. account_relationships table (real relationship graph)
  3. Stub fallback when Supabase is not configured (test/dev only)

When no KYC profile is found for a customer, the step DOES NOT fabricate one.
Instead it returns a minimal synthetic profile with ``is_synthetic=True`` and
``source="missing_kyc"``, plus an explicit ``data_gaps`` entry that propagates
all the way to the narrative.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from app.pipeline.models import (
    AccountRelationship,
    GatheredData,
    HistoricalAlert,
    KYCProfile,
    ParsedAlert,
)

logger = logging.getLogger(__name__)

_KYC_MISSING_GAP_TEMPLATE = (
    "KYC_PROFILE_MISSING: no profile for customer '{customer_id}' in kyc_profiles. "
    "Investigation will proceed with transaction data only. "
    "Manual KYC review required before filing."
)


async def gather_data(
    parsed: ParsedAlert,
    supabase_url: str = "",
    supabase_key: str = "",
) -> GatheredData:
    """Pull KYC and relationship data. Falls back to stubs when DB not configured."""
    if supabase_url and supabase_key:
        return await _gather_from_db(parsed, supabase_url, supabase_key)
    logger.warning("step=gather Supabase not configured — using stub data")
    return _gather_stub(parsed)


# ---------------------------------------------------------------------------
# DB path
# ---------------------------------------------------------------------------


async def _gather_from_db(
    parsed: ParsedAlert,
    supabase_url: str,
    supabase_key: str,
) -> GatheredData:
    try:
        from supabase import acreate_client
    except ImportError:
        logger.warning("step=gather supabase-py not installed — using stub data")
        return _gather_stub(parsed)

    db = await acreate_client(supabase_url, supabase_key)

    customer_id = parsed.account_holder
    data_gaps: list[str] = []

    kyc_profiles = await _query_kyc_profiles(db, customer_id, parsed)
    if not kyc_profiles:
        gap_msg = _KYC_MISSING_GAP_TEMPLATE.format(customer_id=customer_id)
        data_gaps.append(gap_msg)
        logger.warning("step=gather %s", gap_msg)
        kyc_profiles = [_build_synthetic_profile(parsed)]

    relationships, rel_available = await _query_account_relationships(
        db, customer_id,
    )
    historical = await _query_historical_alerts(db, parsed)

    return GatheredData(
        kyc_profiles=kyc_profiles,
        account_relationships=relationships,
        historical_alerts=historical,
        source_metadata={
            "source": "supabase",
            "queried_at": datetime.utcnow().isoformat(),
        },
        data_gaps=data_gaps,
        relationships_available=rel_available,
    )


async def _query_kyc_profiles(
    db: Any,
    customer_id: str,
    parsed: ParsedAlert,
) -> list[KYCProfile]:
    """Look up KYC profiles from the kyc_profiles table."""
    try:
        resp = await (
            db.table("kyc_profiles")
            .select("*")
            .eq("legal_name", customer_id)
            .limit(5)
            .execute()
        )

        if not resp.data:
            resp = await (
                db.table("kyc_profiles")
                .select("*")
                .eq("customer_id", customer_id)
                .limit(5)
                .execute()
            )

        if not resp.data:
            return []

        profiles: list[KYCProfile] = []
        for row in resp.data:
            bo_raw = row.get("beneficial_owners") or []
            bo_names = [
                bo.get("name", "") for bo in bo_raw if isinstance(bo, dict)
            ]

            profiles.append(
                KYCProfile(
                    entity_name=row.get("legal_name", customer_id),
                    entity_type=(
                        "organization"
                        if row.get("customer_type") in ("business", "trust")
                        else "person"
                    ),
                    registration_number=row.get("business_registration_number"),
                    registration_country=(
                        row.get("business_jurisdiction")
                        or row.get("country_of_residence")
                    ),
                    directors=[],
                    beneficial_owners=bo_names,
                    kyc_tier=_risk_to_tier(row.get("risk_rating", "medium")),
                    last_reviewed=(
                        date.fromisoformat(str(row["last_reviewed_at"])[:10])
                        if row.get("last_reviewed_at")
                        else None
                    ),
                    source="kyc_profiles",
                    is_synthetic=False,
                    pep_status=row.get("pep_status"),
                    risk_rating=row.get("risk_rating"),
                    occupation=row.get("occupation"),
                    source_of_funds=row.get("source_of_funds"),
                    date_of_birth=(
                        date.fromisoformat(str(row["date_of_birth"]))
                        if row.get("date_of_birth")
                        else None
                    ),
                    nationality=row.get("nationality"),
                    country_of_residence=row.get("country_of_residence"),
                )
            )
        return profiles

    except Exception as exc:
        logger.warning("step=gather KYC query failed: %s", exc)
        return []


def _risk_to_tier(risk_rating: str) -> str:
    return {
        "low": "standard",
        "medium": "standard",
        "high": "enhanced",
        "prohibited": "enhanced",
    }.get(risk_rating, "standard")


def _build_synthetic_profile(parsed: ParsedAlert) -> KYCProfile:
    """Minimal profile when no real KYC exists — flagged as synthetic."""
    return KYCProfile(
        entity_name=parsed.account_holder,
        entity_type="organization" if parsed.business_type else "person",
        registration_country=parsed.jurisdiction,
        beneficial_owners=(
            [parsed.beneficial_owner_name] if parsed.beneficial_owner_name else []
        ),
        kyc_tier="unknown",
        source="missing_kyc",
        is_synthetic=True,
        nationality=parsed.nationality,
        date_of_birth=parsed.dob,
    )


async def _query_account_relationships(
    db: Any,
    customer_id: str,
) -> tuple[list[AccountRelationship], bool]:
    """Query account_relationships for any edges involving this customer.

    Returns (relationships, was_queryable).
    """
    try:
        resp_source = await (
            db.table("account_relationships")
            .select("*")
            .eq("source_customer_id", customer_id)
            .limit(50)
            .execute()
        )
        resp_related = await (
            db.table("account_relationships")
            .select("*")
            .eq("related_customer_id", customer_id)
            .limit(50)
            .execute()
        )

        relationships: list[AccountRelationship] = []
        seen: set[str] = set()

        for row in (resp_source.data or []) + (resp_related.data or []):
            key = f"{row['source_customer_id']}:{row['related_customer_id']}:{row['relationship_type']}"
            if key in seen:
                continue
            seen.add(key)
            relationships.append(
                AccountRelationship(
                    source_customer_id=row["source_customer_id"],
                    related_customer_id=row["related_customer_id"],
                    relationship_type=row["relationship_type"],
                    confidence=float(row.get("confidence", 1.0)),
                    source="account_relationships",
                )
            )
        return relationships, True

    except Exception as exc:
        logger.warning("step=gather relationships query failed: %s", exc)
        return [], False


async def _query_historical_alerts(
    db: Any, parsed: ParsedAlert
) -> list[HistoricalAlert]:
    """Prior alerts for the same customer (``raw_data.account_holder``), excluding this alert.

    ``parsed.alert_id`` is the external alert reference string from the payload, not the
    DB UUID — it must not be compared to ``alerts.id``.
    """
    try:
        resp = (
            await db.table("alerts")
            .select("id, title, severity, status, created_at, raw_data")
            .contains("raw_data", {"account_holder": parsed.account_holder})
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        results: list[HistoricalAlert] = []
        for row in resp.data or []:
            rd = row.get("raw_data") or {}
            if rd.get("alert_id") == parsed.alert_id:
                continue
            results.append(
                HistoricalAlert(
                    alert_id=str(row.get("id", "")),
                    alert_type="unknown",
                    date=str(row.get("created_at", ""))[:10],
                    severity=str(row.get("severity", "low")),
                    resolved=row.get("status") == "closed",
                )
            )
            if len(results) >= 10:
                break
        return results
    except Exception as exc:
        logger.warning("step=gather historical alerts query failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Stub path (no DB)
# ---------------------------------------------------------------------------


def _gather_stub(parsed: ParsedAlert) -> GatheredData:
    """Return realistic stub data for testing without a live DB."""
    profiles: list[KYCProfile] = [
        KYCProfile(
            entity_name=parsed.account_holder,
            entity_type="organization",
            registration_number="12345678",
            registration_country=parsed.jurisdiction,
            directors=[parsed.beneficial_owner_name] if parsed.beneficial_owner_name else [],
            beneficial_owners=[parsed.beneficial_owner_name] if parsed.beneficial_owner_name else [],
            kyc_tier="standard",
            last_reviewed=date(2026, 1, 15),
            source="stub",
        )
    ]

    if parsed.beneficial_owner_name:
        profiles.append(
            KYCProfile(
                entity_name=parsed.beneficial_owner_name,
                entity_type="person",
                registration_country=parsed.nationality,
                kyc_tier="enhanced",
                source="stub",
                nationality=parsed.nationality,
                date_of_birth=parsed.dob,
            )
        )

    return GatheredData(
        kyc_profiles=profiles,
        account_relationships=[],
        historical_alerts=[],
        source_metadata={
            "source": "stub",
            "queried_at": datetime.utcnow().isoformat(),
        },
    )
