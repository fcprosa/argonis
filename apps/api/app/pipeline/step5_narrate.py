"""
Step 5: NARRATE — LLM-generated prose from structured evidence.

THIS IS THE ONLY STEP THAT USES THE LLM.

The LLM receives a numbered evidence list assembled from Steps 1-4.
Every factual claim in the output MUST cite a specific [EVID-XXX] ID.
If a fact has no evidence ID, it cannot appear in the narrative.

This architecture makes hallucination structurally impossible:
  - The LLM cannot invent new transactions (it has no alert text)
  - The LLM cannot cite non-existent IDs (validation strips them)
  - The LLM cannot recommend actions beyond what the evidence supports
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, Field

from app.pipeline.models import (
    AnalysisResult,
    EvidenceItem,
    GatheredData,
    NarrativeOutput,
    NarrativeSection,
    ParsedAlert,
    ScreeningBundle,
)

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-6"
MAX_TOKENS = 8192


# ---------------------------------------------------------------------------
# Evidence package builder (deterministic — no LLM)
# ---------------------------------------------------------------------------


def build_evidence_package(
    parsed: ParsedAlert,
    gathered: GatheredData,
    screening: ScreeningBundle,
    analysis: AnalysisResult,
) -> list[EvidenceItem]:
    """
    Assemble all facts from Steps 1-4 into a numbered evidence list.

    Every item gets a unique EVID-XXX id. This list is the ONLY data the
    LLM can reference in the narrative — it cannot see the raw alert.
    """
    items: list[EvidenceItem] = []

    def add(
        category: str,
        description: str,
        value: str,
        source: str,
        confidence: float = 1.0,
    ) -> str:
        evid = f"EVID-{len(items) + 1:03d}"
        items.append(
            EvidenceItem(
                id=evid,
                category=category,
                description=description,
                value=value,
                source=source,
                confidence=confidence,
            )
        )
        return evid

    # ---- Step 1: transactions ----
    for txn in parsed.transactions:
        branch_info = f" at {txn.branch}" if txn.branch else ""
        add(
            "transaction",
            f"Cash deposit on {txn.date.isoformat()}",
            f"{txn.amount} {txn.currency} ({txn.type}){branch_info}",
            "step1_parse",
        )

    # ---- Step 1: account metadata ----
    add("account", "Account holder", parsed.account_holder, "step1_parse")
    add("account", "Account number", parsed.account_number, "step1_parse")
    add("account", "Account age (days)", str(parsed.account_age_days), "step1_parse")
    add("account", "Business type", parsed.business_type, "step1_parse")
    add("account", "Beneficial owner", parsed.beneficial_owner_raw, "step1_parse")

    if parsed.nationality:
        add("entity", "Beneficial owner nationality", parsed.nationality, "step1_parse")

    add("account", "Expected monthly activity", parsed.expected_monthly_activity, "step1_parse")
    add("account", "Actual activity (30 days)", parsed.actual_activity_30d, "step1_parse")

    currency = parsed.transactions[0].currency if parsed.transactions else "GBP"
    add(
        "account",
        "Total transaction volume",
        f"{parsed.total_amount} {currency} across {parsed.transaction_count} transaction(s)",
        "step1_parse",
    )

    if parsed.prior_sar_count > 0:
        add(
            "account",
            "Prior SARs on this account",
            str(parsed.prior_sar_count),
            "step1_parse",
        )

    # ---- Step 2: KYC profiles ----
    for kyc in gathered.kyc_profiles:
        owners = ", ".join(kyc.beneficial_owners) if kyc.beneficial_owners else "N/A"
        add(
            "kyc",
            f"KYC profile: {kyc.entity_name}",
            (
                f"type={kyc.entity_type}, tier={kyc.kyc_tier}, "
                f"country={kyc.registration_country or 'unknown'}, "
                f"beneficial_owners=[{owners}], "
                f"last_reviewed={kyc.last_reviewed or 'unknown'}"
            ),
            "step2_gather",
        )

    # ---- Step 3: screening hits ----
    if screening.hits:
        for hit in screening.hits:
            add(
                "screening",
                f"Screening hit: {hit.entity_name} on {hit.list_name}",
                (
                    f"match_confidence={hit.match_confidence:.0%}, "
                    f"match_type={hit.match_type}. "
                    f"Source: {hit.source_url or 'N/A'}. "
                    f"Snippet: {(hit.snippet or 'N/A')[:200]}"
                ),
                "step3_screen",
                hit.match_confidence,
            )
    else:
        add(
            "screening",
            "Screening result",
            f"No sanctions or PEP hits found. Sources queried: {', '.join(screening.sources_queried)}",
            "step3_screen",
        )

    # ---- Step 4: pattern detections ----
    pattern_fields = [
        ("structuring", "Structuring / smurfing"),
        ("layering", "Layering"),
        ("funnel", "Funnel / one-directional flow"),
        ("velocity", "Velocity anomaly"),
        ("geographic_risk", "Geographic risk"),
    ]
    for attr, label in pattern_fields:
        detection = getattr(analysis, attr)
        if detection.detected:
            add(
                "pattern",
                f"Pattern detected: {label}",
                f"confidence={detection.confidence:.0%}; evidence: {'; '.join(detection.evidence)}",
                "step4_analyze",
                detection.confidence,
            )

    # Overall risk
    add(
        "analysis",
        "Overall risk assessment",
        f"risk_score={analysis.overall_risk_score:.0%}, recommended_action={analysis.recommended_action}",
        "step4_analyze",
        analysis.overall_risk_score,
    )

    for indicator in analysis.high_risk_indicators:
        add("analysis", "High-risk indicator", indicator, "step4_analyze")

    return items


# ---------------------------------------------------------------------------
# Internal schema for LLM forced tool use
# ---------------------------------------------------------------------------


class _NarrativeSectionInput(BaseModel):
    section_key: Literal["executive_summary", "background", "findings", "conclusion"]
    title: str
    content: str = Field(
        description=(
            "Prose for this section. "
            "Every factual claim MUST end with an inline citation [EVID-XXX]. "
            "Do NOT state any fact that is not in the provided evidence list."
        )
    )


class _NarrativeToolOutput(BaseModel):
    case_title: str = Field(
        max_length=80,
        description="Short case file title, max 80 characters",
    )
    sections: list[_NarrativeSectionInput] = Field(
        description="Four sections: executive_summary, background, findings, conclusion"
    )
    sar_required: bool
    sar_grounds: str | None = Field(
        default=None,
        description="Legal grounds for the SAR (required when sar_required=True)",
    )
    recommended_action: Literal["dismiss", "monitor", "investigate", "escalate", "file_sar"]
    evidence_ids_cited: list[str] = Field(
        description="All EVID-XXX IDs referenced in the sections content"
    )


# ---------------------------------------------------------------------------
# Narrate
# ---------------------------------------------------------------------------


async def narrate(
    parsed: ParsedAlert,
    evidence_items: list[EvidenceItem],
    client: anthropic.AsyncAnthropic,
) -> NarrativeOutput:
    """
    Generate the AML investigation narrative from structured evidence only.

    The LLM:
      MAY  — write prose connecting evidence items, cite [EVID-XXX] inline
      MAY  — recommend actions supported by the evidence
      MAY NOT — state any fact not present in the evidence list
      MAY NOT — introduce entities, amounts, or dates not in evidence
      MAY NOT — cite non-existent evidence IDs (validation strips them)
    """
    valid_ids = {item.id for item in evidence_items}

    system_prompt = """\
