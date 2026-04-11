"""
KYC profile ingestion endpoints.

POST /kyc/profiles      — upsert a single KYC profile
POST /kyc/profiles/bulk — upsert up to 10,000 profiles (batched at 500)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from app.auth import AuthContext, get_current_user
from app.db import get_service_db
from app.models.kyc import (
    BulkKYCRequest,
    BulkKYCResponse,
    BulkRowError,
    KYCProfileCreate,
    KYCProfileResponse,
    hash_tax_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kyc", tags=["kyc"])

_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile_to_row(
    profile: KYCProfileCreate,
    organization_id: str,
) -> dict[str, Any]:
    """Convert a validated Pydantic model to a DB row dict."""
    row: dict[str, Any] = {
        "organization_id": organization_id,
        "customer_id": profile.customer_id,
        "legal_name": profile.legal_name,
        "date_of_birth": profile.date_of_birth.isoformat() if profile.date_of_birth else None,
        "nationality": profile.nationality,
        "country_of_residence": profile.country_of_residence,
        "tax_id_country": profile.tax_id_country,
        "email": profile.email,
        "phone": profile.phone,
        "address_line1": profile.address_line1,
        "address_line2": profile.address_line2,
        "city": profile.city,
        "postal_code": profile.postal_code,
        "country": profile.country,
        "customer_type": profile.customer_type,
        "business_registration_number": profile.business_registration_number,
        "business_jurisdiction": profile.business_jurisdiction,
        "occupation": profile.occupation,
        "source_of_funds": profile.source_of_funds,
        "source_of_wealth": profile.source_of_wealth,
        "pep_status": profile.pep_status,
        "risk_rating": profile.risk_rating,
        "risk_rating_reason": profile.risk_rating_reason,
        "onboarded_at": profile.onboarded_at.isoformat(),
        "onboarding_source": profile.onboarding_source,
        "last_reviewed_at": (
            profile.last_reviewed_at.isoformat() if profile.last_reviewed_at else None
        ),
        "beneficial_owners": (
            [bo.model_dump(mode="json") for bo in profile.beneficial_owners]
            if profile.beneficial_owners
            else None
        ),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if profile.tax_id:
        row["tax_id"] = hash_tax_id(profile.tax_id, organization_id)
    else:
        row["tax_id"] = None

    return row


# ---------------------------------------------------------------------------
# POST /kyc/profiles — single upsert
# ---------------------------------------------------------------------------


@router.post(
    "/profiles",
    response_model=KYCProfileResponse,
    status_code=status.HTTP_200_OK,
)
async def upsert_kyc_profile(
    body: KYCProfileCreate,
    auth: AuthContext = Depends(get_current_user),
) -> KYCProfileResponse:
    """Upsert a single KYC profile by (organization_id, customer_id)."""
    db = await get_service_db()
    row = _profile_to_row(body, auth.organization_id)

    result = await (
        db.table("kyc_profiles")
        .upsert(row, on_conflict="organization_id,customer_id")
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to upsert KYC profile")

    return KYCProfileResponse(**result.data[0])


# ---------------------------------------------------------------------------
# POST /kyc/profiles/bulk — batch upsert
# ---------------------------------------------------------------------------


@router.post(
    "/profiles/bulk",
    response_model=BulkKYCResponse,
    status_code=status.HTTP_200_OK,
)
async def bulk_upsert_kyc_profiles(
    body: BulkKYCRequest,
    auth: AuthContext = Depends(get_current_user),
) -> BulkKYCResponse:
    """Upsert up to 10,000 KYC profiles in batches of 500."""
    db = await get_service_db()

    inserted = 0
    updated = 0
    failed = 0
    errors: list[BulkRowError] = []

    rows: list[dict[str, Any]] = []
    row_indices: list[int] = []

    for i, profile in enumerate(body.profiles):
        try:
            rows.append(_profile_to_row(profile, auth.organization_id))
            row_indices.append(i)
        except Exception as exc:
            failed += 1
            errors.append(BulkRowError(row=i, error=str(exc)[:500]))

    for batch_start in range(0, len(rows), _BATCH_SIZE):
        batch = rows[batch_start : batch_start + _BATCH_SIZE]
        batch_indices = row_indices[batch_start : batch_start + _BATCH_SIZE]

        try:
            # Check which customer_ids already exist
            customer_ids = [r["customer_id"] for r in batch]
            existing = await (
                db.table("kyc_profiles")
                .select("customer_id")
                .eq("organization_id", auth.organization_id)
                .in_("customer_id", customer_ids)
                .execute()
            )
            existing_set = {r["customer_id"] for r in (existing.data or [])}

            result = await (
                db.table("kyc_profiles")
                .upsert(batch, on_conflict="organization_id,customer_id")
                .execute()
            )

            upserted_count = len(result.data or [])
            batch_updated = sum(
                1 for r in (result.data or []) if r["customer_id"] in existing_set
            )
            batch_inserted = upserted_count - batch_updated
            inserted += batch_inserted
            updated += batch_updated

        except Exception as exc:
            logger.error("Bulk KYC batch %d failed: %s", batch_start, exc)
            for j, idx in enumerate(batch_indices):
                failed += 1
                errors.append(BulkRowError(row=idx, error=str(exc)[:500]))

    logger.info(
        "Bulk KYC upsert: org=%s inserted=%d updated=%d failed=%d",
        auth.organization_id, inserted, updated, failed,
    )

    return BulkKYCResponse(
        inserted=inserted,
        updated=updated,
        failed=failed,
        errors=errors,
    )
