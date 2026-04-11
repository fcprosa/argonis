"""
Golden-set KYC profile fixtures.

Inserts matching kyc_profiles rows for each golden-set test case so that
Step 2 GATHER finds real KYC data instead of returning synthetic profiles.

Each profile matches the ``account_holder`` field in the corresponding
fixture JSON.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from supabase import AsyncClient

KYC_PROFILES: dict[str, dict[str, Any]] = {
    "TESTCASE_Ridgeline Consulting LLC": {
        "customer_id": "TESTCASE_Ridgeline Consulting LLC",
        "legal_name": "TESTCASE_Ridgeline Consulting LLC",
        "customer_type": "business",
        "nationality": "US",
        "country_of_residence": "US",
        "business_registration_number": "NY-2024-88321",
        "business_jurisdiction": "US",
        "occupation": "Management consulting",
        "source_of_funds": "Consulting fees from corporate clients",
        "pep_status": "clear",
        "risk_rating": "medium",
        "onboarded_at": "2026-01-15T00:00:00Z",
        "onboarding_source": "exchange_signup",
        "last_reviewed_at": "2026-03-01T00:00:00Z",
        "beneficial_owners": [
            {"name": "TESTCASE_Thomas J. Mercer", "dob": "1985-03-14",
             "nationality": "US", "ownership_pct": 100, "role": "sole_owner"},
        ],
    },
    "TESTCASE_Zenith Global Imports Inc": {
        "customer_id": "TESTCASE_Zenith Global Imports Inc",
        "legal_name": "TESTCASE_Zenith Global Imports Inc",
        "customer_type": "business",
        "nationality": "IR",
        "country_of_residence": "US",
        "business_registration_number": "CA-2023-45210",
        "business_jurisdiction": "US",
        "occupation": "Textile and garment importer",
        "source_of_funds": "Import/export trade revenue",
        "pep_status": "not_screened",
        "risk_rating": "high",
        "onboarded_at": "2025-06-20T00:00:00Z",
        "onboarding_source": "manual",
        "last_reviewed_at": "2025-12-10T00:00:00Z",
        "beneficial_owners": [
            {"name": "TESTCASE_Reza Karimi", "dob": "1978-11-02",
             "nationality": "IR", "ownership_pct": 85, "role": "director"},
        ],
    },
    "TESTCASE_Maple Ridge Realty Partners LLC": {
        "customer_id": "TESTCASE_Maple Ridge Realty Partners LLC",
        "legal_name": "TESTCASE_Maple Ridge Realty Partners LLC",
        "customer_type": "business",
        "nationality": "US",
        "country_of_residence": "US",
        "business_registration_number": "FL-2025-11245",
        "business_jurisdiction": "US",
        "occupation": "Real estate holding company",
        "source_of_funds": "Real estate investment returns",
        "pep_status": "clear",
        "risk_rating": "medium",
        "onboarded_at": "2025-09-01T00:00:00Z",
        "onboarding_source": "exchange_signup",
        "last_reviewed_at": "2026-02-15T00:00:00Z",
        "beneficial_owners": [
            {"name": "TESTCASE_Daniel R. Whitmore", "dob": "1990-06-22",
             "nationality": "US", "ownership_pct": 60, "role": "managing_member"},
        ],
    },
    "TESTCASE_Ironclad Fabrication Corp": {
        "customer_id": "TESTCASE_Ironclad Fabrication Corp",
        "legal_name": "TESTCASE_Ironclad Fabrication Corp",
        "customer_type": "business",
        "nationality": "US",
        "country_of_residence": "US",
        "business_registration_number": "TX-2024-77902",
        "business_jurisdiction": "US",
        "occupation": "Metal fabrication and welding services",
        "source_of_funds": "Government and private-sector contracts",
        "pep_status": "clear",
        "risk_rating": "low",
        "onboarded_at": "2024-04-01T00:00:00Z",
        "onboarding_source": "manual",
        "last_reviewed_at": "2025-10-20T00:00:00Z",
        "beneficial_owners": [
            {"name": "TESTCASE_Harold E. Briggs", "dob": "1972-09-08",
             "nationality": "US", "ownership_pct": 100, "role": "sole_owner"},
        ],
    },
    "TESTCASE_Golden Lotus Trading Co": {
        "customer_id": "TESTCASE_Golden Lotus Trading Co",
        "legal_name": "TESTCASE_Golden Lotus Trading Co",
        "customer_type": "business",
        "nationality": "MM",
        "country_of_residence": "US",
        "business_registration_number": "WA-2025-33781",
        "business_jurisdiction": "MM",
        "occupation": "Gemstone and hardwood importer",
        "source_of_funds": "Commodity trade revenue",
        "pep_status": "not_screened",
        "risk_rating": "high",
        "onboarded_at": "2025-11-01T00:00:00Z",
        "onboarding_source": "api_import",
        "last_reviewed_at": None,
        "beneficial_owners": [
            {"name": "TESTCASE_Kyaw Min Tun", "dob": "1980-05-19",
             "nationality": "MM", "ownership_pct": 90, "role": "director"},
        ],
    },
    "TESTCASE_Heron Logistics Ltd": {
        "customer_id": "TESTCASE_Heron Logistics Ltd",
        "legal_name": "TESTCASE_Heron Logistics Ltd",
        "customer_type": "business",
        "nationality": "US",
        "country_of_residence": "US",
        "business_registration_number": "IL-2025-55210",
        "business_jurisdiction": "US",
        "occupation": "Freight logistics",
        "source_of_funds": "Shipping and logistics services",
        "pep_status": "clear",
        "risk_rating": "medium",
        "onboarded_at": "2025-10-15T00:00:00Z",
        "onboarding_source": "exchange_signup",
        "last_reviewed_at": "2026-03-10T00:00:00Z",
        "beneficial_owners": [
            {"name": "TESTCASE_Patricia M. Dalton", "dob": "1979-08-22",
             "nationality": "US", "ownership_pct": 100, "role": "sole_owner"},
        ],
    },
}


async def insert_kyc_for_fixture(
    db: AsyncClient,
    organization_id: str,
    account_holder: str,
) -> str | None:
    """Insert a KYC profile for the given account_holder. Returns the profile ID or None."""
    profile_data = KYC_PROFILES.get(account_holder)
    if not profile_data:
        return None

    row = {
        "organization_id": organization_id,
        **profile_data,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = await (
        db.table("kyc_profiles")
        .upsert(row, on_conflict="organization_id,customer_id")
        .execute()
    )
    if result.data:
        return result.data[0]["id"]
    return None


async def cleanup_kyc_for_org(
    db: AsyncClient,
    organization_id: str,
) -> None:
    """Delete all KYC profiles and relationships for the given org."""
    await (
        db.table("account_relationships")
        .delete()
        .eq("organization_id", organization_id)
        .execute()
    )
    await (
        db.table("kyc_profiles")
        .delete()
        .eq("organization_id", organization_id)
        .execute()
    )