You are an expert AML Investigator writing a Suspicious Activity Report (SAR) narrative.
Your ONLY job is to assemble a formal prose narrative based STRICTLY on the provided `evidence_package`.

CRITICAL RULES (HALLUCINATION FIREWALL):
1. DO NOT include any information, names, dates, amounts, typologies, or assumptions that are not explicitly present in the evidence package.
2. Every single factual claim MUST be followed by its specific evidence ID in brackets. Example: "The subject account received $15,000 on March 1st [EVID-012]."
3. If evidence is missing or insufficient to complete ANY section, you MUST NOT invent details. Instead, output exactly this phrase for that section: "INSUFFICIENT EVIDENCE — REQUIRES HUMAN INPUT."
4. Incorporate relevant regulatory frameworks (e.g., BSA/AML, AMLD6, FATF red flags) when describing detected patterns, but ONLY if those specific patterns (e.g., structuring, layering) were flagged in the evidence package.

REQUIRED SAR NARRATIVE STRUCTURE:
You must output the narrative using the following exact sections. For each section, you must include a "Section Confidence Score" (0-100%) based on the strength, volume, and clarity of the provided evidence.

### 1. Introduction
[State the reason for the alert/investigation trigger based on the evidence]
Confidence Score: [X]%

### 2. Subject Information
[Summarize KYC profiles, account relationships, and any adverse media or sanctions screening results (OFAC, OpenSanctions, PEP) found in the evidence]
Confidence Score: [X]%

