"""
Admin endpoints — founder/ops dashboard.

All endpoints require JWT auth + admin role.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import AuthContext, require_role
from app.db import get_service_db
from app.services.cost_monitor import (
    ABSOLUTE_COST_THRESHOLD_USD,
    BASELINE_WINDOW,
    RATIO_MULTIPLIER,
    STDDEV_MULTIPLIER,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CostBucket(BaseModel):
    investigations: int
    total_cost_usd: float
    avg_cost_usd: float
    p95_cost_usd: float


class CostStatsResponse(BaseModel):
    last_24h: CostBucket
    last_7d: CostBucket
    anomalies_last_24h: int


class FirewallBucket(BaseModel):
    total_narratives: int
    avg_strip_rate: float
    p95_strip_rate: float
    narratives_above_20pct: int


class FirewallOffender(BaseModel):
    case_id: str
    section_key: str
    strip_rate: float
    created_at: str


class FirewallStatsResponse(BaseModel):
    last_24h: FirewallBucket
    last_7d: FirewallBucket
    worst_offenders: list[FirewallOffender]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/cost-stats", response_model=CostStatsResponse)
async def cost_stats(
    auth: AuthContext = Depends(require_role("admin")),
) -> CostStatsResponse:
    """
    Aggregate LLM cost statistics for the founder dashboard.

    Answers: "Is our pricing model intact? Did a prompt change blow up costs?"
    """
    db = await get_service_db()
    now = datetime.now(timezone.utc)
    since_24h = (now - timedelta(hours=24)).isoformat()
    since_7d = (now - timedelta(days=7)).isoformat()

    # Fetch all rows from the last 7 days in one query (superset of 24h)
    result = await (
        db.table("llm_usage_log")
        .select("cost_usd, input_tokens, output_tokens, created_at")
        .gte("created_at", since_7d)
        .order("created_at", desc=True)
        .execute()
    )

    rows_7d = result.data or []
    rows_24h = [r for r in rows_7d if r["created_at"] >= since_24h]

    bucket_24h = _compute_bucket(rows_24h)
    bucket_7d = _compute_bucket(rows_7d)

    # Count anomalies in the last 24h using the same logic as cost_monitor
    anomalies_24h = _count_anomalies(rows_24h, rows_7d)

    return CostStatsResponse(
        last_24h=bucket_24h,
        last_7d=bucket_7d,
        anomalies_last_24h=anomalies_24h,
    )


@router.get("/firewall-stats", response_model=FirewallStatsResponse)
async def firewall_stats(
    auth: AuthContext = Depends(require_role("admin")),
) -> FirewallStatsResponse:
    """
    Evidence-firewall health dashboard.

    Answers: "Is our hallucination defense holding?  Did a prompt change
    increase fabrication rates?"
    """
    db = await get_service_db()
    now = datetime.now(timezone.utc)
    since_24h = (now - timedelta(hours=24)).isoformat()
    since_7d = (now - timedelta(days=7)).isoformat()

    result = await (
        db.table("firewall_strip_log")
        .select(
            "case_id, stripped_count, total_cited_count, strip_rate, "
            "created_at, narrative_sections(section_key)"
        )
        .gte("created_at", since_7d)
        .order("created_at", desc=True)
        .execute()
    )

    rows_7d = result.data or []
    rows_24h = [r for r in rows_7d if r["created_at"] >= since_24h]

    bucket_24h = _compute_firewall_bucket(rows_24h)
    bucket_7d = _compute_firewall_bucket(rows_7d)

    worst = sorted(rows_7d, key=lambda r: float(r["strip_rate"]), reverse=True)[:10]
    offenders = [
        FirewallOffender(
            case_id=r["case_id"],
            section_key=(
                r.get("narrative_sections", {}).get("section_key", "unknown")
            ),
            strip_rate=round(float(r["strip_rate"]), 4),
            created_at=r["created_at"],
        )
        for r in worst
    ]

    return FirewallStatsResponse(
        last_24h=bucket_24h,
        last_7d=bucket_7d,
        worst_offenders=offenders,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_firewall_bucket(rows: list[dict]) -> FirewallBucket:
    if not rows:
        return FirewallBucket(
            total_narratives=0,
            avg_strip_rate=0.0,
            p95_strip_rate=0.0,
            narratives_above_20pct=0,
        )

    per_case: dict[str, list[dict]] = {}
    for r in rows:
        per_case.setdefault(r["case_id"], []).append(r)

    narrative_rates: list[float] = []
    for case_rows in per_case.values():
        t_stripped = sum(int(r["stripped_count"]) for r in case_rows)
        t_cited = sum(int(r["total_cited_count"]) for r in case_rows)
        narrative_rates.append(t_stripped / t_cited if t_cited else 0.0)

    narrative_rates.sort()
    avg = sum(narrative_rates) / len(narrative_rates)
    p95_idx = min(
        int(math.ceil(0.95 * len(narrative_rates))) - 1, len(narrative_rates) - 1
    )
    p95 = narrative_rates[max(0, p95_idx)]
    above_20 = sum(1 for r in narrative_rates if r > 0.2)

    return FirewallBucket(
        total_narratives=len(per_case),
        avg_strip_rate=round(avg, 4),
        p95_strip_rate=round(p95, 4),
        narratives_above_20pct=above_20,
    )


def _compute_bucket(rows: list[dict]) -> CostBucket:
    if not rows:
        return CostBucket(
            investigations=0,
            total_cost_usd=0.0,
            avg_cost_usd=0.0,
            p95_cost_usd=0.0,
        )

    costs = sorted(float(r["cost_usd"]) for r in rows)
    total = sum(costs)
    avg = total / len(costs)
    p95_idx = min(int(math.ceil(0.95 * len(costs))) - 1, len(costs) - 1)
    p95 = costs[max(0, p95_idx)]

    return CostBucket(
        investigations=len(costs),
        total_cost_usd=round(total, 4),
        avg_cost_usd=round(avg, 4),
        p95_cost_usd=round(p95, 4),
    )


def _count_anomalies(rows_24h: list[dict], rows_7d: list[dict]) -> int:
    """Count how many of the last-24h runs would be flagged as anomalous.

    Uses the 7d window (excluding the row under test) as the baseline,
    applying the same thresholds as cost_monitor.
    """
    if len(rows_7d) < 5:
        return 0

    all_costs = [float(r["cost_usd"]) for r in rows_7d]
    mean = sum(all_costs) / len(all_costs)
    if mean <= 0:
        return 0

    variance = sum((c - mean) ** 2 for c in all_costs) / len(all_costs)
    stddev = math.sqrt(variance)

    count = 0
    for row in rows_24h:
        cost = float(row["cost_usd"])
        if cost > ABSOLUTE_COST_THRESHOLD_USD:
            count += 1
        elif stddev > 0 and cost > mean + STDDEV_MULTIPLIER * stddev:
            count += 1
        elif cost > RATIO_MULTIPLIER * mean:
            count += 1
    return count
