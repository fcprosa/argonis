"""
EvidencePipeline — evidence-first AML investigation pipeline.

Architecture
============
Step 1  PARSE      Pure Python parsing. Deterministic.
Step 2  GATHER     DB/API queries. Deterministic. Stub fallback when no DB.
Step 3  SCREEN     Sanctions/PEP APIs. Deterministic. Stub fallback when no key.
Step 4  ANALYZE    Python pattern detection. Fully deterministic.
Step 5  NARRATE    LLM receives ONLY the evidence package from Steps 1-4.
                   Every claim must cite a specific EVID-XXX id.

Steps 1-4 produce no hallucinations — they are pure functions over real data.
Step 5 cannot hallucinate new facts — it can only reference verified evidence.

Usage
-----
    pipeline = EvidencePipeline()
    result = await pipeline.run(alert_dict)
    print(result.narrative.case_title)
    print(result.narrative.sar_required)
"""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.pipeline.models import EvidencePipelineResult
from app.pipeline.step1_parse import parse_alert
from app.pipeline.step2_gather import gather_data
from app.pipeline.step3_screen import screen_entities
from app.pipeline.step4_analyze import analyze
from app.pipeline.step5_narrate import build_evidence_package, narrate

logger = logging.getLogger(__name__)


class EvidencePipeline:
    """Orchestrates the 5-step evidence-first investigation pipeline."""

    def __init__(
        self,
        api_key: str | None = None,
        supabase_url: str = "",
        supabase_key: str = "",
        opensanctions_api_key: str = "",
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._supabase_url = supabase_url
        self._supabase_key = supabase_key
        self._opensanctions_api_key = opensanctions_api_key

    async def run(self, alert: dict[str, Any]) -> EvidencePipelineResult:
        """Run all 5 steps sequentially. Steps 1-4 are deterministic; Step 5 calls the LLM."""

        # ── Step 1: PARSE ────────────────────────────────────────────────────
        logger.info("▶ step=1/5 parse")
        parsed = parse_alert(alert)
        logger.info(
            "  ✓ step=parse alert_id=%s txns=%d total=%s %s",
            parsed.alert_id,
            parsed.transaction_count,
            parsed.total_amount,
            parsed.transactions[0].currency if parsed.transactions else "",
        )

        # ── Step 2: GATHER ───────────────────────────────────────────────────
        logger.info("▶ step=2/5 gather")
        gathered = await gather_data(
            parsed,
            supabase_url=self._supabase_url,
            supabase_key=self._supabase_key,
        )
        logger.info(
            "  ✓ step=gather kyc_profiles=%d relationships=%d source=%s",
            len(gathered.kyc_profiles),
            len(gathered.account_relationships),
            gathered.source_metadata.get("source", "?"),
        )

        # ── Step 3: SCREEN ───────────────────────────────────────────────────
        logger.info("▶ step=3/5 screen")
        screening = await screen_entities(
            parsed,
            opensanctions_api_key=self._opensanctions_api_key,
            supabase_url=self._supabase_url,
            supabase_key=self._supabase_key,
        )
        logger.info(
            "  ✓ step=screen entities=%d hits=%d sources=%s",
            len(screening.entity_names),
            len(screening.hits),
            screening.sources_queried,
        )

        # ── Step 4: ANALYZE ──────────────────────────────────────────────────
        logger.info("▶ step=4/5 analyze")
        analysis = analyze(parsed, gathered)
        logger.info(
            "  ✓ step=analyze risk_score=%.3f action=%s patterns=%s",
            analysis.overall_risk_score,
            analysis.recommended_action,
            [
                k
                for k, d in {
                    "structuring": analysis.structuring,
                    "layering": analysis.layering,
                    "funnel": analysis.funnel,
                    "velocity": analysis.velocity,
                    "geographic_risk": analysis.geographic_risk,
                }.items()
                if d.detected
            ],
        )

        # ── Assemble evidence package (deterministic) ────────────────────────
        evidence_items = build_evidence_package(parsed, gathered, screening, analysis)
        logger.info("  ✓ evidence_package size=%d", len(evidence_items))

        # ── Step 5: NARRATE (LLM) ────────────────────────────────────────────
        logger.info("▶ step=5/5 narrate (LLM)")
        narrative = await narrate(parsed, evidence_items, self._client)
        logger.info(
            "  ✓ step=narrate title=%r sar=%s action=%s cited=%d",
            narrative.case_title,
            narrative.sar_required,
            narrative.recommended_action,
            len(narrative.evidence_ids_cited),
        )

        return EvidencePipelineResult(
            parsed_alert=parsed,
            gathered_data=gathered,
            screening_bundle=screening,
            analysis_result=analysis,
            evidence_items=evidence_items,
            narrative=narrative,
        )
