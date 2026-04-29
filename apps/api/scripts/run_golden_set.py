#!/usr/bin/env python3
"""
Golden-set CLI runner — daily narrative-quality regression tool.

Runs the full evidence-first pipeline against all canonical AML typologies,
prints a summary table (one row per typology, including CRASH rows), writes
full narratives to latest_run/<typology>.md for
human review, and exits 0 on success / 1 on any failure.

Usage:
    cd apps/api
    python scripts/run_golden_set.py
    python scripts/run_golden_set.py --typology structuring   # single case

Environment variables required:
    ANTHROPIC_API_KEY          — Claude API key for Step 5 (narrate)
    SUPABASE_URL (optional)    — enables DB-backed gather in Step 2
    SUPABASE_SERVICE_KEY (opt) — service-role key for Supabase
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_API_ROOT = Path(__file__).resolve().parent.parent

# Load repo-root .env before any app import (Pydantic reads os.environ).
_DOTENV = Path("/Users/daniel/argonis/.env")
if _DOTENV.is_file():
    load_dotenv(_DOTENV, override=False)
else:
    _fallback = _API_ROOT.parent / ".env"
    load_dotenv(_fallback, override=False)

# Import sanitizer (needs apps/api on path; no app.config yet).
sys.path.insert(0, str(_API_ROOT))
from app.env_parse import sanitize_env_secret


def _peek_secret_env(name: str, raw: str | None, cleaned: str) -> None:
    """Temporary debug: first 10 + last 5 of raw (post-dotenv) and cleaned (os.environ)."""
    def frag(s: str | None) -> str:
        if s is None:
            return "<unset>"
        if not s:
            return "<empty>"
        if len(s) <= 15:
            return repr(s)
        return f"{s[:10]}…{s[-5:]}"

    print(f"[env debug] {name} raw (after load_dotenv): {frag(raw)} len={len(raw or '')}", flush=True)
    print(f"[env debug] {name} cleaned (after sanitize): {frag(cleaned)} len={len(cleaned)}", flush=True)
    if raw is not None and raw != cleaned:
        reasons: list[str] = []
        if raw.strip() != raw:
            reasons.append("leading/trailing whitespace")
        if "\r" in raw:
            reasons.append("contains \\r")
        if "\n" in raw:
            reasons.append("contains \\n")
        if raw.startswith("\ufeff"):
            reasons.append("UTF-8 BOM prefix")
        if (len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'")) or (
            len(cleaned) >= 2 and raw != cleaned and raw.strip().startswith(("'", '"'))
        ):
            reasons.append("outer quotes (stripped)")
        print(
            f"[env debug] {name} raw≠cleaned ({'; '.join(reasons) or 'normalized'}) "
            f"raw: {frag(raw)} len_raw={len(raw)}",
            flush=True,
        )


for _secret_key in ("ANTHROPIC_API_KEY", "OPENSANCTIONS_API_KEY"):
    _raw = os.environ.get(_secret_key)
    _cleaned = sanitize_env_secret(_raw)
    os.environ[_secret_key] = _cleaned
    _peek_secret_env(_secret_key, _raw, _cleaned)

if not os.environ.get("ANTHROPIC_API_KEY"):
    print(
        "\033[91mERRO: ANTHROPIC_API_KEY em falta no .env\033[0m",
        file=sys.stderr,
    )
    sys.exit("ERRO: ANTHROPIC_API_KEY em falta no .env")

from app.config import settings
from app.pipeline.core import EvidencePipeline
from app.pipeline.models import EvidencePipelineResult

from tests.golden.expected import (
    DETECTOR_NAMES,
    EXPECTATIONS,
    GoldenExpectation,
)

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden"
OUTPUT_DIR = GOLDEN_DIR / "latest_run"

TYPOLOGIES = sorted(EXPECTATIONS.keys())

# partial_screening deliberately uses a broken OpenSanctions key
_PARTIAL_SCREENING_TYPOLOGY = "partial_screening"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run_single(
    typology: str,
    pipeline: EvidencePipeline,
) -> tuple[EvidencePipelineResult, float]:
    """Run the pipeline for one typology, return (result, wall_clock_seconds)."""
    fixture_path = GOLDEN_DIR / f"{typology}.json"
    alert_data: dict[str, Any] = json.loads(fixture_path.read_text())

    if typology == _PARTIAL_SCREENING_TYPOLOGY:
        partial_pipeline = EvidencePipeline(
            api_key=settings.anthropic_api_key or None,
            supabase_url=settings.supabase_url,
            supabase_key=settings.supabase_service_key,
            opensanctions_api_key="INVALID_KEY_FOR_PARTIAL_SCREENING_TEST",
            serper_api_key=settings.serper_api_key,
        )
        t0 = time.monotonic()
        result = await partial_pipeline.run(alert_data)
    else:
        t0 = time.monotonic()
        result = await pipeline.run(alert_data)
    duration = time.monotonic() - t0

    return result, duration


def check_expectations(
    typology: str,
    result: EvidencePipelineResult,
    expectation: GoldenExpectation,
) -> list[str]:
    """Return a list of failure messages (empty = pass)."""
    failures: list[str] = []
    analysis = result.analysis_result
    narrative = result.narrative

    for name in DETECTOR_NAMES:
        detection = getattr(analysis, name)
        expected = expectation.detectors[name]

        if detection.detected != expected.should_fire:
            failures.append(
                f"{name}: expected detected={expected.should_fire}, "
                f"got {detection.detected}"
            )
        elif expected.should_fire:
            if not (expected.confidence_min <= detection.confidence <= expected.confidence_max):
                failures.append(
                    f"{name}: confidence {detection.confidence:.3f} "
                    f"outside [{expected.confidence_min}, {expected.confidence_max}]"
                )

    actual_keys = {s.section_key for s in narrative.sections}
    if actual_keys != set(expectation.section_keys):
        failures.append(f"section_keys: expected {expectation.section_keys}, got {actual_keys}")

    for section in narrative.sections:
        if len(section.content) < expectation.min_section_content_length:
            failures.append(
                f"section '{section.section_key}': {len(section.content)} chars "
                f"< {expectation.min_section_content_length} min"
            )

    if len(result.evidence_items) < expectation.min_evidence_items:
        failures.append(
            f"evidence_items: {len(result.evidence_items)} "
            f"< {expectation.min_evidence_items} min"
        )

    if result.llm_usage and result.llm_usage.cost_usd >= expectation.max_cost_usd:
        failures.append(
            f"cost: ${result.llm_usage.cost_usd:.4f} >= ${expectation.max_cost_usd} budget"
        )

    if typology == "missing_kyc":
        gathered = result.gathered_data
        if not gathered or not gathered.kyc_profiles:
            failures.append("missing_kyc: expected at least one (synthetic) KYC profile")
        elif not gathered.kyc_profiles[0].is_synthetic:
            failures.append("missing_kyc: KYC profile should be is_synthetic=True")
        if not gathered or not gathered.data_gaps:
            failures.append("missing_kyc: data_gaps should be non-empty")

        subject = next(
            (s for s in (narrative.sections if narrative else [])
             if s.section_key == "subject_information"),
            None,
        )
        if subject and "Subject KYC profile was not found" not in subject.content:
            failures.append("missing_kyc: Subject Information missing KYC warning text")

    if typology == _PARTIAL_SCREENING_TYPOLOGY:
        if not result.screening_bundle or not result.screening_bundle.is_partial:
            failures.append("partial_screening: screening should be is_partial=True")
        if result.screening_bundle and not any(
            "OpenSanctions" in g for g in result.screening_bundle.coverage_gaps
        ):
            failures.append(
                f"partial_screening: coverage_gaps should mention OpenSanctions, "
                f"got {result.screening_bundle.coverage_gaps}"
            )
        if narrative and not narrative.is_partial_screening:
            failures.append("partial_screening: narrative.is_partial_screening should be True")

    return failures


def write_narrative_md(typology: str, result: EvidencePipelineResult) -> Path:
    """Write the narrative to latest_run/<typology>.md and return the path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        f"# {result.narrative.case_title}",
        "",
        f"**Typology:** {typology}",
        f"**SAR required:** {result.narrative.sar_required}",
        f"**SAR grounds:** {result.narrative.sar_grounds or 'N/A'}",
        f"**Recommended action:** {result.narrative.recommended_action}",
        f"**Evidence IDs cited:** {len(result.narrative.evidence_ids_cited)}",
        "",
    ]

    if result.llm_usage:
        lines.extend([
            "## LLM Usage",
            "",
            f"| Field | Value |",
            f"|---|---|",
            f"| Model | {result.llm_usage.model} |",
            f"| Input tokens | {result.llm_usage.input_tokens:,} |",
            f"| Output tokens | {result.llm_usage.output_tokens:,} |",
            f"| Cost (USD) | ${result.llm_usage.cost_usd:.4f} |",
            f"| Duration (ms) | {result.llm_usage.duration_ms or 'N/A'} |",
            "",
        ])

    analysis = result.analysis_result
    lines.extend([
        "## Detectors",
        "",
        "| Detector | Fired | Confidence |",
        "|---|---|---|",
    ])
    for name in DETECTOR_NAMES:
        det = getattr(analysis, name)
        lines.append(
            f"| {name} | {'YES' if det.detected else 'no'} "
            f"| {det.confidence:.3f} |"
        )
    lines.extend([
        "",
        f"**Overall risk:** {analysis.overall_risk_score:.3f}",
        f"**Recommended action:** {analysis.recommended_action}",
        "",
    ])

    if result.narrative.is_partial_screening:
        lines.extend([
            "## Screening Coverage Warning",
            "",
            "**INCOMPLETE SCREENING:** This investigation was conducted with partial "
            "screening coverage.",
            "",
            "Unavailable sources:",
            "",
        ])
        for gap in result.narrative.screening_gaps:
            lines.append(f"- {gap}")
        lines.extend(["", "---", ""])

    if result.firewall_results:
        lines.extend([
            "## Firewall Strip Rates",
            "",
            "| Section | Kept | Stripped | Strip Rate |",
            "|---|---|---|---|",
        ])
        for fw in result.firewall_results:
            lines.append(
                f"| {fw.section_key} | {len(fw.kept_ids)} "
                f"| {len(fw.stripped_ids)} | {fw.strip_rate:.1%} |"
            )
        lines.append("")

    for section in result.narrative.sections:
        lines.extend([
            f"## {section.title}",
            f"*section_key: {section.section_key} · {len(section.content)} chars*",
            "",
            section.content,
            "",
        ])

    out_path = OUTPUT_DIR / f"{typology}.md"
    out_path.write_text("\n".join(lines))
    return out_path


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------


