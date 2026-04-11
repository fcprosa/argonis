"""
RLS Isolation Test Suite — Multi-Tenant Data Boundary Verification
==================================================================

**Threat model**

A malicious authenticated user in Organisation A attempts to:

1. Read another organisation's (B) cases, alerts, narratives, etc.
2. Modify or delete organisation B's data via UPDATE / DELETE.
3. Link their own rows to organisation B's entities via foreign keys
   (PostgreSQL FK checks bypass RLS).
4. Enumerate the existence or count of organisation B's records.

Every operation in (1)–(4) MUST fail silently (0 rows returned, not an
error) or be blocked by a constraint.  Any success is a data-isolation
breach and a **P0 bug**.

This suite must pass **100 %** before any customer is onboarded.  Run it
against a live Supabase instance with ``SUPABASE_URL``,
``SUPABASE_SERVICE_KEY``, and ``SUPABASE_JWT_SECRET`` set.

RLS GAPS FOUND (review migrations to fix)
==========================================

# RED — GAP 1: Cross-org FK references bypass RLS.
#
# ``cases.alert_id`` can reference an alert belonging to a different org
# because PostgreSQL foreign-key checks run as the table owner and bypass
# row-level security.  The same gap exists for every FK that crosses org
# boundaries (``investigation_steps.case_id``,
# ``screening_results.case_id``, ``narratives.case_id``, etc.).
#
# Fix: add a CHECK constraint or BEFORE INSERT trigger that validates the
# referenced row's ``organization_id`` matches the inserting row's.

# RED — GAP 2: ``evidence_links`` is NOT actually immutable.
#
# ``evidence_links_no_update`` uses ``FOR UPDATE USING (false)`` with
# default PERMISSIVE mode, but ``evidence_links_org`` (``FOR ALL``)
# already permits UPDATE for same-org users.  PERMISSIVE policies are
# OR'd, so the no-update policy is a complete no-op.
#
# Fix: recreate the policy with ``AS RESTRICTIVE``:
#   DROP POLICY "evidence_links_no_update" ON evidence_links;
#   CREATE POLICY "evidence_links_no_update" ON evidence_links
#       AS RESTRICTIVE FOR UPDATE USING (false);

# WARN — GAP 3: ``narrative_sections`` approval role check is ineffective.
#
# ``sections_approve_reviewer`` restricts UPDATE to reviewers/admins when
# ``approval_status`` changes, but ``sections_org`` (``FOR ALL``) already
# permits any same-org user to UPDATE.  Permissive policies are OR'd, so
# the role check is bypassed.  This is a within-org role-enforcement gap,
# not a cross-org isolation gap.

# NOTE — ``ofac_refresh_log`` has no ``organization_id``.  It is global
# operational data with ``FOR SELECT USING (true)``.  Cross-org isolation
# does not apply.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pytest
from postgrest import AsyncPostgrestClient
from supabase import AsyncClient, acreate_client

from tests.rls_helpers import (
    OrgTestData,
    cleanup_test_org,
    create_test_org,
    seed_org_data,
    service_role_client,
    supabase_client_as,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ---------------------------------------------------------------------------
# Table specifications for the parametrised isolation test
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TableSpec:
    """Describes one RLS-protected table to probe."""

    table: str
    id_attr: str  # attribute on OrgTestData holding the row PK
    update_payload: dict[str, Any] | None = None  # None → skip UPDATE sub-test


TABLE_SPECS: list[TableSpec] = [
    TableSpec("organizations", "org_id", {"name": "HACKED_BY_CROSS_ORG"}),
    TableSpec("users", "user_id", {"full_name": "HACKED_BY_CROSS_ORG"}),
    TableSpec("alerts", "alert_id", {"title": "HACKED_BY_CROSS_ORG"}),
    TableSpec("cases", "case_id", {"title": "HACKED_BY_CROSS_ORG"}),
    TableSpec("investigation_steps", "step_id", {"name": "HACKED_BY_CROSS_ORG"}),
    TableSpec(
        "screening_results", "screening_id", {"entity_name": "HACKED_BY_CROSS_ORG"}
    ),
    TableSpec("narratives", "narrative_id", {"title": "HACKED_BY_CROSS_ORG"}),
    TableSpec(
        "narrative_sections", "section_id", {"content": "HACKED_BY_CROSS_ORG"}
    ),
    # evidence_links: UPDATE blocked by evidence_links_no_update policy
    # (see GAP 2 for why this may actually be ineffective)
    TableSpec("evidence_links", "evidence_link_id"),
    # audit_log / llm_usage_log: SELECT-only for users, no write policies
    TableSpec("audit_log", "audit_log_id"),
    TableSpec("llm_usage_log", "llm_usage_id"),
]


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def service_db() -> AsyncClient:
    """Full Supabase service-role client (for org / user management)."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    secret = os.environ.get("SUPABASE_JWT_SECRET", "")
    if not url or not key or not secret:
        pytest.skip(
            "SUPABASE_URL, SUPABASE_SERVICE_KEY, and SUPABASE_JWT_SECRET required"
        )
    return await acreate_client(url, key)


