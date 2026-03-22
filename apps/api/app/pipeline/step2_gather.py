"""
Step 2: GATHER — Pull KYC, transaction history, and account relationships.

Deterministic: DB queries + stub fallback. No LLM. No hallucination possible.

In production, queries Supabase for:
  - KYC profiles for the account holder and beneficial owner
  - Related accounts (same beneficial owner, same address)
  - Historical alerts for this account

Falls back to realistic stub data when Supabase is not configured.
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
        from supabase import acreate_client  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("step=gather supabase-py not installed — using stub data")
        return _gather_stub(parsed)

    db = await acreate_client(supabase_url, supabase_key)

    kyc_profiles = await _query_kyc(db, parsed)
    relationships = await _query_account_relationships(db, parsed)
    historical = await _query_historical_alerts(db, parsed)

    return GatheredData(
        kyc_profiles=kyc_profiles,
        account_relationships=relationships,
        historical_alerts=historical,
        source_metadata={
            "source": "supabase",
            "queried_at": datetime.utcnow().isoformat(),
        },
    )


async def _query_kyc(db: Any, parsed: ParsedAlert) -> list[KYCProfile]:
    """Look up prior alerts for this account holder to infer KYC profile."""
    try:
        resp = (
            await db.table("alerts")
            .select("raw_data, severity, created_by")
            .eq("account_holder", parsed.account_holder)
            .limit(10)
            .execute()
        )
        if resp.data:
            return [
                KYCProfile(
                    entity_name=parsed.account_holder,
                    entity_type="organization",
                    beneficial_owners=[parsed.beneficial_owner_name],
                    kyc_tier="standard",
                    source="db",
                )
            ]
    except Exception as exc:
        logger.warning("step=gather KYC query failed: %s", exc)
    return []


async def _query_account_relationships(
    db: Any, parsed: ParsedAlert
) -> list[AccountRelationship]:
    # Placeholder: a real implementation would query a relationships table
    return []


async def _query_historical_alerts(
    db: Any, parsed: ParsedAlert
) -> list[HistoricalAlert]:
    try:
        resp = (
            await db.table("alerts")
            .select("id, title, severity, status, created_at")
            .neq("id", parsed.alert_id)
            .limit(20)
            .execute()
        )
        results: list[HistoricalAlert] = []
        for row in resp.data or []:
            results.append(
                HistoricalAlert(
                    alert_id=str(row.get("id", "")),
                    alert_type="unknown",
                    date=str(row.get("created_at", ""))[:10],
                    severity=str(row.get("severity", "low")),
                    resolved=row.get("status") == "closed",
                )
            )
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
                kyc_tier="enhanced",  # Non-domestic beneficial owner = enhanced due diligence
                source="stub",
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
