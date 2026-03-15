"""
Pipeline step definitions.

Each step wraps a Pydantic output model as a forced-tool-use schema,
which guarantees structured JSON output — Claude must call the named tool
and fill every required field. This eliminates free-text drift.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.agent.models import (
    AlertTriage,
    EntityExtraction,
    InvestigationSummary,
    RiskAssessment,
)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _add_additional_properties_false(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively add ``additionalProperties: false`` to every object node.

    Required for structured outputs — without this, Claude may include extra
    fields that break Pydantic validation.
    """
    schema = copy.deepcopy(schema)

    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        if "properties" in schema:
            schema["properties"] = {
                k: _add_additional_properties_false(v)
                for k, v in schema["properties"].items()
            }

    if "items" in schema:
        schema["items"] = _add_additional_properties_false(schema["items"])

    if "$defs" in schema:
        schema["$defs"] = {
            k: _add_additional_properties_false(v)
            for k, v in schema["$defs"].items()
        }

    # anyOf / allOf / oneOf — recurse into each branch
    for key in ("anyOf", "allOf", "oneOf"):
        if key in schema:
            schema[key] = [_add_additional_properties_false(s) for s in schema[key]]

    return schema


def _tool_from_model(
    name: str,
    description: str,
    model: type[BaseModel],
) -> dict[str, Any]:
    """Convert a Pydantic model to an Anthropic tool definition with strict schema."""
    schema = _add_additional_properties_false(model.model_json_schema())
    return {"name": name, "description": description, "input_schema": schema}


# ---------------------------------------------------------------------------
# PipelineStep
# ---------------------------------------------------------------------------

@dataclass
class PipelineStep:
    name: str
    tool_name: str
    output_model: type[BaseModel]
    system_prompt: str
    build_prompt: Callable[[dict[str, Any]], str]
    # Tool definition is built lazily and cached
    _tool_cache: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    @property
    def tool(self) -> dict[str, Any]:
        if not self._tool_cache:
            self._tool_cache.update(
                _tool_from_model(
                    self.tool_name,
                    f"Submit the structured {self.name} result",
                    self.output_model,
                )
            )
        return self._tool_cache


# ---------------------------------------------------------------------------
# Step registry
# ---------------------------------------------------------------------------

STEPS: list[PipelineStep] = [

    PipelineStep(
        name="alert_triage",
        tool_name="submit_triage",
        output_model=AlertTriage,
        system_prompt=(
            "You are a senior AML/financial crime analyst with 15 years of experience. "
            "Triage incoming alerts to determine severity and risk classification. "
            "Be precise and evidence-based. "
            "Use ONLY information present in the alert — do not infer facts not stated."
        ),
        build_prompt=lambda ctx: (
            "Triage the following financial crime alert. "
            "Determine severity, risk type, and whether immediate action is required.\n\n"
            f"ALERT:\n{ctx['alert_text']}"
        ),
    ),

    PipelineStep(
        name="entity_extraction",
        tool_name="submit_entities",
        output_model=EntityExtraction,
        system_prompt=(
            "You are a financial intelligence analyst specializing in entity extraction. "
            "Extract ALL named entities, transaction amounts, and jurisdictions from the alert. "
            "Do not infer or fabricate — extract only what is explicitly stated. "
            "Assign entity types and roles based strictly on what the alert says."
        ),
        build_prompt=lambda ctx: (
            "Extract all entities, transaction amounts, and jurisdictions from this alert.\n\n"
            f"ALERT:\n{ctx['alert_text']}\n\n"
            f"TRIAGE CONTEXT:\n{ctx.get('alert_triage', 'N/A')}"
        ),
    ),

    PipelineStep(
        name="risk_assessment",
        tool_name="submit_risk",
        output_model=RiskAssessment,
        system_prompt=(
            "You are a risk assessment specialist in financial crime compliance. "
            "Evaluate this case against established AML red flags, FATF typologies, "
            "and sector-specific guidance. "
            "For each risk factor, you MUST cite specific evidence from the alert "
            "or prior step outputs — never score a factor without evidence."
        ),
        build_prompt=lambda ctx: (
            "Assess the financial crime risk for this case.\n\n"
            f"ALERT:\n{ctx['alert_text']}\n\n"
            f"TRIAGE:\n{ctx.get('alert_triage', 'N/A')}\n\n"
            f"EXTRACTED ENTITIES:\n{ctx.get('entity_extraction', 'N/A')}"
        ),
    ),

    PipelineStep(
        name="investigation_summary",
        tool_name="submit_summary",
        output_model=InvestigationSummary,
        system_prompt=(
            "You are a compliance officer producing investigation summaries for case files. "
            "Synthesize all prior analysis into a structured summary. "
            "Every key finding MUST be supported by at least one evidence_item. "
            "Every evidence_item MUST cite its source field. "
            "Be concise but complete — this summary is the primary record of the investigation."
        ),
        build_prompt=lambda ctx: (
            "Produce a complete investigation summary for this case file.\n\n"
            f"ALERT:\n{ctx['alert_text']}\n\n"
            f"TRIAGE:\n{ctx.get('alert_triage', 'N/A')}\n\n"
            f"EXTRACTED ENTITIES:\n{ctx.get('entity_extraction', 'N/A')}\n\n"
            f"RISK ASSESSMENT:\n{ctx.get('risk_assessment', 'N/A')}"
        ),
    ),
]
