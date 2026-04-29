#!/usr/bin/env python3
"""Seed demo org + 7 golden investigations (service role). Run from repo / apps/api."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path("/Users/daniel/argonis/.env"), override=True)

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

GOLDEN_DIR = _ROOT / "tests" / "golden"
TYPOLOGIES = sorted(p.stem for p in GOLDEN_DIR.glob("*.json"))


async def _ensure_auth_user() -> None:
    import httpx

    from app.config import settings

    base = (settings.supabase_url or "").rstrip("/")
    headers = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
    }
    uid = settings.demo_user_id.strip()
    email = "demo@argonis.local"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{base}/auth/v1/admin/users",
            headers=headers,
            json={
                "id": uid,
                "email": email,
                "password": "DemoSeedArgonis2026!",
                "email_confirm": True,
            },
        )
        if r.status_code not in (200, 201) and "already been registered" not in (
            r.text or ""
        ):
            if r.status_code == 422 and "duplicate" in (r.text or "").lower():
                pass
            else:
                r.raise_for_status()


async def _ensure_org_user() -> None:
    from app.config import settings
    from app.db import get_service_db

    db = await get_service_db()
    oid = settings.demo_org_id.strip()
    slug = f"demo-{oid.replace('-', '')[:10]}"
    await (
        db.table("organizations")
        .upsert(
            {"id": oid, "name": "Argonis Demo", "slug": slug},
            on_conflict="id",
        )
        .execute()
    )
    await _ensure_auth_user()
    await (
        db.table("users")
        .upsert(
            {
                "id": settings.demo_user_id.strip(),
                "organization_id": oid,
                "email": "demo@argonis.local",
                "full_name": "Demo Analyst",
                "role": "analyst",
            },
            on_conflict="id",
        )
        .execute()
    )


async def _wipe_demo_cases() -> None:
    from app.config import settings
    from app.db import get_service_db

    oid = settings.demo_org_id.strip()
    db = await get_service_db()
    await db.table("llm_usage_log").delete().eq("organization_id", oid).execute()
    await db.table("cases").delete().eq("organization_id", oid).execute()
    await db.table("alerts").delete().eq("organization_id", oid).execute()


async def _seed_one(typology: str, org_id: str, user_id: str) -> dict[str, object]:
    from app.config import settings
    from app.db import get_service_db
    from app.pipeline.core import EvidencePipeline
    from app.services.persist_investigation import persist_pipeline_result

    path = GOLDEN_DIR / f"{typology}.json"
    with path.open(encoding="utf-8") as f:
        alert_data = json.load(f)

    db = await get_service_db()
    alert_row = {
        "organization_id": org_id,
        "title": alert_data.get("alert_type", typology),
        "description": f"Golden demo: {typology}",
        "source": "demo_seed",
        "raw_data": alert_data,
        "created_by": user_id,
    }
    ar = await db.table("alerts").insert(alert_row).execute()
    alert_id = ar.data[0]["id"]
    case_row = {
        "organization_id": org_id,
        "alert_id": alert_id,
        "title": f"Demo: {typology} — {alert_data.get('account_holder', '')}",
        "description": "Seeding…",
        "status": "open",
        "assigned_to": user_id,
        "created_by": user_id,
    }
    cr = await db.table("cases").insert(case_row).execute()
    case_id = cr.data[0]["id"]

    await (
        db.table("cases")
        .update({"status": "in_review"})
        .eq("id", case_id)
        .execute()
    )

    t0 = time.perf_counter()
    pipeline = EvidencePipeline(
        api_key=settings.anthropic_api_key or None,
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_key,
        opensanctions_api_key=settings.opensanctions_api_key,
        serper_api_key=settings.serper_api_key,
    )
    result = await pipeline.run(alert_data)
    if result.halted:
        raise RuntimeError(
            "halted: " + "; ".join(e.error_message for e in result.step_errors)
        )

    await persist_pipeline_result(
        case_id=case_id,
        organization_id=org_id,
        user_id=user_id,
        result=result,
        db=db,
    )
    elapsed = time.perf_counter() - t0
    cost = float(result.llm_usage.cost_usd) if result.llm_usage else 0.0
    print(
        f"  ✓ {typology}: {elapsed:.1f}s, ${cost:.4f}, case={case_id[:8]}…",
        flush=True,
    )
    return {
        "typology": typology,
        "case_id": case_id,
        "risk": result.analysis_result.overall_risk_score,
        "action": result.analysis_result.recommended_action,
        "evidence_count": len(result.evidence_items),
        "cost_usd": cost,
        "duration_s": elapsed,
    }


async def main() -> int:
    from app.config import settings

    if not settings.demo_mode:
        print("DEMO_MODE must be true in .env", file=sys.stderr)
        return 1
    if not settings.supabase_url or not settings.supabase_service_key:
        print("Supabase not configured", file=sys.stderr)
        return 1

    print("Ensuring demo org + user…", flush=True)
    await _ensure_org_user()
    print("Wiping prior demo cases…", flush=True)
    await _wipe_demo_cases()

    org_id = settings.demo_org_id.strip()
    user_id = settings.demo_user_id.strip()
    rows: list[dict[str, object]] = []
    total_cost = 0.0
    total_time = 0.0

    for typ in TYPOLOGIES:
        print(f"▶ {typ}…", flush=True)
        try:
            row = await _seed_one(typ, org_id, user_id)
            rows.append(row)
            total_cost += float(row["cost_usd"])
            total_time += float(row["duration_s"])
        except Exception as exc:
            print(f"  ✗ {typ}: {exc}", file=sys.stderr)
            return 1

    print("\n" + "=" * 100)
    hdr = (
        f"{'typology':<18} {'case_id':<38} {'risk':>6} {'action':<12} "
        f"{'evid':>5} {'cost':>10} {'sec':>8}"
    )
    print(hdr)
    print("-" * 100)
    for r in rows:
        print(
            f"{r['typology']!s:<18} {r['case_id']!s:<38} "
            f"{float(r['risk']):>6.3f} {str(r['action']):<12} "
            f"{int(r['evidence_count']):>5} ${float(r['cost_usd']):>9.4f} "
            f"{float(r['duration_s']):>8.1f}"
        )
    print("-" * 100)
    print(f"TOTAL{'':<74} ${total_cost:>9.4f} {total_time:>8.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
