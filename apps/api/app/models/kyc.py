"""
Pydantic models for KYC profile ingestion and response.

tax_id is hashed (SHA-256 with org_id salt) before storage.
Plaintext SSN/TIN must never be persisted or logged.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Beneficial owner sub-model (stored as JSONB)
# ---------------------------------------------------------------------------


class BeneficialOwner(BaseModel):
    name: str
    dob: date | None = None
    nationality: str | None = None
    ownership_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    role: str | None = None


# ---------------------------------------------------------------------------
# Ingestion request — single profile
# ---------------------------------------------------------------------------


class KYCProfileCreate(BaseModel):
    """Payload for POST /kyc/profiles — upserted by (organization_id, customer_id)."""

    customer_id: str = Field(min_length=1, max_length=256)

    # Identity
    legal_name: str = Field(min_length=1, max_length=512)
    date_of_birth: date | None = None
    nationality: str | None = Field(default=None, max_length=2)
    country_of_residence: str | None = Field(default=None, max_length=2)
    tax_id: str | None = Field(
        default=None,
        description="Plaintext tax ID — will be SHA-256 hashed before storage",
    )
    tax_id_country: str | None = Field(default=None, max_length=2)

    # Contact
    email: str | None = None
    phone: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = Field(default=None, max_length=2)

    # Classification
    customer_type: Literal["individual", "business", "trust", "other"]
    business_registration_number: str | None = None
    business_jurisdiction: str | None = None
    occupation: str | None = None
    source_of_funds: str | None = None
    source_of_wealth: str | None = None
    pep_status: Literal["not_screened", "clear", "pep", "rca"] = "not_screened"

    # Risk
    risk_rating: Literal["low", "medium", "high", "prohibited"] = "medium"
    risk_rating_reason: str | None = None

    # Onboarding
    onboarded_at: datetime
    onboarding_source: str | None = None
    last_reviewed_at: datetime | None = None

    # Beneficial ownership
    beneficial_owners: list[BeneficialOwner] | None = None


# ---------------------------------------------------------------------------
# Bulk ingestion
# ---------------------------------------------------------------------------


class BulkKYCRequest(BaseModel):
    profiles: list[KYCProfileCreate] = Field(min_length=1, max_length=10_000)


class BulkRowError(BaseModel):
    row: int
    error: str


class BulkKYCResponse(BaseModel):
    inserted: int
    updated: int
    failed: int
    errors: list[BulkRowError]


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class KYCProfileResponse(BaseModel):
    id: str
    organization_id: str
    customer_id: str
    legal_name: str
    date_of_birth: date | None = None
    nationality: str | None = None
    country_of_residence: str | None = None
    tax_id: str | None = None
    tax_id_country: str | None = None
    customer_type: str
    pep_status: str
    risk_rating: str
    onboarded_at: datetime
    last_reviewed_at: datetime | None = None
    beneficial_owners: list[dict[str, Any]] | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def hash_tax_id(plaintext: str, organization_id: str) -> str:
    """SHA-256 hash of the tax ID salted with the organization ID."""
    salted = f"{organization_id}:{plaintext}"
    return hashlib.sha256(salted.encode()).hexdigest()
