"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { getCase, runInvestigation, exportNarrativePdf, ApiError } from "@/lib/api";
import type { CaseDetail, InvestigationStep, ScreeningResult } from "@/lib/types";
import {
  SAMPLE_CASE_DETAIL,
  parseAlertType,
  parseCustomerName,
  riskLabel,
  riskColors,
  statusMeta,
  fmtDate,
} from "@/lib/sample-data";
import { NarrativeViewer } from "@/components/NarrativeViewer";

// Pipeline step definitions — display order + labels
const PIPELINE_STEPS = [
  { key: "parse", label: "PARSE", desc: "Structured extraction" },
  { key: "gather", label: "GATHER", desc: "KYC & history" },
  { key: "screen", label: "SCREEN", desc: "OFAC + sanctions" },
  { key: "analyze", label: "ANALYZE", desc: "Pattern detection" },
  { key: "narrate", label: "NARRATE", desc: "AI narrative" },
] as const;

type PipelineKey = (typeof PIPELINE_STEPS)[number]["key"];

// Max polling duration: 5 minutes (pipeline can take 2-3 min with Claude)
const POLL_MAX_MS = 5 * 60 * 1000;
const POLL_INTERVAL_MS = 2000;

export default function CaseDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const { id } = params;

  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [demoMode, setDemoMode] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Investigation state
  const [investigating, setInvestigating] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollStartRef = useRef<number>(0);

  // ---------------------------------------------------------------------------
  // Load case
  // ---------------------------------------------------------------------------
  const loadCase = useCallback(async () => {
    try {
      const data = await getCase(id);
      setDetail(data);
      setDemoMode(false);
      return data;
    } catch (err) {
      // Try sample data
      const sample = SAMPLE_CASE_DETAIL[id];
      if (sample) {
        setDetail(sample);
        setDemoMode(true);
        return sample;
      }
      const msg =
        err instanceof ApiError
          ? `${err.httpStatus}: ${err.message}`
          : "Failed to load case";
      setError(msg);
      return null;
    }
  }, [id]);

  useEffect(() => {
    setLoading(true);
    loadCase().finally(() => setLoading(false));
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [loadCase]);

  // ---------------------------------------------------------------------------
  // Polling — re-fetch until narrative appears or timeout
  // ---------------------------------------------------------------------------
  const startPolling = useCallback(() => {
    pollStartRef.current = Date.now();

    async function tick() {
      const elapsed = Date.now() - pollStartRef.current;
      if (elapsed > POLL_MAX_MS) {
        setInvestigating(false);
        setPollError("Investigation timed out after 5 minutes.");
        return;
      }

      try {
        const fresh = await getCase(id);
        setDetail(fresh);

        // Done when narratives exist
        if (fresh.narratives.length > 0) {
          setInvestigating(false);
          setPollError(null);
          return;
        }

        // Error step detected
        const errStep = fresh.investigation_steps.find(
          (s) => s.name === "pipeline_error",
        );
        if (errStep) {
          setInvestigating(false);
          setPollError(`Pipeline error: ${errStep.description}`);
          return;
        }
      } catch {
        // transient network error — keep polling
      }

      pollRef.current = setTimeout(tick, POLL_INTERVAL_MS);
    }

    pollRef.current = setTimeout(tick, POLL_INTERVAL_MS);
  }, [id]);

  // ---------------------------------------------------------------------------
  // Export PDF
  // ---------------------------------------------------------------------------
  async function handleExportPdf() {
    if (!narrative) return;
    if (demoMode) {
      setExportError("Demo mode — PDF export requires live API");
      return;
    }
    setExportingPdf(true);
    setExportError(null);
    try {
      const blob = await exportNarrativePdf(narrative.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `narrative-${narrative.id.slice(-8).toUpperCase()}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(
        err instanceof ApiError ? err.message : "PDF export failed"
      );
    } finally {
      setExportingPdf(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Run investigation
  // ---------------------------------------------------------------------------
  async function handleRunInvestigation() {
    if (!detail || demoMode) return;
    setInvestigating(true);
    setPollError(null);

    try {
      const body = detail.case.alert_id
        ? { alert_id: detail.case.alert_id }
        : { alert_data: {} as Record<string, unknown> };
      await runInvestigation(body);
      startPolling();
    } catch (err) {
      setInvestigating(false);
      const msg =
        err instanceof ApiError
          ? `${err.httpStatus}: ${err.message}`
          : "Failed to start investigation";
      setPollError(msg);
    }
  }

  // ---------------------------------------------------------------------------
  // Derived values
  // ---------------------------------------------------------------------------
  const analyzeStep = detail?.investigation_steps.find(
    (s) => s.name === "analyze",
  );
  const riskScore =
    (analyzeStep?.confidence_score as number | null | undefined) ?? null;
  const completedStepKeys = new Set<string>(
    detail?.investigation_steps.map((s) => s.name) ?? [],
  );
  if ((detail?.narratives.length ?? 0) > 0) completedStepKeys.add("narrate");

  const narrative = detail?.narratives[0] ?? null;
  const caseTitle = detail?.case.title ?? "";
  const caseStatus = detail?.case.status ?? "open";
  const { label: statusLabel, classes: statusClasses } = statusMeta(caseStatus);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-gray-400 animate-pulse">Loading case…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2">
        <p className="text-sm text-red-600">{error}</p>
        <Link
          href="/dashboard"
          className="text-xs text-blue-600 hover:underline"
        >
          Back to queue
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Page header */}
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-gray-200 bg-white px-6">
        <Link
          href="/dashboard"
          className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
        >
          Alert Queue
        </Link>
        <span className="text-gray-300 text-xs">›</span>
        <span className="font-mono text-xs text-gray-500">
          {id.slice(-8).toUpperCase()}
        </span>
        {demoMode && (
          <span className="rounded bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-700 ring-1 ring-yellow-300">
            DEMO
          </span>
        )}
      </header>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
        {/* Case header card */}
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-xs text-gray-400 mb-1">
                {parseAlertType(caseTitle)}
              </p>
              <h2 className="text-base font-semibold text-gray-900 leading-tight">
                {parseCustomerName(caseTitle)}
              </h2>
              {detail?.case.description && (
                <p className="mt-1 text-xs text-gray-500 leading-relaxed">
                  {detail.case.description}
                </p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {riskScore != null && (
                <span
                  className={[
                    "rounded px-2 py-0.5 text-xs font-semibold",
                    riskColors(riskScore),
                  ].join(" ")}
                >
                  {riskLabel(riskScore)} · {(riskScore * 100).toFixed(0)}%
                </span>
              )}
              <span
                className={[
                  "rounded px-2 py-0.5 text-xs font-medium",
                  statusClasses,
                ].join(" ")}
              >
                {statusLabel}
              </span>
            </div>
          </div>
          <div className="mt-3 flex gap-6 text-xs text-gray-400">
            <span>
              Case{" "}
              <span className="font-mono text-gray-600">
                {id.slice(-8).toUpperCase()}
              </span>
            </span>
            {detail?.case.created_at && (
              <span>Created {fmtDate(detail.case.created_at)}</span>
            )}
            {detail?.case.updated_at && (
              <span>Updated {fmtDate(detail.case.updated_at)}</span>
            )}
          </div>
        </div>

        {/* Pipeline progress */}
        <PipelinePanel
          completedSteps={completedStepKeys}
          steps={detail?.investigation_steps ?? []}
          investigating={investigating}
          pollError={pollError}
          canRun={
            !demoMode &&
            !investigating &&
            completedStepKeys.size === 0 &&
            caseStatus === "open"
          }
          onRun={handleRunInvestigation}
        />

        {/* Screening results */}
        {(detail?.screening_results.length ?? 0) > 0 && (
          <ScreeningPanel results={detail!.screening_results} />
        )}

        {/* Narrative actions */}
        {narrative && (
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wider text-gray-400">
              Narrative · v{narrative.version}
            </p>
            <div className="flex items-center gap-2">
              {exportError && (
                <span className="text-xs text-red-500">{exportError}</span>
              )}
              <button
                onClick={handleExportPdf}
                disabled={exportingPdf}
                className="rounded border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {exportingPdf ? "Generating…" : "Export PDF"}
              </button>
            </div>
          </div>
        )}

        {/* Narrative viewer */}
        {narrative && (
          <NarrativeViewer
            narrative={narrative}
            evidenceLinks={detail?.evidence_links ?? []}
            overallConfidence={riskScore}
            demoMode={demoMode}
            onSectionApproved={async () => {
              const fresh = await loadCase();
              if (fresh) setDetail(fresh);
            }}
          />
        )}

        {/* Empty state — no investigation yet */}
        {!investigating &&
          completedStepKeys.size === 0 &&
          !narrative &&
          !demoMode && (
            <div className="rounded-lg border border-dashed border-gray-200 bg-white p-8 text-center">
              <p className="text-sm text-gray-400">
                No investigation results yet.
              </p>
              {caseStatus === "open" && (
                <button
                  onClick={handleRunInvestigation}
                  className="mt-3 rounded bg-[#111] px-4 py-2 text-xs font-semibold text-white hover:bg-gray-800 transition-colors"
                >
                  Run Investigation
                </button>
              )}
            </div>
          )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pipeline Panel
// ---------------------------------------------------------------------------

function PipelinePanel({
  completedSteps,
  steps,
  investigating,
  pollError,
  canRun,
  onRun,
}: {
  completedSteps: Set<string>;
  steps: InvestigationStep[];
  investigating: boolean;
  pollError: string | null;
  canRun: boolean;
  onRun: () => void;
}) {
  const hasAny = completedSteps.size > 0 || investigating;
  if (!hasAny && !canRun) return null;

  function stepStatus(key: PipelineKey): "done" | "running" | "pending" | "error" {
    const dbStep = steps.find((s) => s.name === key);
    if (dbStep?.status === "failed") return "error";
    if (completedSteps.has(key)) return "done";
    if (investigating) {
      // running = the first step that's not yet done
      const order = PIPELINE_STEPS.map((s) => s.key);
      const firstPending = order.find((k) => !completedSteps.has(k));
      if (firstPending === key) return "running";
    }
    return "pending";
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
          Investigation Pipeline
        </h3>
        {canRun && (
          <button
            onClick={onRun}
            className="rounded bg-[#111] px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-800 transition-colors"
          >
            Run Investigation
          </button>
        )}
        {investigating && (
          <span className="flex items-center gap-1.5 text-xs text-blue-600">
            <span className="inline-block h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
            Running…
          </span>
        )}
      </div>

      {/* Step row */}
      <div className="flex items-start gap-0">
        {PIPELINE_STEPS.map((step, i) => {
          const state = stepStatus(step.key);
          const dbStep = steps.find((s) => s.name === step.key);
          return (
            <div key={step.key} className="flex flex-1 items-start">
              <div className="flex flex-1 flex-col items-center gap-1.5">
                {/* Dot */}
                <div
                  className={[
                    "flex h-7 w-7 items-center justify-center rounded-full text-[10px] font-bold transition-colors",
                    state === "done"
                      ? "bg-green-500 text-white"
                      : state === "running"
                        ? "bg-blue-500 text-white animate-pulse"
                        : state === "error"
                          ? "bg-red-500 text-white"
                          : "bg-gray-100 text-gray-400",
                  ].join(" ")}
                >
                  {state === "done"
                    ? "✓"
                    : state === "error"
                      ? "✗"
                      : i + 1}
                </div>
                {/* Label */}
                <p
                  className={[
                    "text-[10px] font-semibold tracking-wide text-center",
                    state === "done"
                      ? "text-green-700"
                      : state === "running"
                        ? "text-blue-600"
                        : state === "error"
                          ? "text-red-600"
                          : "text-gray-300",
                  ].join(" ")}
                >
                  {step.label}
                </p>
                {/* Desc */}
                <p className="text-[10px] text-gray-400 text-center leading-tight hidden sm:block">
                  {state === "done" && dbStep?.description
                    ? dbStep.description
                    : step.desc}
                </p>
                {/* Confidence */}
                {state === "done" &&
                  dbStep?.confidence_score != null && (
                    <p className="text-[10px] text-gray-400">
                      {(dbStep.confidence_score * 100).toFixed(0)}%
                    </p>
                  )}
              </div>
              {/* Connector line */}
              {i < PIPELINE_STEPS.length - 1 && (
                <div
                  className={[
                    "mt-3.5 h-px flex-none w-full max-w-[40px] transition-colors",
                    completedSteps.has(step.key)
                      ? "bg-green-300"
                      : "bg-gray-100",
                  ].join(" ")}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Poll error */}
      {pollError && (
        <p className="mt-3 text-xs text-red-600 border-t border-red-100 pt-3">
          {pollError}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Screening Panel
// ---------------------------------------------------------------------------

function ScreeningPanel({ results }: { results: ScreeningResult[] }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
        Screening Results
        <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 font-normal text-gray-500">
          {results.length}
        </span>
      </h3>
      <div className="space-y-2">
        {results.map((r) => (
          <div
            key={r.id}
            className="flex items-start justify-between gap-4 rounded border border-red-100 bg-red-50 p-3"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <span className="text-xs font-semibold text-red-700">
                  {r.entity_name}
                </span>
                <span className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-600 ring-1 ring-red-200">
                  {r.match_data?.list_name ?? "Unknown list"}
                </span>
              </div>
              {r.match_data?.snippet && (
                <p className="text-xs text-red-600/70 leading-relaxed">
                  {r.match_data.snippet}
                </p>
              )}
              {r.source_url && (
                <a
                  href={r.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 inline-block text-[10px] text-red-400 hover:underline"
                >
                  View source ↗
                </a>
              )}
            </div>
            <div className="shrink-0 text-right">
              <span
                className={[
                  "rounded px-2 py-0.5 text-xs font-semibold",
                  r.match_confidence >= 0.85
                    ? "bg-red-100 text-red-700 ring-1 ring-red-300"
                    : "bg-orange-100 text-orange-700 ring-1 ring-orange-200",
                ].join(" ")}
              >
                {(r.match_confidence * 100).toFixed(0)}% match
              </span>
              <p
                className={[
                  "mt-1 text-[10px]",
                  r.status === "pending"
                    ? "text-gray-400"
                    : r.status === "reviewed"
                      ? "text-green-600"
                      : "text-gray-300",
                ].join(" ")}
              >
                {r.status}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
