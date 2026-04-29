"""Unit tests for qualitative compliance overlays (no DB, no LLM)."""

from __future__ import annotations

from typing import Any

from app.pipeline.compliance_overlays import apply_overlays, evaluate_overlays
from app.pipeline.models import (
    AnalysisResult,
    GatheredData,
    OverlayFinding,
    PatternDetection,
    ParsedAlert,
)
from app.pipeline.step1_parse import parse_alert


def _blank_detection() -> PatternDetection:
    return PatternDetection(detected=False, confidence=0.0, evidence=[])


def _analysis(
    *,
    overall_risk_score: float = 0.09,
    recommended_action: str = "dismiss",
) -> AnalysisResult:
    return AnalysisResult(
        structuring=_blank_detection(),
        layering=_blank_detection(),
        funnel=_blank_detection(),
        velocity=_blank_detection(),
        geographic_risk=_blank_detection(),
        overall_risk_score=overall_risk_score,
        high_risk_indicators=[],
        recommended_action=recommended_action,  # type: ignore[arg-type]
    )


def _gathered(**kwargs: Any) -> GatheredData:
    return GatheredData(
        kyc_profiles=kwargs.get("kyc_profiles", []),
        account_relationships=[],
        historical_alerts=[],
        source_metadata={},
        data_gaps=kwargs.get("data_gaps", []),
    )


def _base_alert(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "alert_id": "T-OVR-001",
        "alert_type": "test",
        "generated_at": "2026-04-01T12:00:00Z",
        "account_number": "0000",
        "account_holder": "Test Holder LLC",
        "jurisdiction": "US",
        "transactions": [
            {
                "date": "2026-03-01",
                "amount": 10000,
                "currency": "USD",
                "type": "wire_transfer",
            }
        ],
        "counterparties": "N/A",
        "account_age_days": 400,
        "prior_sar_count": 0,
        "beneficial_owner": "Test Person (DOB: 1980-01-01, nationality: DE)",
        "business_type": "Software consulting",
        "expected_monthly_activity": "Max USD 50,000/month",
        "actual_activity_30d": "USD 10,000",
        "screening_hits": "None",
        "sanctions_hits": "None",
        "pep_hits": "None",
    }
    base.update(overrides)
    return base


def test_myanmar_gemstone_fires_sanctioned_jurisdiction_sensitive_sector() -> None:
    raw = _base_alert(
        beneficial_owner="Kyaw Min Tun (DOB: 1980-05-19, nationality: MM)",
        business_type="Gemstone and hardwood importer",
    )
    parsed = parse_alert(raw)
    gathered = _gathered()
    analysis = _analysis()
    findings = evaluate_overlays(parsed, gathered, analysis)
    ids = [f.rule_id for f in findings]
    assert "SANCTIONED_JURISDICTION_SENSITIVE_SECTOR" in ids
    f = next(x for x in findings if x.rule_id == "SANCTIONED_JURISDICTION_SENSITIVE_SECTOR")
    assert f.min_risk_score == 0.50
    assert f.min_recommended_action == "escalate"


def test_russia_oil_fires() -> None:
    raw = _base_alert(
        beneficial_owner="Ivan Petrov (DOB: 1970-01-01, nationality: RU)",
        business_type="Crude oil trading",
    )
    parsed = parse_alert(raw)
    findings = evaluate_overlays(parsed, _gathered(), _analysis())
    assert any(f.rule_id == "SANCTIONED_JURISDICTION_SENSITIVE_SECTOR" for f in findings)


def test_iran_new_account_fires() -> None:
    raw = _base_alert(
        beneficial_owner="Ali Reza (DOB: 1985-01-01, nationality: IR)",
        business_type="Textile manufacturing",
        account_age_days=45,
    )
    parsed = parse_alert(raw)
    findings = evaluate_overlays(parsed, _gathered(), _analysis())
    assert any(f.rule_id == "SANCTIONED_JURISDICTION_NEW_ACCOUNT" for f in findings)
    assert not any(
        f.rule_id == "SANCTIONED_JURISDICTION_SENSITIVE_SECTOR" for f in findings
    )


def test_gemstone_missing_kyc_fires() -> None:
    raw = _base_alert(
        beneficial_owner="Jane Doe (DOB: 1990-01-01, nationality: US)",
        business_type="Diamond wholesale",
    )
    parsed = parse_alert(raw)
    gaps = ["KYC_PROFILE_MISSING: no row for account"]
    findings = evaluate_overlays(parsed, _gathered(data_gaps=gaps), _analysis())
    assert any(f.rule_id == "SENSITIVE_SECTOR_MISSING_KYC" for f in findings)
    f = next(x for x in findings if x.rule_id == "SENSITIVE_SECTOR_MISSING_KYC")
    assert f.min_recommended_action == "investigate"


def test_clean_case_fires_nothing() -> None:
    raw = _base_alert(account_age_days=400)
    parsed = parse_alert(raw)
    assert evaluate_overlays(parsed, _gathered(), _analysis()) == []


def test_apply_overlays_takes_maximum_floor() -> None:
    analysis = _analysis(overall_risk_score=0.20, recommended_action="monitor")
    f35 = OverlayFinding(
        rule_id="SANCTIONED_JURISDICTION_NEW_ACCOUNT",
        description="d1",
        regulatory_basis="r1",
        matched_factors=["x"],
        min_risk_score=0.35,
        min_recommended_action="investigate",
    )
    f50 = OverlayFinding(
        rule_id="SANCTIONED_JURISDICTION_SENSITIVE_SECTOR",
        description="d2",
        regulatory_basis="r2",
        matched_factors=["y"],
        min_risk_score=0.50,
        min_recommended_action="escalate",
    )
    result = apply_overlays(analysis, [f35, f50])
    assert result.overall_risk_score >= 0.50
    assert result.recommended_action == "escalate"
    assert len(result.overlay_findings) == 2


def test_apply_overlays_does_not_downgrade() -> None:
    analysis = _analysis(overall_risk_score=0.80, recommended_action="file_sar")
    f = OverlayFinding(
        rule_id="SENSITIVE_SECTOR_MISSING_KYC",
        description="d",
        regulatory_basis="r",
        matched_factors=["z"],
        min_risk_score=0.35,
        min_recommended_action="investigate",
    )
    result = apply_overlays(analysis, [f])
    assert result.overall_risk_score == 0.80
    assert result.recommended_action == "file_sar"
