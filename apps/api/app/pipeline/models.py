"""
Shared Pydantic models for the evidence-first investigation pipeline.

Steps 1-4 are deterministic (no LLM). Step 5 is the only LLM call.
Every model here represents verified, structured data — not LLM output.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OverlayFinding(BaseModel):
    """Qualitative compliance rule fired after quantitative pattern analysis."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    description: str
    regulatory_basis: str
    matched_factors: list[str]
    min_risk_score: float = Field(ge=0.0, le=1.0)
    min_recommended_action: Literal[
        "dismiss", "monitor", "investigate", "escalate", "file_sar"
    ]


# ---------------------------------------------------------------------------
# Step 1: PARSE
# ---------------------------------------------------------------------------


class ParsedTransaction(BaseModel):
    txn_id: str = ""  # e.g. "AML-2026-00147-txn-000" — set by parse_alert
    date: date
    amount: Decimal
    currency: str
    type: str
    branch: str | None = None
    counterparty: str | None = None


class ParsedAlert(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    alert_id: str
    alert_type: str
    generated_at: datetime
    account_number: str
    account_holder: str
    jurisdiction: str
    transactions: list[ParsedTransaction]
    counterparties: str
    account_age_days: int
    prior_sar_count: int
    # Beneficial owner — raw string + parsed fields
    beneficial_owner_raw: str
    beneficial_owner_name: str
    nationality: str | None
    dob: date | None
    business_type: str
    expected_monthly_activity: str
    actual_activity_30d: str
    screening_hits_raw: str
    sanctions_hits_raw: str
    pep_hits_raw: str
    # Computed
    total_amount: Decimal
    transaction_count: int
    reporting_threshold: Decimal


# ---------------------------------------------------------------------------
# Step 2: GATHER
# ---------------------------------------------------------------------------


class KYCProfile(BaseModel):
    entity_name: str
    entity_type: Literal["person", "organization"]
    registration_number: str | None = None
    registration_country: str | None = None
    directors: list[str] = Field(default_factory=list)
    beneficial_owners: list[str] = Field(default_factory=list)
    kyc_tier: str = "standard"
    last_reviewed: date | None = None
    source: str  # "kyc_profiles" | "stub" | "missing_kyc"
    is_synthetic: bool = False
    pep_status: str | None = None
    risk_rating: str | None = None
    occupation: str | None = None
    source_of_funds: str | None = None
    date_of_birth: date | None = None
    nationality: str | None = None
    country_of_residence: str | None = None


class AccountRelationship(BaseModel):
    source_customer_id: str
    related_customer_id: str
    relationship_type: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source: str  # "account_relationships" | "stub"


class HistoricalAlert(BaseModel):
    alert_id: str
    alert_type: str
    date: str
    severity: str
    resolved: bool


class GatheredData(BaseModel):
    kyc_profiles: list[KYCProfile]
    account_relationships: list[AccountRelationship]
    historical_alerts: list[HistoricalAlert]
    source_metadata: dict[str, str]
    data_gaps: list[str] = Field(default_factory=list)
    relationships_available: bool = True


# ---------------------------------------------------------------------------
# Step 3: SCREEN
# ---------------------------------------------------------------------------


class ScreeningHit(BaseModel):
    entity_name: str
    list_name: str  # "OFAC_SDN", "UN_CONSOLIDATED", "PEP", "adverse_media"
    match_confidence: float = Field(ge=0.0, le=1.0)
    match_type: Literal["exact", "fuzzy", "alias", "phonetic", "keyword"]
    source_url: str | None = None
    snippet: str | None = None
    screened_at: datetime


class SourceResult(BaseModel):
    """Outcome of a single screening source (OFAC, OpenSanctions, adverse media)."""

    source_name: str
    status: Literal["success", "failed", "timeout", "rate_limited", "skipped"]
    matches: list[ScreeningHit] = Field(default_factory=list)
    error_message: str | None = None
    duration_ms: int = 0


class ScreeningBundle(BaseModel):
    entity_names: list[str]
    hits: list[ScreeningHit]
    sources_queried: list[str]
    screened_at: datetime
    source_results: list[SourceResult] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)
    """Analyst-facing gap messages (sanitized)."""
    coverage_gaps_debug: list[str] = Field(default_factory=list)
    """Raw technical errors for ops / pipeline_events only."""
    is_partial: bool = False


# ---------------------------------------------------------------------------
# Step 4: ANALYZE
# ---------------------------------------------------------------------------


class EvidenceFact(BaseModel):
    """
    A single piece of evidence produced by a deterministic pattern detector.

    For transaction evidence: txn_id, amount, and date are all set.
    For entity/account evidence (e.g. geographic risk): amount and date are None
    and txn_id carries a semantic identifier like "entity:RU" or "account:new_47d".
    """

    txn_id: str  # e.g. "AML-2026-00147-txn-000" or "entity:RU"
    amount: Decimal | None = None
    date: str | None = None  # ISO 8601
    detail: str  # human-readable explanation of why this is suspicious


class PatternDetection(BaseModel):
    detected: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceFact]


class AnalysisResult(BaseModel):
    structuring: PatternDetection
    layering: PatternDetection
    funnel: PatternDetection
    velocity: PatternDetection
    geographic_risk: PatternDetection
    overall_risk_score: float = Field(ge=0.0, le=1.0)
    high_risk_indicators: list[str]
    recommended_action: Literal["dismiss", "monitor", "investigate", "escalate", "file_sar"]
    overlay_findings: list[OverlayFinding] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Evidence package (assembled after Step 4, before Step 5)
# ---------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    id: str  # "EVID-001", "EVID-002", …
    category: str  # "transaction", "entity", "pattern", "screening", "account", "kyc", "analysis"
    description: str
    value: str
    source: str  # which step produced this
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


# ---------------------------------------------------------------------------
# Step 5: NARRATE
# ---------------------------------------------------------------------------


class NarrativeSection(BaseModel):
    section_key: str  # subject_information | suspicious_activity_summary | detailed_narrative | supporting_evidence
    title: str
    content: str  # prose with inline [EVID-XXX] citations


class NarrativeOutput(BaseModel):
    case_title: str
    sections: list[NarrativeSection]
    sar_required: bool
    sar_grounds: str | None = None
    recommended_action: Literal["dismiss", "monitor", "investigate", "escalate", "file_sar"]
    evidence_ids_cited: list[str]
    is_partial_screening: bool = False
    screening_gaps: list[str] = Field(default_factory=list)


class SectionFirewallResult(BaseModel):
    """Per-section results from the evidence firewall pass."""

    section_key: str
    kept_ids: list[str]
    stripped_ids: list[str]
    strip_rate: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# LLM usage / cost tracking
# ---------------------------------------------------------------------------


class LLMUsage(BaseModel):
    model: str
    step: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int | None = None


# Pipeline result
# ---------------------------------------------------------------------------


class StepError(BaseModel):
    step_name: str
    error_message: str


class EvidencePipelineResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    parsed_alert: ParsedAlert
    gathered_data: GatheredData
    screening_bundle: ScreeningBundle | None = None
    analysis_result: AnalysisResult | None = None
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    narrative: NarrativeOutput | None = None
    llm_usage: LLMUsage | None = None
    firewall_results: list[SectionFirewallResult] = Field(default_factory=list)
    step_errors: list[StepError] = Field(default_factory=list)
    halted: bool = False
