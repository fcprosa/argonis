"""
Pydantic output models for each investigation pipeline step.

DESIGN RULE: Every field must be something Claude can fill from evidence
present in the alert or prior step outputs — no hallucination scaffolding.
"""

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Step 1 — Alert Triage
# ---------------------------------------------------------------------------

class AlertTriage(BaseModel):
    severity: Literal["low", "medium", "high", "critical"]
    risk_type: str = Field(
        description=(
            "Primary risk typology, e.g. structuring, money_laundering, "
            "fraud, sanctions_evasion, terrorism_financing, bribery"
        )
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in this triage classification, 0.0–1.0",
    )
    requires_immediate_action: bool = Field(
        description="True if the alert cannot wait for normal review queue"
    )
    summary: str = Field(
        description="One sentence: what happened and why this severity was assigned"
    )


# ---------------------------------------------------------------------------
# Step 2 — Entity Extraction
# ---------------------------------------------------------------------------

class ExtractedEntity(BaseModel):
    name: str
    entity_type: Literal["person", "organization", "account", "jurisdiction"]
    role: str = Field(
        description=(
            "Role in the transaction or alert, e.g. account_holder, "
            "beneficial_owner, sender, receiver, intermediary"
        )
    )
    identifiers: list[str] = Field(
        default_factory=list,
        description="Any IDs, passport numbers, account numbers, etc. associated with this entity",
    )


class TransactionAmount(BaseModel):
    amount: float
    currency: str = Field(description="ISO 4217 currency code, e.g. GBP, USD, EUR")
    direction: Literal["inbound", "outbound", "unknown"]
    date: str | None = Field(default=None, description="ISO 8601 date if determinable")
    transaction_type: str | None = Field(
        default=None,
        description="e.g. cash_deposit, wire_transfer, card_payment",
    )


class EntityExtraction(BaseModel):
    entities: list[ExtractedEntity]
    amounts: list[TransactionAmount]
    jurisdictions: list[str] = Field(
        description="ISO 3166-1 alpha-2 country codes present in or implied by the alert"
    )
    date_range: str | None = Field(
        default=None,
        description="Human-readable date range of transactions if determinable, e.g. '2026-03-10 to 2026-03-13'",
    )


# ---------------------------------------------------------------------------
# Step 3 — Risk Assessment
# ---------------------------------------------------------------------------

class RiskFactor(BaseModel):
    factor: str = Field(description="Short name of the AML/financial crime red flag")
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Severity of this specific risk factor, 0.0–1.0",
    )
    evidence: str = Field(
        description=(
            "Verbatim or closely paraphrased evidence from the alert "
            "that supports this risk factor — must cite a specific field or value"
        )
    )


class RiskAssessment(BaseModel):
    overall_risk_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Weighted overall risk score across all factors, 0.0–1.0",
    )
    risk_factors: list[RiskFactor] = Field(
        description="Each identified AML/financial crime red flag with evidence"
    )
    recommended_action: Literal["dismiss", "monitor", "investigate", "escalate", "file_sar"]
    rationale: str = Field(
        description=(
            "Concise explanation of why this action is recommended, "
            "referencing the most significant risk factors"
        )
    )


# ---------------------------------------------------------------------------
# Step 4 — Investigation Summary
# ---------------------------------------------------------------------------

class EvidenceItem(BaseModel):
    description: str = Field(description="What the evidence shows")
    source: str = Field(
        description="Where this evidence came from, e.g. 'alert.transactions', 'screening_results', 'entity_extraction'"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence that this evidence is accurate and relevant, 0.0–1.0",
    )


class InvestigationSummary(BaseModel):
    case_title: str = Field(
        description="Short, descriptive title for the case file, max 80 characters"
    )
    key_findings: list[str] = Field(
        description="The most important findings, each as a single specific sentence"
    )
    evidence_items: list[EvidenceItem] = Field(
        description=(
            "Structured evidence record — every key_finding must map to "
            "at least one evidence_item"
        )
    )
    next_steps: list[str] = Field(
        description="Specific, actionable next steps for the analyst, in priority order"
    )
    sar_required: bool = Field(
        description="Whether a Suspicious Activity Report must be filed"
    )
    sar_grounds: str | None = Field(
        default=None,
        description=(
            "Regulatory/legal grounds for the SAR (required when sar_required=True), "
            "e.g. 'POCA 2002 s.330 — failure to disclose knowledge or suspicion of money laundering'"
        ),
    )
