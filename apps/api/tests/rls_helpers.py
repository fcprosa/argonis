"""
Helpers for RLS isolation tests.

Provides JWT minting, PostgREST client factories scoped to specific users
(with RLS enforced) or service role (RLS bypassed), and test organisation
lifecycle utilities.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from uuid import uuid4

import jwt as pyjwt
from postgrest import AsyncPostgrestClient
from supabase import AsyncClient


def _env(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        raise RuntimeError(f"{name} is not set")
    return val


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def mint_anon_key(jwt_secret: str) -> str:
    """Derive a Supabase-compatible anon key from the project JWT secret."""
    return pyjwt.encode(
        {"role": "anon", "iss": "supabase"},
        jwt_secret,
        algorithm="HS256",
    )


def mint_user_jwt(user_id: str, jwt_secret: str) -> str:
    """Mint a short-lived authenticated-role JWT for *user_id*."""
    now = int(time.time())
    return pyjwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "role": "authenticated",
            "iat": now,
            "exp": now + 3600,
        },
        jwt_secret,
        algorithm="HS256",
    )


# ---------------------------------------------------------------------------
# Client factories
# ---------------------------------------------------------------------------


def supabase_client_as(
    user_id: str,
    supabase_url: str | None = None,
    jwt_secret: str | None = None,
) -> AsyncPostgrestClient:
    """PostgREST client operating as *user_id* with RLS enforced.

    Uses an anon-key ``apikey`` header so PostgREST applies RLS, and a
    user JWT in the ``Authorization`` header so ``auth.uid()`` resolves
    to *user_id*.
    """
    url = supabase_url or _env("SUPABASE_URL")
    secret = jwt_secret or _env("SUPABASE_JWT_SECRET")
    return AsyncPostgrestClient(
        f"{url}/rest/v1",
        headers={
            "apikey": mint_anon_key(secret),
            "Authorization": f"Bearer {mint_user_jwt(user_id, secret)}",
        },
    )


def service_role_client(
    supabase_url: str | None = None,
    service_key: str | None = None,
) -> AsyncPostgrestClient:
    """PostgREST client with the service-role key (bypasses RLS)."""
    url = supabase_url or _env("SUPABASE_URL")
    key = service_key or _env("SUPABASE_SERVICE_KEY")
    return AsyncPostgrestClient(
        f"{url}/rest/v1",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
        },
    )


# ---------------------------------------------------------------------------
# Test-data container
# ---------------------------------------------------------------------------


@dataclass
class OrgTestData:
    """Row IDs for the full hierarchy seeded for one test organisation."""

    org_id: str = ""
    user_id: str = ""
    alert_id: str = ""
    case_id: str = ""
    step_id: str = ""
    screening_id: str = ""
    narrative_id: str = ""
    section_id: str = ""
    evidence_link_id: str = ""
    audit_log_id: str = ""
    llm_usage_id: str = ""


# ---------------------------------------------------------------------------
# Org lifecycle
# ---------------------------------------------------------------------------


async def create_test_org(
    service_db: AsyncClient,
    name: str,
) -> tuple[str, str]:
    """Create an org + auth user + ``public.users`` row.

    Returns ``(org_id, user_id)``.
    """
    slug = f"{name}-{uuid4().hex[:8]}"

    org = await (
        service_db.table("organizations")
        .insert({"name": f"RLS Test: {name}", "slug": slug})
        .execute()
    )
    org_id: str = org.data[0]["id"]

    email = f"rls-{slug}@argonis.test"
    auth_resp = await service_db.auth.admin.create_user(
        {"email": email, "password": f"Test!{uuid4().hex}", "email_confirm": True}
    )
    user_id = str(auth_resp.user.id)

    await (
        service_db.table("users")
        .insert(
            {
                "id": user_id,
                "organization_id": org_id,
                "email": email,
                "full_name": f"RLS Test User ({name})",
                "role": "analyst",
            }
        )
        .execute()
    )
    return org_id, user_id


async def seed_org_data(
    service_db: AsyncClient,
    org_id: str,
    user_id: str,
) -> OrgTestData:
    """Insert a full row hierarchy for *org_id* via service role."""
    d = OrgTestData(org_id=org_id, user_id=user_id)

    r = await service_db.table("alerts").insert(
        {
            "organization_id": org_id,
            "title": f"RLS Alert {org_id[:8]}",
            "source": "rls_test",
            "severity": "medium",
            "created_by": user_id,
        }
    ).execute()
    d.alert_id = r.data[0]["id"]

    r = await service_db.table("cases").insert(
        {
            "organization_id": org_id,
            "alert_id": d.alert_id,
            "title": f"RLS Case {org_id[:8]}",
            "created_by": user_id,
        }
    ).execute()
    d.case_id = r.data[0]["id"]

    r = await service_db.table("investigation_steps").insert(
        {
            "organization_id": org_id,
            "case_id": d.case_id,
            "name": "rls_test_step",
            "status": "completed",
        }
    ).execute()
    d.step_id = r.data[0]["id"]

    r = await service_db.table("screening_results").insert(
        {
            "organization_id": org_id,
            "case_id": d.case_id,
            "entity_name": f"RLS Entity {org_id[:8]}",
            "match_confidence": 0.850,
        }
    ).execute()
    d.screening_id = r.data[0]["id"]

    r = await service_db.table("narratives").insert(
        {
            "organization_id": org_id,
            "case_id": d.case_id,
            "version": 1,
            "title": f"RLS Narrative {org_id[:8]}",
            "created_by": user_id,
        }
    ).execute()
    d.narrative_id = r.data[0]["id"]

    r = await service_db.table("narrative_sections").insert(
        {
            "organization_id": org_id,
            "narrative_id": d.narrative_id,
            "section_key": "subject_information",
            "title": "Subject Information",
            "content": "Test content for RLS isolation testing.",
        }
    ).execute()
    d.section_id = r.data[0]["id"]

    r = await service_db.table("evidence_links").insert(
        {
            "organization_id": org_id,
            "narrative_id": d.narrative_id,
            "section_id": d.section_id,
            "sentence_text": "Test evidence sentence for RLS.",
            "source_type": "investigation_step",
            "investigation_step_id": d.step_id,
        }
    ).execute()
    d.evidence_link_id = r.data[0]["id"]

    r = await service_db.table("llm_usage_log").insert(
        {
            "organization_id": org_id,
            "case_id": d.case_id,
            "model": "claude-sonnet-4-20250514",
            "step": "narrate",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cost_usd": 0.015,
        }
    ).execute()
    d.llm_usage_id = r.data[0]["id"]

    # The cases INSERT fires the write_audit_log() trigger — fetch the row
    audit = await (
        service_db.table("audit_log")
        .select("id")
        .eq("organization_id", org_id)
        .eq("table_name", "cases")
        .eq("record_id", d.case_id)
        .limit(1)
        .execute()
    )
    if audit.data:
        d.audit_log_id = audit.data[0]["id"]
    else:
        r = await service_db.table("audit_log").insert(
            {
                "organization_id": org_id,
                "user_id": user_id,
                "action": "INSERT",
                "table_name": "cases",
                "record_id": d.case_id,
                "new_data": {"rls_test": True},
            }
        ).execute()
        d.audit_log_id = r.data[0]["id"]

    return d


async def cleanup_test_org(
    service_db: AsyncClient,
    org_id: str,
    user_id: str,
) -> None:
    """Best-effort cascade-delete all test data for *org_id*."""
    # Tables with ON DELETE SET NULL on organization_id — delete explicitly
    for table in ("llm_usage_log", "audit_log"):
        try:
            await (
                service_db.table(table)
                .delete()
                .eq("organization_id", org_id)
                .execute()
            )
        except Exception:
            pass
    # Deleting the org cascades to users, alerts, cases, and their children
    try:
        await service_db.table("organizations").delete().eq("id", org_id).execute()
    except Exception:
        pass
    # Clean up Supabase auth user (public.users row already cascaded)
    try:
        await service_db.auth.admin.delete_user(user_id)
    except Exception:
        pass