### 3. Suspicious Activity Analysis
[Detail the specific transaction patterns detected, such as structuring, layering, funnel accounts, velocity anomalies, or geographic risks. Reference specific transactions]
Confidence Score: [X]%

### 4. Conclusion
[Provide a final summary of the risk and the facts presented]
Confidence Score: [X]%\
"""

    user_prompt = (
        f"Write an AML investigation narrative for alert {parsed.alert_id}.\n\n"
        f"{_format_evidence(evidence_items)}\n\n"
        "Produce a structured narrative with all four required sections. "
        "Cite every fact with [EVID-XXX]. "
        "State whether a SAR must be filed and the legal grounds."
    )

    schema = _strict_schema(_NarrativeToolOutput.model_json_schema())
    tool = {
        "name": "submit_narrative",
        "description": "Submit the completed AML investigation narrative",
        "input_schema": schema,
    }

    logger.info("▶ step=narrate evidence_items=%d alert=%s", len(evidence_items), parsed.alert_id)

    async with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        tools=[tool],
        tool_choice={"type": "tool", "name": "submit_narrative"},
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        message = await stream.get_final_message()

    tool_block = next((b for b in message.content if b.type == "tool_use"), None)
    if tool_block is None:
        raise RuntimeError(
            f"step=narrate: no tool_use block in response (stop_reason={message.stop_reason})"
        )

    raw: dict[str, Any] = tool_block.input  # type: ignore[union-attr]
    validated = _NarrativeToolOutput(**raw)

    # Strip any hallucinated evidence IDs the LLM invented
    cited = [eid for eid in validated.evidence_ids_cited if eid in valid_ids]
    invalid = [eid for eid in validated.evidence_ids_cited if eid not in valid_ids]
    if invalid:
        logger.warning("step=narrate stripped non-existent evidence IDs: %s", invalid)

    logger.info(
        "  ✓ step=narrate title=%r sections=%d sar=%s cited=%d",
        validated.case_title,
        len(validated.sections),
        validated.sar_required,
        len(cited),
    )

    return NarrativeOutput(
        case_title=validated.case_title,
        sections=[
            NarrativeSection(
                section_key=s.section_key,
                title=s.title,
                content=s.content,
            )
            for s in validated.sections
        ],
        sar_required=validated.sar_required,
        sar_grounds=validated.sar_grounds,
        recommended_action=validated.recommended_action,
        evidence_ids_cited=cited,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_evidence(items: list[EvidenceItem]) -> str:
    """Format the evidence list for the LLM prompt."""
    lines = ["VERIFIED EVIDENCE — cite as [EVID-XXX]:\n"]
    for item in items:
        conf_note = f" [confidence: {item.confidence:.0%}]" if item.confidence < 1.0 else ""
        lines.append(
            f"{item.id} [{item.category.upper()}] {item.description}\n"
            f"  → {item.value}{conf_note}"
        )
    return "\n".join(lines)


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively add additionalProperties: false to all object nodes."""
    schema = copy.deepcopy(schema)
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        if "properties" in schema:
            schema["properties"] = {
                k: _strict_schema(v) for k, v in schema["properties"].items()
            }
    if "items" in schema:
        schema["items"] = _strict_schema(schema["items"])
    if "$defs" in schema:
        schema["$defs"] = {k: _strict_schema(v) for k, v in schema["$defs"].items()}
    for key in ("anyOf", "allOf", "oneOf"):
        if key in schema:
            schema[key] = [_strict_schema(s) for s in schema[key]]
    return schema
