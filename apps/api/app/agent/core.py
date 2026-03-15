"""
InvestigationPipeline — sequential AML investigation pipeline.

Architecture:
    • Each step forces a specific tool call (tool_choice: {type: tool, name: ...})
      so Claude MUST return structured JSON matching the Pydantic schema.
      This eliminates free-text drift and parsing ambiguity.
    • Adaptive thinking is enabled on every step so Claude reasons deeply
      before committing to field values.
    • Token usage (input, output, cache) is accumulated across all steps.
    • Transient errors (rate-limit, server errors) are retried with
      exponential backoff + jitter before propagating.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.agent.models import (
    AlertTriage,
    EntityExtraction,
    InvestigationSummary,
    RiskAssessment,
)
from app.agent.steps import STEPS, PipelineStep

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-6"
MAX_TOKENS = 8192          # high enough for thinking + structured output
MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0     # seconds, doubled each attempt


# ---------------------------------------------------------------------------
# Token tracking
# ---------------------------------------------------------------------------

@dataclass
class StepUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def __str__(self) -> str:
        parts = [f"in={self.input_tokens}", f"out={self.output_tokens}"]
        if self.cache_creation_tokens:
            parts.append(f"cache_create={self.cache_creation_tokens}")
        if self.cache_read_tokens:
            parts.append(f"cache_read={self.cache_read_tokens}")
        return " ".join(parts)


@dataclass
class TokenUsage:
    steps: dict[str, StepUsage] = field(default_factory=dict)

    @property
    def total_input(self) -> int:
        return sum(s.input_tokens for s in self.steps.values())

    @property
    def total_output(self) -> int:
        return sum(s.output_tokens for s in self.steps.values())

    @property
    def total(self) -> int:
        return self.total_input + self.total_output

    def record(self, step_name: str, usage: anthropic.types.Usage) -> None:
        self.steps[step_name] = StepUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )

    def summary(self) -> str:
        lines = [
            f"  {name:<28} {usage}"
            for name, usage in self.steps.items()
        ]
        lines.append(
            f"  {'TOTAL':<28} in={self.total_input} out={self.total_output}"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    alert_triage: AlertTriage
    entity_extraction: EntityExtraction
    risk_assessment: RiskAssessment
    investigation_summary: InvestigationSummary
    token_usage: TokenUsage


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class InvestigationPipeline:
    """
    Runs the four-step investigation pipeline for a single alert.

    Each step:
        1. Builds a prompt from the alert text + prior step outputs.
        2. Calls Claude with forced tool_choice → structured JSON output.
        3. Validates the JSON into the step's Pydantic model.
        4. Accumulates token usage.
        5. Retries up to ``max_retries`` times on transient API errors.

    Usage::

        pipeline = InvestigationPipeline()
        result = await pipeline.run(alert_dict)
        print(result.investigation_summary.case_title)
        print(result.token_usage.summary())
    """

    def __init__(
        self,
        api_key: str | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._max_retries = max_retries

    async def run(self, alert: dict[str, Any]) -> PipelineResult:
        """Run all steps sequentially. Each step output feeds the next."""
        alert_text = _format_alert(alert)
        ctx: dict[str, Any] = {"alert_text": alert_text}
        usage = TokenUsage()
        step_outputs: dict[str, Any] = {}

        for step in STEPS:
            logger.info("▶ step=%s", step.name)
            raw_output, step_usage = await self._run_step_with_retry(step, ctx)

            try:
                model_output = step.output_model(**raw_output)
            except Exception as exc:
                raise ValueError(
                    f"Step '{step.name}' returned invalid structured output: {exc}\n"
                    f"Raw output: {json.dumps(raw_output, indent=2)}"
                ) from exc

            step_outputs[step.name] = model_output
            usage.record(step.name, step_usage)

            # Serialise into context so subsequent steps can read it
            ctx[step.name] = model_output.model_dump_json(indent=2)

            logger.info(
                "  ✓ step=%s %s",
                step.name,
                usage.steps[step.name],
            )

        logger.info("Pipeline complete.\n%s", usage.summary())

        return PipelineResult(
            alert_triage=step_outputs["alert_triage"],
            entity_extraction=step_outputs["entity_extraction"],
            risk_assessment=step_outputs["risk_assessment"],
            investigation_summary=step_outputs["investigation_summary"],
            token_usage=usage,
        )

    # ------------------------------------------------------------------
    # Retry wrapper
    # ------------------------------------------------------------------

    async def _run_step_with_retry(
        self,
        step: PipelineStep,
        ctx: dict[str, Any],
    ) -> tuple[dict[str, Any], anthropic.types.Usage]:
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                return await self._call_step(step, ctx)

            except anthropic.RateLimitError as exc:
                last_error = exc
                delay = BASE_RETRY_DELAY * (2**attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "Rate limited on step=%s attempt=%d/%d — sleeping %.1fs",
                    step.name, attempt + 1, self._max_retries, delay,
                )
                await asyncio.sleep(delay)

            except (anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
                last_error = exc
                delay = BASE_RETRY_DELAY * (2**attempt)
                logger.warning(
                    "Server error on step=%s attempt=%d/%d — sleeping %.0fs: %s",
                    step.name, attempt + 1, self._max_retries, delay, exc,
                )
                await asyncio.sleep(delay)

            # Auth / bad-request errors are not retryable — let them propagate

        raise RuntimeError(
            f"Step '{step.name}' failed after {self._max_retries} attempts"
        ) from last_error

    # ------------------------------------------------------------------
    # Single API call
    # ------------------------------------------------------------------

    async def _call_step(
        self,
        step: PipelineStep,
        ctx: dict[str, Any],
    ) -> tuple[dict[str, Any], anthropic.types.Usage]:
        """
        Call Claude with:
          - forced tool_choice → guaranteed structured output
          - adaptive thinking  → deep reasoning before committing to field values
          - streaming          → avoids HTTP timeout on long reasoning chains

        Returns (tool_input_dict, usage).
        """
        async with self._client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=step.system_prompt,
            tools=[step.tool],
            tool_choice={"type": "tool", "name": step.tool_name},
            messages=[
                {"role": "user", "content": step.build_prompt(ctx)}
            ],
        ) as stream:
            message = await stream.get_final_message()

        # Forced tool_choice guarantees exactly one tool_use block
        tool_block = next(
            (b for b in message.content if b.type == "tool_use"),
            None,
        )
        if tool_block is None:
            raise RuntimeError(
                f"Step '{step.name}': no tool_use block in response. "
                f"stop_reason={message.stop_reason}"
            )

        return tool_block.input, message.usage  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_alert(alert: dict[str, Any]) -> str:
    """Pretty-print the alert dict, expanding any embedded JSON strings."""
    lines: list[str] = []
    for key, value in alert.items():
        if isinstance(value, str):
            # Try to pretty-print embedded JSON (e.g. transactions field)
            try:
                parsed = json.loads(value)
                lines.append(f"{key}:\n{json.dumps(parsed, indent=2)}")
                continue
            except (json.JSONDecodeError, ValueError):
                pass
        lines.append(f"{key}: {value}")
    return "\n\n".join(lines)
