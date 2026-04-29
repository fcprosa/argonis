"""
Qualitative compliance overlays (post–Step 4, pre–evidence package).

FATF-style risk factors that weighted pattern scores under-represent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.pipeline.models import (
    AnalysisResult,
    GatheredData,
    OverlayFinding,
    ParsedAlert,
)

# ---------------------------------------------------------------------------
# Reference data — auditable policy inputs
# ---------------------------------------------------------------------------

SANCTIONED_OR_HIGH_RISK_COUNTRIES = frozenset(
    {
        "AF",
        "BY",
        "BI",
        "CF",
        "CG",
        "CD",
        "CU",
        "ER",
        "ET",
        "GN",
        "GW",
        "HT",
        "IR",
        "IQ",
        "KP",
        "LY",
        "ML",
        "MM",
        "NI",
        "RU",
        "SO",
        "SS",
        "SD",
        "SY",
        "VE",
        "YE",
        "ZW",
    }
)

SENSITIVE_SECTORS: dict[str, list[str]] = {
    "precious_stones_metals": [
        "gemstone",
        "gem stone",
        "precious stone",
        "diamond",
        "ruby",
        "emerald",
        "sapphire",
        "jade",
        "precious metal",
        "gold trading",
        "gold refin",
        "bullion",
    ],
    "extractive_industries": [
        "oil",
        "petroleum",
        "crude",
        "natural gas",
        "lng",
        "mining",
        "mineral extraction",
        "rare earth",
        "uranium",
    ],
    "timber_forestry": [
        "timber",
        "hardwood",
        "logging",
        "teak",
        "rosewood",
    ],
    "arms_dual_use": [
        "arms",
        "weapon",
        "firearm",
        "ammunition",
        "defense export",
        "military equipment",
        "dual-use",
        "dual use",
    ],
    "art_antiquities": [
        "antiquit",
        "cultural artifact",
        "fine art dealer",
        "auction house",
    ],
    "crypto_informal_transfer": [
        "crypto",
        "virtual asset",
        "hawala",
        "money service business",
        "money remit",
    ],
}


RecommendedAction = Literal["dismiss", "monitor", "investigate", "escalate", "file_sar"]


@dataclass(frozen=True)
class RiskOverlay:
    rule_id: str
    description: str
    min_risk_score: float
    min_recommended_action: RecommendedAction
    regulatory_basis: str


OVERLAYS: tuple[RiskOverlay, ...] = (
    RiskOverlay(
        rule_id="SANCTIONED_JURISDICTION_SENSITIVE_SECTOR",
        description=(
            "Beneficial owner or registered entity is linked to a sanctioned or "
            "FATF high-risk jurisdiction AND operates in a sector subject to "
            "enhanced due diligence (precious stones, extractives, timber, arms, "
            "antiquities, or informal value transfer). This combination requires "
            "mandatory enhanced scrutiny under FATF Recommendation 10 and relevant "
            "sectoral sanctions regimes."
        ),
        min_risk_score=0.50,
        min_recommended_action="escalate",
        regulatory_basis=(
            "FATF Recommendation 10 (CDD), FATF Recommendation 19 (high-risk "
            "countries), U.S. Burma-related sanctions and sectoral measures, "
            "EU Council Regulation 401/2013 concerning restrictive measures "
            "in respect of Myanmar, EU Regulation 833/2014 concerning measures "
            "in respect of Russia."
        ),
    ),
    RiskOverlay(
        rule_id="SANCTIONED_JURISDICTION_NEW_ACCOUNT",
        description=(
            "Beneficial owner or registered entity is linked to a sanctioned or "
            "FATF high-risk jurisdiction AND the account is less than 90 days old. "
            "New accounts from high-risk jurisdictions require enhanced onboarding "
            "review and ongoing monitoring."
        ),
        min_risk_score=0.35,
        min_recommended_action="investigate",
        regulatory_basis=(
            "Directive (EU) 2018/1673 (AMLD6) provisions on enhanced customer due "
            "diligence for high-risk third countries, FATF Recommendation 19."
        ),
    ),
    RiskOverlay(
        rule_id="SENSITIVE_SECTOR_MISSING_KYC",
        description=(
            "Customer operates in a sector subject to enhanced due diligence AND "
            "no KYC profile was available at the time of investigation. Operating "
            "in a sensitive sector without a verified KYC profile is a Category 1 "
            "compliance deficiency and must be remediated before further "
            "transactions are processed."
        ),
        min_risk_score=0.35,
        min_recommended_action="investigate",
        regulatory_basis=(
            "Directive (EU) 2018/1673 (AMLD6) customer due diligence requirements, "
            "FATF Recommendation 10."
        ),
    ),
)

_ACTION_ORDER = (
    "dismiss",
    "monitor",
    "investigate",
    "escalate",
    "file_sar",
)


def country_is_flagged(country_code: str | None) -> bool:
    if not country_code:
        return False
    c = country_code.strip().upper()[:2]
    return len(c) == 2 and c.isalpha() and c in SANCTIONED_OR_HIGH_RISK_COUNTRIES


def classify_sector(business_type: str | None) -> list[str]:
    if not business_type:
        return []
    hay = business_type.lower()
    matched: list[str] = []
    for cat, needles in SENSITIVE_SECTORS.items():
        if any(n in hay for n in needles):
            matched.append(cat)
    return matched


def _alpha2_fields(parsed: ParsedAlert, gathered: GatheredData) -> set[str]:
    codes: set[str] = set()
    n = parsed.nationality
    if n:
        codes.add(n.strip().upper()[:2])
    j = parsed.jurisdiction.strip().upper() if parsed.jurisdiction else ""
    if len(j) == 2 and j.isalpha():
        codes.add(j)
    for kyc in gathered.kyc_profiles:
        for raw in (
            kyc.nationality,
            kyc.registration_country,
            kyc.country_of_residence,
        ):
            if raw and len(raw.strip()) >= 2:
                c = raw.strip().upper()[:2]
                if c.isalpha():
                    codes.add(c)
    return {c for c in codes if country_is_flagged(c)}


def _any_flagged_country(parsed: ParsedAlert, gathered: GatheredData) -> tuple[bool, list[str]]:
    flagged = sorted(_alpha2_fields(parsed, gathered))
    return (len(flagged) > 0, [f"jurisdiction_country={c}" for c in flagged])


def evaluate_overlays(
    parsed: ParsedAlert,
    gathered: GatheredData,
    analysis: AnalysisResult,
) -> list[OverlayFinding]:
    _ = analysis  # reserved for future rules that reference detector output
    findings: list[OverlayFinding] = []
    has_flagged, country_factors = _any_flagged_country(parsed, gathered)
    sectors = classify_sector(parsed.business_type)
    sector_factors = [f"sensitive_sector={s}" for s in sectors]
    bt_factor = [f"business_type={parsed.business_type!r}"] if parsed.business_type else []

    # Rule 1 — sanctioned / high-risk jurisdiction + sensitive sector
    if has_flagged and sectors:
        factors = [*country_factors, *sector_factors, *bt_factor]
        ro = OVERLAYS[0]
        findings.append(
            OverlayFinding(
                rule_id=ro.rule_id,
                description=ro.description,
                regulatory_basis=ro.regulatory_basis,
                matched_factors=factors,
                min_risk_score=ro.min_risk_score,
                min_recommended_action=ro.min_recommended_action,
            )
        )

    # Rule 2 — flagged jurisdiction + new account (<90 days)
    if has_flagged and parsed.account_age_days is not None and parsed.account_age_days < 90:
        factors = [
            *country_factors,
            f"account_age_days={parsed.account_age_days}",
        ]
        ro = OVERLAYS[1]
        findings.append(
            OverlayFinding(
                rule_id=ro.rule_id,
                description=ro.description,
                regulatory_basis=ro.regulatory_basis,
                matched_factors=factors,
                min_risk_score=ro.min_risk_score,
                min_recommended_action=ro.min_recommended_action,
            )
        )

    # Rule 3 — sensitive sector + missing KYC
    kyc_missing = any(
        (g or "").strip().startswith("KYC_PROFILE_MISSING") for g in gathered.data_gaps
    )
    if sectors and kyc_missing:
        gap_hits = [
            g
            for g in gathered.data_gaps
            if (g or "").strip().startswith("KYC_PROFILE_MISSING")
        ]
        factors = [*sector_factors, *bt_factor, *[f"data_gap={g}" for g in gap_hits]]
        ro = OVERLAYS[2]
        findings.append(
            OverlayFinding(
                rule_id=ro.rule_id,
                description=ro.description,
                regulatory_basis=ro.regulatory_basis,
                matched_factors=factors,
                min_risk_score=ro.min_risk_score,
                min_recommended_action=ro.min_recommended_action,
            )
        )

    return findings


def apply_overlays(
    analysis: AnalysisResult,
    findings: list[OverlayFinding],
) -> AnalysisResult:
    if not findings:
        return analysis
    max_score = max(analysis.overall_risk_score, *(f.min_risk_score for f in findings))
    max_score = min(1.0, round(max_score, 3))
    act_idx = max(
        _ACTION_ORDER.index(analysis.recommended_action),
        max(_ACTION_ORDER.index(f.min_recommended_action) for f in findings),
    )
    new_action = _ACTION_ORDER[act_idx]
    return analysis.model_copy(
        update={
            "overall_risk_score": max_score,
            "recommended_action": new_action,
            "overlay_findings": list(findings),
        }
    )