def print_summary(
    typologies: list[str],
    results: dict[str, tuple[EvidencePipelineResult, float, list[str]]],
    crashed: dict[str, str],
) -> None:
    """Print a formatted summary table to stdout (one row per typology, incl. CRASH)."""
    col_w = {
        "typology": 18,
        "detectors": 40,
        "cost": 10,
        "duration": 10,
        "sections": 50,
        "strip": 40,
        "status": 8,
    }
    sep = "+" + "+".join("-" * (w + 2) for w in col_w.values()) + "+"
    header = (
        f"| {'Typology':<{col_w['typology']}} "
        f"| {'Detectors Fired':<{col_w['detectors']}} "
        f"| {'Cost':<{col_w['cost']}} "
        f"| {'Duration':<{col_w['duration']}} "
        f"| {'Section Lengths':<{col_w['sections']}} "
        f"| {'Strip Rates':<{col_w['strip']}} "
        f"| {'Status':<{col_w['status']}} |"
    )

    print()
    print(sep)
    print(header)
    print(sep)

    for typology in typologies:
        if typology in crashed:
            err = crashed[typology][:120] + ("…" if len(crashed[typology]) > 120 else "")
            print(
                f"| {typology:<{col_w['typology']}} "
                f"| {'(crash)':<{col_w['detectors']}} "
                f"| {'N/A':<{col_w['cost']}} "
                f"| {'N/A':<{col_w['duration']}} "
                f"| {'N/A':<{col_w['sections']}} "
                f"| {'N/A':<{col_w['strip']}} "
                f"| {'CRASH':<{col_w['status']}} |"
            )
            print(f"|   CRASH: {err}")
            continue

        if typology not in results:
            print(
                f"| {typology:<{col_w['typology']}} "
                f"| {'(skipped)':<{col_w['detectors']}} "
                f"| {'N/A':<{col_w['cost']}} "
                f"| {'N/A':<{col_w['duration']}} "
                f"| {'N/A':<{col_w['sections']}} "
                f"| {'N/A':<{col_w['strip']}} "
                f"| {'SKIP':<{col_w['status']}} |"
            )
            continue

        result, duration, failures = results[typology]
        analysis = result.analysis_result
        usage = result.llm_usage

        fired = [n for n in DETECTOR_NAMES if getattr(analysis, n).detected]
        fired_str = ", ".join(fired) if fired else "(none)"

        cost_str = f"${usage.cost_usd:.4f}" if usage else "N/A"
        dur_str = f"{duration:.1f}s"

        section_lens = {s.section_key: len(s.content) for s in result.narrative.sections}
        sec_parts = [
            f"{k[:4]}={v}" for k, v in sorted(section_lens.items())
        ]
        sec_str = " ".join(sec_parts)

        fw_map = {fw.section_key: fw.strip_rate for fw in result.firewall_results}
        strip_parts = [
            f"{k[:4]}={v:.0%}" for k, v in sorted(fw_map.items())
        ]
        strip_str = " ".join(strip_parts) if strip_parts else "N/A"

        status = "FAIL" if failures else "PASS"

        print(
            f"| {typology:<{col_w['typology']}} "
            f"| {fired_str:<{col_w['detectors']}} "
            f"| {cost_str:<{col_w['cost']}} "
            f"| {dur_str:<{col_w['duration']}} "
            f"| {sec_str:<{col_w['sections']}} "
            f"| {strip_str:<{col_w['strip']}} "
            f"| {status:<{col_w['status']}} |"
        )

        if failures:
            for f in failures:
                print(f"|   FAIL: {f}")

    print(sep)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(typologies: list[str]) -> bool:
    """Run golden set. Returns True if all pass."""
    pipeline = EvidencePipeline(
        api_key=settings.anthropic_api_key or None,
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_key,
        opensanctions_api_key=settings.opensanctions_api_key,
        serper_api_key=settings.serper_api_key,
    )

    all_results: dict[str, tuple[EvidencePipelineResult, float, list[str]]] = {}
    crashed: dict[str, str] = {}
    all_pass = True

    for typology in typologies:
        expectation = EXPECTATIONS[typology]
        print(f"\n▶ Running {typology}…", flush=True)

        try:
            result, duration = await run_single(typology, pipeline)
        except Exception as exc:
            print(f"  ✗ {typology} — pipeline crashed: {exc}", file=sys.stderr)
            crashed[typology] = str(exc)
            all_pass = False
            continue

        failures = check_expectations(typology, result, expectation)
        all_results[typology] = (result, duration, failures)

        md_path = write_narrative_md(typology, result)
        cost_str = f"${result.llm_usage.cost_usd:.4f}" if result.llm_usage else "N/A"
        status = "PASS" if not failures else "FAIL"
        print(f"  {'✓' if not failures else '✗'} {typology} — {status} "
              f"(cost={cost_str}, duration={duration:.1f}s, narrative={md_path.name})")

        if failures:
            all_pass = False
            for f in failures:
                print(f"    FAIL: {f}")

    print_summary(typologies, all_results, crashed)

    total_cost = sum(
        r.llm_usage.cost_usd
        for r, _, _ in all_results.values()
        if r.llm_usage
    )
    total_duration = sum(d for _, d, _ in all_results.values())
    passed = sum(1 for _, _, f in all_results.values() if not f)
    failed = sum(1 for _, _, f in all_results.values() if f)
    crashed = len(typologies) - len(all_results)

    print(f"\nTotal: {passed} passed, {failed} failed, {crashed} crashed")
    print(f"Total cost: ${total_cost:.4f}")
    print(f"Total duration: {total_duration:.1f}s")
    print(f"Narratives written to: {OUTPUT_DIR}/")

    return all_pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run golden-set regression harness for AML pipeline narratives"
    )
    parser.add_argument(
        "--typology",
        choices=TYPOLOGIES,
        help="Run a single typology instead of all 5",
    )
    args = parser.parse_args()

    selected = [args.typology] if args.typology else TYPOLOGIES
    success = asyncio.run(main(selected))
    sys.exit(0 if success else 1)
