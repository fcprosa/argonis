"""
Shared fixtures for integration tests.

Provides a Supabase service-role client and helpers for creating / tearing
down test organizations and users against a live Supabase instance.
"""

from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv

# Load .env from repo root. Must run before app.config is imported,
# otherwise pydantic-settings reads an empty environment.
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env", override=False)

import logging
import os
from uuid import uuid4

import pytest
from supabase import AsyncClient

from app.db import get_service_db

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def _require_env() -> None:
    """Fast-fail if required env vars are missing."""
    for var in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "ANTHROPIC_API_KEY"):
        if not os.getenv(var):
            pytest.skip(f"{var} not set — skipping integration tests")


@pytest.fixture
async def db(_require_env: None) -> AsyncClient:
    """Return the Supabase async service-role client (bypasses RLS)."""
    return await get_service_db()


@pytest.fixture
async def test_org(db: AsyncClient) -> str:
    """Create a throwaway organization and delete it on teardown.

    Deleting the org cascades to alerts, cases, investigation_steps,
    screening_results, narratives, narrative_sections, and evidence_links
    via ON DELETE CASCADE on organization_id foreign keys.
    """
    slug = f"test-{uuid4().hex[:12]}"
    result = await (
        db.table("organizations")
        .insert({"name": f"Pipeline Integration Test ({slug})", "slug": slug})
        .execute()
    )
    org_id: str = result.data[0]["id"]

    yield org_id  # type: ignore[misc]

    # Teardown order — write_audit_log() triggers on cascaded deletes can insert
    # audit rows referencing the org; clean audit-adjacent tables first.
    try:
        await db.table("audit_log").delete().eq("organization_id", org_id).execute()
    except Exception as exc:
        logger.warning("audit_log pre-cleanup failed (non-fatal): %s", exc)

    try:
        await db.table("pipeline_events").delete().eq("organization_id", org_id).execute()
    except Exception as exc:
        logger.warning("pipeline_events pre-cleanup failed (non-fatal): %s", exc)

    try:
        await db.table("account_relationships").delete().eq("organization_id", org_id).execute()
    except Exception as exc:
        logger.warning("account_relationships pre-cleanup failed (non-fatal): %s", exc)

    try:
        await db.table("kyc_profiles").delete().eq("organization_id", org_id).execute()
    except Exception as exc:
        logger.warning("kyc_profiles pre-cleanup failed (non-fatal): %s", exc)

    try:
        await db.table("llm_usage_log").delete().eq("organization_id", org_id).execute()
    except Exception as exc:
        logger.warning("llm_usage_log pre-cleanup failed (non-fatal): %s", exc)

    await db.table("organizations").delete().eq("id", org_id).execute()


@pytest.fixture
async def test_user(db: AsyncClient, test_org: str) -> str:
    """Create a Supabase auth user + public.users row for the test org.

    Teardown deletes the auth user (cascades to public.users).
    The org fixture handles everything else.
    """
    email = f"test-{uuid4().hex[:10]}@argonis.test"
    auth_resp = await db.auth.admin.create_user(
        {
            "email": email,
            "password": f"Test!{uuid4().hex}",
            "email_confirm": True,
        }
    )
    user_id: str = str(auth_resp.user.id)

    await (
        db.table("users")
        .insert(
            {
                "id": user_id,
                "organization_id": test_org,
                "email": email,
                "full_name": "Pipeline Integration Test User",
                "role": "analyst",
            }
        )
        .execute()
    )

    yield user_id  # type: ignore[misc]

    try:
        await db.auth.admin.delete_user(user_id)
    except Exception:
        pass