@pytest.fixture(scope="module")
async def rls_env(service_db: AsyncClient):
    """Provision two isolated test orgs with full data hierarchies.

    Yields a dict with:
    - ``org_a``, ``org_b``: :class:`OrgTestData`
    - ``client_a``, ``client_b``: user-scoped PostgREST clients (RLS on)
    - ``service``: service-role PostgREST client (RLS off)
    """
    url = os.environ["SUPABASE_URL"]
    secret = os.environ["SUPABASE_JWT_SECRET"]
    svc_key = os.environ["SUPABASE_SERVICE_KEY"]

    org_a_id, user_a_id = await create_test_org(service_db, "rls_org_a")
    org_b_id, user_b_id = await create_test_org(service_db, "rls_org_b")

    data_a = await seed_org_data(service_db, org_a_id, user_a_id)
    data_b = await seed_org_data(service_db, org_b_id, user_b_id)

    client_a = supabase_client_as(user_a_id, url, secret)
    client_b = supabase_client_as(user_b_id, url, secret)
    svc = service_role_client(url, svc_key)

    yield {
        "org_a": data_a,
        "org_b": data_b,
        "client_a": client_a,
        "client_b": client_b,
        "service": svc,
    }

    for c in (client_a, client_b, svc):
        try:
            await c.aclose()
        except Exception:
            pass
    await cleanup_test_org(service_db, org_a_id, user_a_id)
    await cleanup_test_org(service_db, org_b_id, user_b_id)


# ===================================================================
# 1. Core cross-org isolation  (parametrised × 11 tables)
# ===================================================================


@pytest.mark.parametrize("spec", TABLE_SPECS, ids=lambda s: s.table)
async def test_cross_org_isolation(spec: TableSpec, rls_env: dict) -> None:
    """Org B cannot read, update, or delete Org A's rows.

    Steps per table:
      (a) Owner reads own row              → 1 row
      (b) Cross-org SELECT                 → 0 rows
      (c) Cross-org UPDATE (if applicable) → 0 rows affected
      (d) Cross-org DELETE                 → 0 rows affected
      (e) Service role confirms survival   → 1 row
    """
    client_a: AsyncPostgrestClient = rls_env["client_a"]
    client_b: AsyncPostgrestClient = rls_env["client_b"]
    svc: AsyncPostgrestClient = rls_env["service"]
    org_a: OrgTestData = rls_env["org_a"]
    row_id = getattr(org_a, spec.id_attr)

    # (a) Owner can read their own row
    r = await client_a.from_(spec.table).select("*").eq("id", row_id).execute()
    assert len(r.data) == 1, f"{spec.table}: owner must see own row (id={row_id})"

    # (b) Cross-org SELECT → 0 rows (NOT an error, just empty)
    r = await client_b.from_(spec.table).select("*").eq("id", row_id).execute()
    assert len(r.data) == 0, (
        f"{spec.table}: cross-org SELECT must return 0 rows, got {len(r.data)}"
    )

    # (c) Cross-org UPDATE → 0 rows affected
    if spec.update_payload is not None:
        r = (
            await client_b.from_(spec.table)
            .update(spec.update_payload)
            .eq("id", row_id)
            .execute()
        )
        assert len(r.data) == 0, (
            f"{spec.table}: cross-org UPDATE must affect 0 rows"
        )

    # (d) Cross-org DELETE → 0 rows affected
    r = await client_b.from_(spec.table).delete().eq("id", row_id).execute()
    assert len(r.data) == 0, (
        f"{spec.table}: cross-org DELETE must affect 0 rows"
    )

    # (e) Service role confirms the row is untouched
    r = await svc.from_(spec.table).select("*").eq("id", row_id).execute()
    assert len(r.data) == 1, (
        f"{spec.table}: row must survive cross-org attack (id={row_id})"
    )


