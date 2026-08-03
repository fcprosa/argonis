"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import {
  getCase,
  getCaseMetadata,
  runInvestigation,
  exportNarrativePdf,
  isDemoReadOnly,
  ApiError,
} from "@/lib/api";
import type {
  CaseDetail,
  CaseMetadata,
  EvidenceLink,
  InvestigationStep,
  ScreeningResult,
} from "@/lib/types";
import { EvidencePanel } from "@/components/EvidencePanel";
import {
  SAMPLE_CASE_DETAIL,
  parseCustomerName,
  statusMeta,
  fmtDate,
} from "@/lib/sample-data";
import { NarrativeViewer } from "@/components/NarrativeViewer";
import {
  detectDemoKey,
  displayAlertRef,
  displayCaseTitle,
  groupScreeningResults,
  publicSourceAttribution,
  sanitizeDisplayText,
  type DemoTypologyKey,
} from "@/lib/demo-display";
import { trackCaseOpen, trackEvidClick, trackPdfExport } from "@/lib/track";

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
  const [caseMetadata, setCaseMetadata] = useState<CaseMetadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [demoMode, setDemoMode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isDemoAllowed = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

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
      try {
        const meta = await getCaseMetadata(id);
        setCaseMetadata(meta);
      } catch {
        setCaseMetadata(null);
      }
      return data;
    } catch (err) {
      if (isDemoAllowed) {
        const sample = SAMPLE_CASE_DETAIL[id];
        if (sample) {
          setDetail(sample);
          setDemoMode(true);
          setCaseMetadata(null);
          return sample;
        }
      }
      const msg =
        err instanceof ApiError
          ? `${err.httpStatus}: ${err.message}`
          : "Unable to reach investigation API. Check your connection or contact support.";
      setError(msg);
      return null;
    }
  }, [id, isDemoAllowed]);

  useEffect(() => {
    setLoading(true);
    loadCase()
      .then((data) => {
        if (data) trackCaseOpen(id);
      })
      .finally(() => setLoading(false));
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [loadCase, id]);

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
      setExportError("Offline sample — PDF export requires live API");
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
      trackPdfExport();
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
  const analyzeSrc = (analyzeStep?.source_data ?? {}) as Record<string, unknown>;
  const recommendedAction = String(
    analyzeSrc.recommended_action ?? "investigate",
  );
  const completedStepKeys = new Set<string>(
    detail?.investigation_steps.map((s) => s.name) ?? [],
  );
  if ((detail?.narratives.length ?? 0) > 0) completedStepKeys.add("narrate");

  const narrative = detail?.narratives[0] ?? null;
  const caseStatus = detail?.case.status ?? "open";
  const { label: statusLabel, classes: statusClasses } = statusMeta(caseStatus);
  const demoReadOnly = isDemoReadOnly(demoMode);
  const evidenceLinks = detail?.evidence_links ?? [];

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <p className="text-sm text-gray-400 animate-pulse">Loading case…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 px-4 py-16">
        <p className="text-sm text-red-600">{error}</p>
        <Link
          href="/sandbox"
          className="text-xs text-blue-600 hover:underline lg:hidden"
        >
          Back to sandbox
        </Link>
        <Link
          href="/dashboard"
          className="hidden text-xs text-blue-600 hover:underline lg:inline"
        >
          Back to queue
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden max-lg:min-h-screen max-lg:overflow-visible">
      {/* Page header */}
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-gray-200 bg-white px-4 sm:px-6">
        <Link
          href="/sandbox"
          className="text-xs text-gray-400 hover:text-gray-600 transition-colors lg:hidden"
        >
          Sandbox
        </Link>
        <Link
          href="/dashboard"
          className="hidden text-xs text-gray-400 hover:text-gray-600 transition-colors lg:inline"
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
      <div className="flex-1 overflow-y-auto px-4 py-5 space-y-5 sm:px-6 max-lg:overflow-visible">
        {/* Mobile-only notice */}
        <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 lg:hidden">
          Interactive evidence panel available on desktop.
        </p>

        <p className="text-[11px] text-text-muted">
          <span className="font-mono text-text-faint">{id.slice(-8).toUpperCase()}</span>
          {detail?.case.created_at && (
            <span className="ml-3">Created {fmtDate(detail.case.created_at)}</span>
          )}
          <span className={`ml-2 rounded px-1.5 py-0.5 text-[10px] ${statusClasses}`}>
            {statusLabel}
          </span>
        </p>

        {/* Pipeline progress */}
        <PipelinePanel
          completedSteps={completedStepKeys}
          steps={detail?.investigation_steps ?? []}
          investigating={investigating}
          pollError={pollError}
          canRun={
            !demoMode &&
            !demoReadOnly &&
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

        {/* Narrative actions — Export PDF visible on all viewports */}
        {narrative && (
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-gray-400">
              Narrative · v{narrative.version}
            </p>
            <div className="flex items-center gap-2">
              {exportError && (
                <span className="text-xs text-red-500">{exportError}</span>
              )}
              <button
                onClick={handleExportPdf}
                disabled={exportingPdf || demoMode}
                className="rounded border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {exportingPdf ? "Generating…" : "Export PDF"}
              </button>
            </div>
          </div>
        )}

        {/* Narrative + evidence */}
        {narrative && (
          <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
            {/* Desktop ≥lg side panel — unchanged */}
            <aside className="hidden w-96 shrink-0 lg:sticky lg:top-4 lg:order-2 lg:block">
              <EvidencePanel links={evidenceLinks} />
            </aside>
            <div className="min-w-0 flex-1 max-w-4xl space-y-5 lg:order-1">
              <CaseDemoHeader
                caseTitle={detail?.case.title ?? ""}
                sourceMetadata={detail?.case.source_metadata}
                narrativeTitle={narrative.title}
                riskScore={riskScore}
                recommendedAction={recommendedAction}
                detectors={detectorBadges(analyzeSrc)}
              />
              <NarrativeViewer
                narrative={narrative}
                evidenceLinks={evidenceLinks}
                overallConfidence={riskScore}
                demoMode={demoMode}
                demoReadOnly={demoReadOnly}
                caseMetadata={caseMetadata}
                onSectionApproved={async () => {
                  const fresh = await loadCase();
                  if (fresh) setDetail(fresh);
                }}
              />
              {/* Mobile <lg — expandable evidence list */}
              <MobileEvidenceList links={evidenceLinks} />
            </div>
          </div>
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
              {caseStatus === "open" && !demoReadOnly && (
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

function MobileEvidenceList({ links }: { links: EvidenceLink[] }) {
  if (links.length === 0) {
    return (
      <div className="rounded border border-gray-200 bg-white p-4 text-xs text-gray-400 lg:hidden">
        No evidence links for this narrative.
      </div>
    );
  }

  return (
    <section className="space-y-2 lg:hidden">
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">
        Evidence ({links.length})
      </h3>
      <ul className="space-y-2">
        {links.map((el) => {
          const sd = el.source_data ?? {};
          const cat = String(sd.category ?? "unknown").toUpperCase();
          const desc = String(sd.description ?? "");
          const val = String(sd.value ?? "");
          const fact =
            `${desc}: ${val}`.trim().slice(0, 400) ||
            el.sentence_text ||
            el.evidence_ref;
          return (
            <li key={el.id}>
              <details
                className="rounded border border-gray-200 bg-white"
                onToggle={(e) => {
                  if ((e.target as HTMLDetailsElement).open) {
                    trackEvidClick();
                  }
                }}
              >
                <summary className="cursor-pointer list-none px-3 py-2.5 [&::-webkit-details-marker]:hidden">
                  <span className="font-mono text-[11px] font-semibold text-cyan-700">
                    {el.evidence_ref}
                  </span>
                  <span className="ml-2 text-[10px] uppercase tracking-wide text-gray-400">
                    {cat}
                  </span>
                </summary>
                <p className="border-t border-gray-100 px-3 py-2.5 text-xs leading-relaxed text-gray-700">
                  {fact}
                </p>
              </details>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function detectorBadges(src: Record<string, unknown>): string[] {
  const keys = [
    "structuring",
    "layering",
    "funnel",
    "velocity",
    "geographic_risk",
  ] as const;
  const out: string[] = [];
  for (const k of keys) {
    const v = src[k] as { detected?: boolean } | undefined;
    if (v && typeof v === "object" && v.detected === true) out.push(k);
  }
  return out;
}

function CaseDemoHeader({
  caseTitle,
  sourceMetadata,
  narrativeTitle,
  riskScore,
  recommendedAction,
  detectors,
}: {
  caseTitle: string;
  sourceMetadata?: CaseDetail["case"]["source_metadata"];
  narrativeTitle: string;
  riskScore: number | null;
  recommendedAction: string;
  detectors: string[];
}) {
  const demoKey = detectDemoKey(caseTitle, sourceMetadata ?? null);
  const customer = parseCustomerName(caseTitle);
  const displayTitle = demoKey
    ? displayCaseTitle(demoKey, customer)
    : sanitizeDisplayText(narrativeTitle || caseTitle);
  const alertRef = demoKey ? displayAlertRef(demoKey) : null;
  const attribution = demoKey ? publicSourceAttribution(demoKey) : null;

  const pct = riskScore != null ? Math.round(riskScore * 100) : null;
  const ring =
    pct == null
      ? "border-neutral-600 text-neutral-400"
      : pct >= 70
        ? "border-red-500 text-red-300"
        : pct >= 50
          ? "border-orange-500 text-orange-200"
          : pct >= 30
            ? "border-yellow-500 text-yellow-200"
            : "border-emerald-600 text-emerald-200";
  const pill =
    pct == null
      ? "bg-neutral-800 text-neutral-400"
      : pct >= 70
        ? "bg-red-500/15 text-red-200 ring-1 ring-red-500/40"
        : pct >= 50
          ? "bg-orange-500/15 text-orange-200 ring-1 ring-orange-500/40"
          : pct >= 30
            ? "bg-yellow-500/15 text-yellow-200 ring-1 ring-yellow-500/40"
            : "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-500/40";

  return (
    <div className="rounded border border-border bg-surface-1 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
            Case narrative
          </p>
          {alertRef && (
            <p className="mt-1 font-mono text-[11px] text-text-muted">
              {alertRef}
            </p>
          )}
          <h2 className="mt-1 text-sm font-semibold text-white">{displayTitle}</h2>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {pct != null && (
            <div
              className={[
                "flex h-14 w-14 shrink-0 items-center justify-center rounded-full border-2 text-xs font-bold",
                ring,
              ].join(" ")}
              title="Risk score"
            >
              {pct}%
            </div>
          )}
          <span
            className={[
              "rounded px-2 py-1 text-[11px] font-semibold capitalize",
              pill,
            ].join(" ")}
          >
            {recommendedAction.replace("_", " ")}
          </span>
        </div>
      </div>
      {detectors.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {detectors.map((d) => (
            <span
              key={d}
              className="rounded bg-surface-2 px-2 py-0.5 font-mono text-[10px] text-text-muted"
            >
              {d}
            </span>
          ))}
        </div>
      )}
      {demoKey && attribution && <PublicSourceBlock demoKey={demoKey} />}
    </div>
  );
}

function PublicSourceBlock({ demoKey }: { demoKey: DemoTypologyKey }) {
  const { label, url } = publicSourceAttribution(demoKey);
  return (
    <div className="mt-4 border-t border-border pt-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
        Public source
      </p>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-1 block break-words text-xs text-accent-DEFAULT underline-offset-2 hover:underline"
      >
        {label}
      </a>
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
  const { exact, keywordGroups } = groupScreeningResults(results);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
        Screening Results
        <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 font-normal text-gray-500">
          {results.length}
        </span>
      </h3>

      {exact.length > 0 && (
        <div className="mb-3 space-y-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-red-600">
            Exact matches
          </p>
          {exact.map((r) => (
            <ScreeningHitRow key={r.id} result={r} highlighted />
          ))}
        </div>
      )}

      {keywordGroups.length > 0 && (
        <div className="space-y-2">
          {exact.length > 0 && (
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">
              Keyword-level media
            </p>
          )}
          {keywordGroups.map((group) => (
            <details
              key={group.entity}
              className="rounded border border-gray-200 bg-gray-50"
            >
              <summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-gray-700 [&::-webkit-details-marker]:hidden">
                {group.entity} — {group.count} keyword-level media hit
                {group.count === 1 ? "" : "s"}
              </summary>
              <div className="space-y-2 border-t border-gray-200 px-3 py-2">
                {group.hits.map((r) => (
                  <ScreeningHitRow key={r.id} result={r} />
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

function ScreeningHitRow({
  result: r,
  highlighted = false,
}: {
  result: ScreeningResult;
  highlighted?: boolean;
}) {
  return (
    <div
      className={[
        "flex items-start justify-between gap-4 rounded border p-3",
        highlighted
          ? "border-red-300 bg-red-50 ring-1 ring-red-200"
          : "border-red-100 bg-red-50/60",
      ].join(" ")}
    >
      <div className="min-w-0">
        <div className="mb-0.5 flex items-center gap-2">
          <span className="text-xs font-semibold text-red-700">
            {r.entity_name}
          </span>
          <span className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-600 ring-1 ring-red-200">
            {r.match_data?.list_name ?? "Unknown list"}
          </span>
          {highlighted && (
            <span className="rounded bg-red-600 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white">
              Exact
            </span>
          )}
        </div>
        {r.match_data?.snippet && (
          <p className="text-xs leading-relaxed text-red-600/70">
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
  );
}
