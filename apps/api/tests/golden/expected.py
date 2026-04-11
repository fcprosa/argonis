"""
Golden-set expected outputs — deterministic assertions only.

Each entry maps a fixture name to the structural properties that MUST hold
regardless of prompt wording, model version, or non-deterministic LLM output.

Confidence ranges are deliberately wide to accommodate variance between
Supabase-backed gather (DB mode) and stub-only gather (no-DB mode), since
KYC profiles differ between the two paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DetectorExpectation:
    """Expected state for a single Step 4 pattern detector."""

    should_fire: bool
    confidence_min: float = 0.0
    confidence_max: float = 1.0


@dataclass(frozen=True)
class GoldenExpectation:
    """Full structural expectation for one golden fixture."""

    detectors: dict[str, DetectorExpectation]
    min_evidence_items: int
    section_keys: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "subject_information",
                "suspicious_activity_summary",
                "detailed_narrative",
                "supporting_evidence",
            }
        )
    )
    min_section_content_length: int = 200
    max_cost_usd: float = 5.0


# ── Detector field names on AnalysisResult ────────────────────────────────
DETECTOR_NAMES = ("structuring", "layering", "funnel", "velocity", "geographic_risk")


# ── Per-fixture expectations ──────────────────────────────────────────────

EXPECTATIONS: dict[str, GoldenExpectation] = {
    # ------------------------------------------------------------------
    # 1. Structuring — 12 sub-threshold cash deposits over 6 days
    #
    # Fires: structuring (12 candidates, multi-branch → confidence 1.0)
    #        velocity   (114K in 6 days vs 80K/month expected → ~0.85)
    #        funnel     (all inbound, zero outbound, corroborated → ~0.70)
    # Clear: layering   (no outbound → no rapid in-out pairs)
    #        geographic (US nationality, not on FATF list)
    # ------------------------------------------------------------------
    "structuring": GoldenExpectation(
        detectors={
            "structuring": DetectorExpectation(True, 0.90, 1.0),
            "layering": DetectorExpectation(False),
            "funnel": DetectorExpectation(True, 0.55, 0.80),
            "velocity": DetectorExpectation(True, 0.75, 0.85),
            "geographic_risk": DetectorExpectation(False),
        },
        min_evidence_items=25,
    ),
    # ------------------------------------------------------------------
    # 2. TBML — round-dollar in/out pairs to shell entities, IR nationality
    #
    # Fires: layering       (5 rapid in-out pairs + "unknown" counterparties)
    #        velocity       (444K in 8 days vs 200K/month expected)
    #        geographic_risk (nationality IR → FATF high-risk)
    # Clear: structuring    (amounts 48-100K, all above 10K threshold)
    #        funnel         (has outbound wire_transfers)
    # ------------------------------------------------------------------
    "tbml": GoldenExpectation(
        detectors={
            "structuring": DetectorExpectation(False),
            "layering": DetectorExpectation(True, 0.70, 0.85),
            "funnel": DetectorExpectation(False),
            "velocity": DetectorExpectation(True, 0.75, 0.85),
            "geographic_risk": DetectorExpectation(True, 0.55, 0.90),
        },
        min_evidence_items=15,
    ),
    # ------------------------------------------------------------------
    # 3. Funnel account — 30 inbound credits, zero outbound in window
    #
    # Fires: funnel   (30 inbound credits, 0 outbound, corroborated)
    #        velocity (91K in 5 days vs 100K/month expected → ~0.85)
    # Clear: structuring    (amounts 2.1-3.9K, below 8K lower bound)
    #        layering       (no outbound, no "unknown" counterparties)
    #        geographic_risk (US nationality)
    # ------------------------------------------------------------------
    "funnel": GoldenExpectation(
        detectors={
            "structuring": DetectorExpectation(False),
            "layering": DetectorExpectation(False),
            "funnel": DetectorExpectation(True, 0.55, 0.80),
            "velocity": DetectorExpectation(True, 0.75, 0.85),
            "geographic_risk": DetectorExpectation(False),
        },
        min_evidence_items=35,
    ),
    # ------------------------------------------------------------------
    # 4. Velocity anomaly — dormant account, 450K in 48 hours
    #
    # Fires: velocity (450K in 2 days vs 50K/month → massive spike)
    #        layering (6 deposits + 2 wires all within 2-day window)
    # Clear: structuring    (amounts 45-70K, above threshold)
    #        funnel         (has outbound wire_transfers)
    #        geographic_risk (US nationality)
    # ------------------------------------------------------------------
    "velocity": GoldenExpectation(
        detectors={
            "structuring": DetectorExpectation(False),
            "layering": DetectorExpectation(True, 0.50, 0.85),
            "funnel": DetectorExpectation(False),
            "velocity": DetectorExpectation(True, 0.75, 0.85),
            "geographic_risk": DetectorExpectation(False),
        },
        min_evidence_items=15,
    ),
    # ------------------------------------------------------------------
    # 5. Geographic risk — wires to FATF high-risk jurisdiction (Myanmar)
    #
    # Fires: geographic_risk (nationality MM → FATF list; stub-mode KYC
    #        also contributes a registration_country hit)
    # Clear: structuring (amounts 25-35K, above threshold)
    #        layering    (all outbound → no inbound for rapid pairs)
    #        funnel      (no inbound types in transaction list)
    #        velocity    (180K over 15 days vs 500K/month → below spike)
    # ------------------------------------------------------------------
    "geographic": GoldenExpectation(
        detectors={
            "structuring": DetectorExpectation(False),
            "layering": DetectorExpectation(False),
            "funnel": DetectorExpectation(False),
            "velocity": DetectorExpectation(False),
            "geographic_risk": DetectorExpectation(True, 0.55, 0.90),
        },
        min_evidence_items=12,
    ),
    # ------------------------------------------------------------------
    # 6. Partial screening — normal structuring alert, but OpenSanctions
    #    API is deliberately broken to test soft-fail behavior.
    #    Detector expectations mirror a basic structuring pattern.
    # ------------------------------------------------------------------
    "partial_screening": GoldenExpectation(
        detectors={
            "structuring": DetectorExpectation(True, 0.85, 1.0),
            "layering": DetectorExpectation(False),
            "funnel": DetectorExpectation(True, 0.55, 0.80),
            "velocity": DetectorExpectation(True, 0.75, 0.85),
            "geographic_risk": DetectorExpectation(False),
        },
        min_evidence_items=15,
    ),
    # ------------------------------------------------------------------
    # 7. Missing KYC — normal structuring alert, but with NO matching
    #    kyc_profiles row. Tests the synthetic profile / data gap path.
    # ------------------------------------------------------------------
    "missing_kyc": GoldenExpectation(
        detectors={
            "structuring": DetectorExpectation(True, 0.85, 1.0),
            "layering": DetectorExpectation(False),
            "funnel": DetectorExpectation(True, 0.55, 0.80),
            "velocity": DetectorExpectation(True, 0.75, 0.85),
            "geographic_risk": DetectorExpectation(False),
        },
        min_evidence_items=15,
    ),
}