# ===================================================================
# 2. Foreign-key leak attack
# ===================================================================


async def test_fk_leak_cross_org_alert_reference(rls_env: dict) -> None:
    """Org B creates a case referencing Org A's alert via FK.

    PostgreSQL FK checks bypass RLS, so the cross-org FK reference may
    succeed.  This test asserts the *ideal* behaviour (INSERT blocked).
    If the INSERT succeeds, the test fails — documenting the RLS gap.

    See GAP 1 in the module docstring.
    """
    org_a: OrgTestData = rls_env["org_a"]
    org_b: OrgTestData = rls_env["org_b"]
    client_b: AsyncPostgrestClient = rls_env["client_b"]
    svc: AsyncPostgrestClient = rls_env["service"]

    created_id: str | None = None
    try:
        try:
            r = await client_b.from_("cases").insert(
                {
                    "organization_id": org_b.org_id,
                    "alert_id": org_a.alert_id,
                    "title": "FK Leak Attack — cross-org alert ref",
                    "created_by": org_b.user_id,
                }
            ).execute()
            created_id = r.data[0]["id"] if r.data else None
        except Exception:
            pass  # Blocked — correct behaviour

        assert created_id is None, (
            f"RLS GAP: cases.alert_id accepted cross-org FK reference. "
            f"Org B case {created_id} references org A alert {org_a.alert_id}. "
            f"Add a CHECK constraint or BEFORE INSERT trigger to enforce "
            f"same-org invariant on FK references."
        )
    finally:
        if created_id:
            await svc.from_("cases").delete().eq("id", created_id).execute()


# ===================================================================
# 3. Enumeration attack
# ===================================================================


async def test_enumeration_attack(rls_env: dict) -> None:
    """Org B cannot discover the count or existence of Org A's cases.

    Creates 5 total cases for Org A, then verifies Org B's user sees
    zero of them via both count and bulk SELECT queries.
    """
    org_a: OrgTestData = rls_env["org_a"]
    org_b: OrgTestData = rls_env["org_b"]
    client_b: AsyncPostgrestClient = rls_env["client_b"]
    svc: AsyncPostgrestClient = rls_env["service"]

    extra_ids: list[str] = []
    try:
        # Seed 4 more cases for org A (1 already exists from fixture → 5 total)
        for i in range(4):
            r = await svc.from_("cases").insert(
                {
                    "organization_id": org_a.org_id,
                    "title": f"Enum Attack Case {i}",
                    "created_by": org_a.user_id,
                }
            ).execute()
            extra_ids.append(r.data[0]["id"])

        # Service role confirms org A has 5 cases
        r = (
            await svc.from_("cases")
            .select("*", count="exact")
            .eq("organization_id", org_a.org_id)
            .execute()
        )
        assert r.count == 5, f"Setup: org A should have 5 cases, got {r.count}"

        # Org B: count query must NOT include org A's cases
        r = (
            await client_b.from_("cases")
            .select("*", count="exact")
            .execute()
        )
        for row in r.data:
            assert row["organization_id"] == org_b.org_id, (
                f"Enumeration leak: org A case {row['id']} visible to org B"
            )
        assert r.count is not None and r.count <= 1, (
            f"Enumeration attack: org B sees {r.count} cases "
            f"(expected ≤1; org A has 5 invisible cases)"
        )

        # Org B: SELECT * LIMIT 1000 returns zero org A rows
        r = await client_b.from_("cases").select("*").limit(1000).execute()
        for row in r.data:
            assert row["organization_id"] == org_b.org_id, (
                f"Enumeration leak via LIMIT: org A case {row['id']} in org B result"
            )
    finally:
        for cid in extra_ids:
            try:
                await svc.from_("cases").delete().eq("id", cid).execute()
            except Exception:
                pass


# ===================================================================
# 4. evidence_links immutability
# ===================================================================


