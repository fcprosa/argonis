"""
LLM cost anomaly detection.

Observability layer — never blocks the pipeline. Logs warnings when a single
investigation's cost deviates significantly from the recent baseline. This
catches prompt regressions (a bad Step 5 rewrite that 20× token usage) before
they show up on the Anthropic bill.

Thresholds:
  WARNING   — cost > mean + 3σ OR cost > 5× mean (statistical outlier)
  CRITICAL  — cost > $2.00 absolute (40%+ of the ~$5 per-case budget cap)
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

ABSOLUTE_COST_THRESHOLD_USD = 2.00
STDDEV_MULTIPLIER = 3.0
RATIO_MULTIPLIER = 5.0
BASELINE_WINDOW = 50


async def check_cost_anomaly(
    case_id: str,
    cost_usd: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Check whether this investigation's LLM cost is anomalous.

    Queries the last BASELINE_WINDOW rows from llm_usage_log (excluding the
    current case) to compute a rolling baseline. Logs structured warnings
    when the current run deviates.

    Never raises — this is observability, not enforcement.
    """
    try:
        await _check(case_id, cost_usd, input_tokens, output_tokens)
    except Exception as exc:
        logger.debug("Cost anomaly check failed (non-blocking): %s", exc)


async def _check(
    case_id: str,
    cost_usd: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    from app.db import get_service_db

    # ── Absolute threshold — no baseline needed ──────────────────────
    if cost_usd > ABSOLUTE_COST_THRESHOLD_USD:
        logger.critical(
            "Single investigation cost $%.2f — 40%%+ of per-case budget. "
            "Investigate immediately. case_id=%s input_tokens=%d output_tokens=%d",
            cost_usd,
            case_id,
            input_tokens,
            output_tokens,
        )

    # ── Statistical anomaly — compare against recent baseline ────────
    db = await get_service_db()

    baseline_result = await (
        db.table("llm_usage_log")
        .select("cost_usd, input_tokens, output_tokens")
        .neq("case_id", case_id)
        .order("created_at", desc=True)
        .limit(BASELINE_WINDOW)
        .execute()
    )

    rows = baseline_result.data or []
    if len(rows) < 5:
        # Not enough history to compute a meaningful baseline
        return

    costs = [float(r["cost_usd"]) for r in rows]
    in_tokens = [int(r["input_tokens"]) for r in rows]
    out_tokens = [int(r["output_tokens"]) for r in rows]

    cost_mean = sum(costs) / len(costs)
    cost_stddev = _stddev(costs, cost_mean)

    # Guard against zero/near-zero baselines (e.g. all free-tier runs)
    if cost_mean <= 0:
        return

    is_stddev_outlier = cost_stddev > 0 and cost_usd > cost_mean + STDDEV_MULTIPLIER * cost_stddev
    is_ratio_outlier = cost_usd > RATIO_MULTIPLIER * cost_mean
    ratio = cost_usd / cost_mean

    if is_stddev_outlier or is_ratio_outlier:
        in_mean = sum(in_tokens) / len(in_tokens)
        out_mean = sum(out_tokens) / len(out_tokens)

        logger.warning(
            "Cost anomaly detected: case_id=%s cost_usd=%.4f "
            "baseline_mean=%.4f baseline_stddev=%.4f ratio=%.1fx "
            "input_tokens=%d (mean=%.0f) output_tokens=%d (mean=%.0f) "
            "trigger=%s",
            case_id,
            cost_usd,
            cost_mean,
            cost_stddev,
            ratio,
            input_tokens,
            in_mean,
            output_tokens,
            out_mean,
            "stddev" if is_stddev_outlier else "ratio",
        )


def _stddev(values: list[float], mean: float) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)