async def test_evidence_links_immutable(rls_env: dict) -> None:
    """evidence_links rows cannot be UPDATEd by any user — even the owner.

    The ``evidence_links_no_update`` policy uses ``FOR UPDATE USING (false)``,
    but because it is PERMISSIVE (the default) and ``evidence_links_org``
    (``FOR ALL``) already permits UPDATE for same-org users, the no-update
    policy is a no-op (PERMISSIVE policies are OR'd).

    This test asserts the *intended* behaviour.  If it fails, the policy
    must be recreated with ``AS RESTRICTIVE``.  See GAP 2 in module docstring.
    """
    client_a: AsyncPostgrestClient = rls_env["client_a"]
    org_a: OrgTestData = rls_env["org_a"]

    r = (
        await client_a.from_("evidence_links")
        .update({"sentence_text": "TAMPERED"})
        .eq("id", org_a.evidence_link_id)
        .execute()
    )
    assert len(r.data) == 0, (
        "RLS GAP: evidence_links_no_update is PERMISSIVE and ineffective — "
        "owner can UPDATE evidence_links.  Recreate policy AS RESTRICTIVE."
    )


# ===================================================================
# 5. ofac_refresh_log — global data, public read, no write
# ===================================================================


async def test_ofac_refresh_log_public_read_no_write(rls_env: dict) -> None:
    """ofac_refresh_log: any user can read, none can write.

    This table has no ``organization_id``.  ``FOR SELECT USING (true)``
    allows universal read.  No INSERT / UPDATE / DELETE policies exist
    for regular users.
    """
    client_a: AsyncPostgrestClient = rls_env["client_a"]
    svc: AsyncPostgrestClient = rls_env["service"]

    r = await svc.from_("ofac_refresh_log").insert(
        {
            "entries_count": 42,
            "alternates_count": 10,
            "source_url": "https://rls-test.example.com/sdn.csv",
        }
    ).execute()
    log_id: str = r.data[0]["id"]

    try:
        # Any authenticated user can read
        r = (
            await client_a.from_("ofac_refresh_log")
            .select("*")
            .eq("id", log_id)
            .execute()
        )
        assert len(r.data) == 1, "Any user should be able to read ofac_refresh_log"

        # INSERT must be denied (no INSERT policy)
        insert_succeeded = False
        try:
            await client_a.from_("ofac_refresh_log").insert(
                {
                    "entries_count": 999,
                    "alternates_count": 0,
                    "source_url": "https://attack.example.com",
                }
            ).execute()
            insert_succeeded = True
        except Exception:
            pass
        assert not insert_succeeded, (
            "ofac_refresh_log INSERT must be denied for regular users"
        )

        # UPDATE must be denied
        r = (
            await client_a.from_("ofac_refresh_log")
            .update({"entries_count": 999})
            .eq("id", log_id)
            .execute()
        )
        assert len(r.data) == 0, (
            "ofac_refresh_log UPDATE must be denied for regular users"
        )

        # DELETE must be denied
        r = (
            await client_a.from_("ofac_refresh_log")
            .delete()
            .eq("id", log_id)
            .execute()
        )
        assert len(r.data) == 0, (
            "ofac_refresh_log DELETE must be denied for regular users"
        )
    finally:
        await svc.from_("ofac_refresh_log").delete().eq("id", log_id).execute()


# ===================================================================
# 6. Audit log and LLM usage log — SELECT-only for users
# ===================================================================


async def test_audit_log_user_cannot_insert(rls_env: dict) -> None:
    """Regular users cannot INSERT into audit_log (trigger-only writes)."""
    client_a: AsyncPostgrestClient = rls_env["client_a"]
    org_a: OrgTestData = rls_env["org_a"]

    insert_succeeded = False
    try:
        await client_a.from_("audit_log").insert(
            {
                "organization_id": org_a.org_id,
                "action": "INSERT",
                "table_name": "fake_table",
                "record_id": org_a.case_id,
                "new_data": {"fabricated": True},
            }
        ).execute()
        insert_succeeded = True
    except Exception:
        pass
    assert not insert_succeeded, (
        "audit_log INSERT must be denied for regular users (trigger-only)"
    )


async def test_llm_usage_log_user_cannot_insert(rls_env: dict) -> None:
    """Regular users cannot INSERT into llm_usage_log (service-role only)."""
    client_a: AsyncPostgrestClient = rls_env["client_a"]
    org_a: OrgTestData = rls_env["org_a"]

    insert_succeeded = False
    try:
        await client_a.from_("llm_usage_log").insert(
            {
                "organization_id": org_a.org_id,
                "case_id": org_a.case_id,
                "model": "fabricated-model",
                "step": "narrate",
                "input_tokens": 999999,
                "output_tokens": 999999,
                "cost_usd": 0.0,
            }
        ).execute()
        insert_succeeded = True
    except Exception:
        pass
    assert not insert_succeeded, (
        "llm_usage_log INSERT must be denied for regular users"
    )
