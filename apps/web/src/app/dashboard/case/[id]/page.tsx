"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Link from "next/link";
import { jsPDF } from "jspdf";
import {
  SAMPLE_CASE_DETAIL,
  DEMO_AUDIT_TRAILS,
  DEMO_FULL_SCREENING,
  DEMO_PIPELINES,
  riskLabel,
  riskColors,
  statusMeta,
  fmtDate,
  parseAlertType,
  parseCustomerName,
} from "@/lib/sample-data";
import type { NarrativeSection, EvidenceLink, CaseDetail } from "@/lib/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Tab = "overview" | "investigation" | "narrative" | "screening" | "audit";
type StepState = "pending" | "running" | "done";

interface PipelineStepRuntime {
  key: string;
  label: string;
  detail: string;
  state: StepState;
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function CaseDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const { id } = params;
  const isDemoAllowed = process.env.NEXT_PUBLIC_DEMO_MODE === "true";
  const detail: CaseDetail | undefined = isDemoAllowed ? SAMPLE_CASE_DETAIL[id] : undefined;

  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [pipelineSteps, setPipelineSteps] = useState<PipelineStepRuntime[]>(
    () =>
      (DEMO_PIPELINES[id] ?? []).map((s) => ({
        key: s.key,
        label: s.label,
        detail: s.detail,
        state: "pending" as StepState,
      })),
  );
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineDone, setPipelineDone] = useState(() => {
    const d = SAMPLE_CASE_DETAIL[id];
    return (d?.narratives.length ?? 0) > 0;
  });

  const [activeEvidenceRef, setActiveEvidenceRef] = useState<string | null>(null);
  const [narrativeSections, setNarrativeSections] = useState<NarrativeSection[]>(
    () => [...(SAMPLE_CASE_DETAIL[id]?.narratives[0]?.narrative_sections ?? [])].sort((a, b) => a.order_index - b.order_index),
  );
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [exportingPdf, setExportingPdf] = useState(false);

  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    return () => timersRef.current.forEach(clearTimeout);
  }, []);

  // Pre-fill pipeline as done if narrative already exists on mount
  useEffect(() => {
    if (pipelineDone) {
      const defs = DEMO_PIPELINES[id] ?? [];
      setPipelineSteps(defs.map((s) => ({ key: s.key, label: s.label, detail: s.detail, state: "done" })));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------------------
  // Pipeline animation
  // ---------------------------------------------------------------------------

  function runDemoPipeline() {
    if (pipelineRunning || pipelineDone) return;
    const defs = DEMO_PIPELINES[id] ?? [];
    if (defs.length === 0) return;

    setPipelineRunning(true);
    setActiveTab("investigation");

    // Reset all to pending
    setPipelineSteps(defs.map((s) => ({ key: s.key, label: s.label, detail: s.detail, state: "pending" })));

    let elapsed = 0;
    defs.forEach((step, i) => {
      // Set running
      const runT = setTimeout(() => {
        setPipelineSteps((prev) =>
          prev.map((s, idx) => (idx === i ? { ...s, state: "running" } : s)),
        );
      }, elapsed);
      timersRef.current.push(runT);

      elapsed += step.durationMs;

      // Set done
      const doneT = setTimeout(() => {
        setPipelineSteps((prev) =>
          prev.map((s, idx) => (idx === i ? { ...s, state: "done" } : s)),
        );
        if (i === defs.length - 1) {
          setPipelineRunning(false);
          setPipelineDone(true);
          setActiveTab("narrative");
        }
      }, elapsed);
      timersRef.current.push(doneT);
    });
  }

  // ---------------------------------------------------------------------------
  // Evidence popover
  // ---------------------------------------------------------------------------

  const evidenceLinks = detail?.evidence_links ?? [];
  const evidenceMap = new Map<string, EvidenceLink>();
  evidenceLinks.forEach((el) => evidenceMap.set(el.evidence_ref, el));

  const activeEvidence = activeEvidenceRef ? evidenceMap.get(activeEvidenceRef) : null;

  // ---------------------------------------------------------------------------
  // Narrative section actions
  // ---------------------------------------------------------------------------

  function approveSection(key: string, action: "approve" | "reject") {
    setNarrativeSections((prev) =>
      prev.map((s) =>
        s.section_key === key
          ? {
              ...s,
              approval_status: action === "approve" ? "approved" : "rejected",
              approved_by: "analyst@argonis.ai",
              approved_at: new Date().toISOString(),
            }
          : s,
      ),
    );
  }

  function saveEdit(key: string) {
    setNarrativeSections((prev) =>
      prev.map((s) =>
        s.section_key === key ? { ...s, content: editDraft, approval_status: "pending" } : s,
      ),
    );
    setEditingKey(null);
  }

  // ---------------------------------------------------------------------------
  // PDF export
  // ---------------------------------------------------------------------------

  function exportPdf() {
    if (!detail) return;
    setExportingPdf(true);

    try {
      const doc = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });
      const W = 210;
      const MARGIN = 18;
      const CONTENT_W = W - MARGIN * 2;
      let y = MARGIN;

      const accent = [232, 255, 77] as [number, number, number];
      const dark   = [17, 17, 17]   as [number, number, number];

      function checkPage(needed = 10) {
        if (y + needed > 270) {
          doc.addPage();
          y = MARGIN;
        }
      }

      function hr(color: [number, number, number] = [220, 220, 220]) {
        doc.setDrawColor(...color);
        doc.setLineWidth(0.2);
        doc.line(MARGIN, y, W - MARGIN, y);
        y += 4;
      }

      function heading(text: string, size = 9) {
        checkPage(10);
        doc.setFontSize(size);
        doc.setTextColor(80, 80, 80);
        doc.setFont("helvetica", "bold");
        doc.text(text.toUpperCase(), MARGIN, y);
        y += 5;
        hr();
      }

      function body(text: string, size = 9, color: [number, number, number] = [50, 50, 50]) {
        checkPage(6);
        doc.setFontSize(size);
        doc.setTextColor(...color);
        doc.setFont("helvetica", "normal");
        const lines = doc.splitTextToSize(text, CONTENT_W) as string[];
        lines.forEach((line: string) => {
          checkPage(5);
          doc.text(line, MARGIN, y);
          y += 4.5;
        });
        y += 1;
      }

      // ── Letterhead ────────────────────────────────────────────────────────
      doc.setFillColor(...dark);
      doc.rect(0, 0, W, 28, "F");

      doc.setFontSize(14);
      doc.setTextColor(255, 255, 255);
      doc.setFont("helvetica", "bold");
      doc.text("ARGONIS", MARGIN, 13);

      doc.setFontSize(7);
      doc.setTextColor(150, 150, 150);
      doc.setFont("helvetica", "normal");
      doc.text("AML Investigation Platform · Evidence-First Architecture", MARGIN, 19);

      doc.setFontSize(7);
      doc.setTextColor(...accent);
      doc.text("CONFIDENTIAL — FOR COMPLIANCE USE ONLY", W - MARGIN, 13, { align: "right" });

      y = 36;
      hr([200, 200, 200]);

      // ── Case metadata ─────────────────────────────────────────────────────
      const caseTitle = detail.case.title;
      const customerName = parseCustomerName(caseTitle);
      const alertType = parseAlertType(caseTitle);
      const narrative = detail.narratives[0];

      doc.setFontSize(13);
      doc.setTextColor(...dark);
      doc.setFont("helvetica", "bold");
      doc.text(customerName, MARGIN, y);
      y += 6;

      doc.setFontSize(9);
      doc.setTextColor(100, 100, 100);
      doc.setFont("helvetica", "normal");
      doc.text(`${alertType}  ·  Case ${id.slice(-8).toUpperCase()}  ·  Generated ${new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}`, MARGIN, y);
      y += 9;
      hr();

      // ── Narrative sections ────────────────────────────────────────────────
      if (narrative) {
        heading("SAR Narrative — " + narrative.title.split("—")[0]?.trim());
        narrativeSections.forEach((section) => {
          checkPage(12);
          doc.setFontSize(9);
          doc.setFont("helvetica", "bold");
          doc.setTextColor(30, 30, 30);
          doc.text(section.title.toUpperCase(), MARGIN, y);

          const statusColor: [number, number, number] =
            section.approval_status === "approved"
              ? [34, 197, 94]
              : section.approval_status === "rejected"
                ? [239, 68, 68]
                : [156, 163, 175];
          doc.setTextColor(...statusColor);
          doc.setFontSize(7);
          doc.text(
            section.approval_status.toUpperCase(),
            W - MARGIN,
            y,
            { align: "right" },
          );
          y += 5;

          // Strip EVID refs for clean PDF text
          const cleanContent = section.content.replace(/\[EVID-\d+\]/g, "").replace(/\s+/g, " ").trim();
          body(cleanContent, 8.5, [60, 60, 60]);
          y += 2;
        });
      }

      // ── Screening results ─────────────────────────────────────────────────
      const screening = DEMO_FULL_SCREENING[id] ?? [];
      if (screening.length > 0) {
        checkPage(20);
        heading("Screening Results");
        screening.forEach((r) => {
          checkPage(8);
          const statusLabel =
            r.status === "hit" ? "HIT" : r.status === "potential_match" ? "PARTIAL" : "CLEAR";
          const statusColor: [number, number, number] =
            r.status === "hit" ? [239, 68, 68] : r.status === "potential_match" ? [234, 88, 12] : [34, 197, 94];

          doc.setFont("helvetica", "bold");
          doc.setFontSize(8);
          doc.setTextColor(30, 30, 30);
          doc.text(`${r.list_name}  ·  ${r.entity_name}`, MARGIN, y);

          doc.setTextColor(...statusColor);
          doc.text(
            `${statusLabel}${r.match_confidence > 0 ? `  ${(r.match_confidence * 100).toFixed(0)}%` : ""}`,
            W - MARGIN,
            y,
            { align: "right" },
          );
          y += 4;

          body(r.snippet, 7.5, [100, 100, 100]);
        });
      }

      // ── Audit trail ───────────────────────────────────────────────────────
      const audit = DEMO_AUDIT_TRAILS[id] ?? [];
      if (audit.length > 0) {
        checkPage(20);
        heading("Audit Trail");
        audit.forEach((entry) => {
          checkPage(8);
          doc.setFont("helvetica", "bold");
          doc.setFontSize(7.5);
          doc.setTextColor(30, 30, 30);
          doc.text(entry.action, MARGIN, y);
          doc.setFont("helvetica", "normal");
          doc.setTextColor(120, 120, 120);
          doc.text(
            `${new Date(entry.timestamp).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}  ·  ${entry.actor}`,
            W - MARGIN,
            y,
            { align: "right" },
          );
          y += 4;
          body(entry.detail, 7.5, [100, 100, 100]);
        });
      }

      // ── Page numbers ──────────────────────────────────────────────────────
      const pageCount = doc.getNumberOfPages();
      for (let i = 1; i <= pageCount; i++) {
        doc.setPage(i);
        doc.setFontSize(7);
        doc.setTextColor(180, 180, 180);
        doc.text(`Page ${i} of ${pageCount}  ·  Argonis Confidential`, W / 2, 290, { align: "center" });
      }

      doc.save(`argonis-${id.slice(-8).toUpperCase()}-${Date.now()}.pdf`);
    } finally {
      setExportingPdf(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Not found
  // ---------------------------------------------------------------------------

  if (!detail) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        {isDemoAllowed ? (
          <p className="text-sm text-gray-500">Case not found: {id}</p>
        ) : (
          <>
            <p className="text-sm font-medium text-red-700">Unable to reach investigation API.</p>
            <p className="text-xs text-gray-500">Check your connection or contact support.</p>
          </>
        )}
        <Link href="/dashboard" className="text-xs text-blue-600 hover:underline">
          ← Back to queue
        </Link>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Derived values
  // ---------------------------------------------------------------------------

  const analyzeStep = detail.investigation_steps.find((s) => s.name === "analyze");
  const riskScore = (analyzeStep?.confidence_score as number | null | undefined) ?? null;
  const caseTitle = detail.case.title;
  const caseStatus = detail.case.status;
  const { label: statusLabel, classes: statusClasses } = statusMeta(caseStatus);
  const narrative = detail.narratives[0] ?? null;
  const approved = narrativeSections.filter((s) => s.approval_status === "approved").length;

  const TABS: { key: Tab; label: string; count: number | null }[] = [
    { key: "overview",      label: "Overview",       count: null },
    { key: "investigation", label: "Investigation",  count: null },
    { key: "narrative",     label: "Narrative",      count: narrative ? narrativeSections.length : null },
    { key: "screening",     label: "Screening",      count: (DEMO_FULL_SCREENING[id] ?? []).length },
    { key: "audit",         label: "Audit Trail",    count: (DEMO_AUDIT_TRAILS[id] ?? []).length },
  ];

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Demo data banner — persistent, not dismissible */}
      {isDemoAllowed && (
        <div className="shrink-0 bg-red-900 px-6 py-2.5 border-b border-red-800">
          <p className="text-sm font-semibold text-white">
            ⚠ DEMO DATA — NOT REAL PIPELINE OUTPUT. API unreachable or demo mode enabled.
          </p>
        </div>
      )}

      {/* Evidence popover modal */}
      {activeEvidenceRef && (
        <EvidenceModal
          evidenceRef={activeEvidenceRef}
          evidence={activeEvidence ?? null}
          onClose={() => setActiveEvidenceRef(null)}
        />
      )}

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="shrink-0 border-b border-gray-200 bg-white px-6 py-3">
        <div className="flex items-center gap-2 text-xs text-gray-400 mb-2">
          <Link href="/dashboard" className="hover:text-gray-600 transition-colors">
            Alert Queue
          </Link>
          <span>›</span>
          <span className="font-mono text-gray-500">{id.slice(-8).toUpperCase()}</span>
          <span className="rounded bg-yellow-100 px-2 py-0.5 text-[10px] font-medium text-yellow-700 ring-1 ring-yellow-300">
            DEMO
          </span>
        </div>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-0.5">
              {parseAlertType(caseTitle)}
            </p>
            <h2 className="text-base font-semibold text-gray-900 leading-tight">
              {parseCustomerName(caseTitle)}
            </h2>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {riskScore != null && (
              <span className={["rounded px-2.5 py-1 text-xs font-bold", riskColors(riskScore)].join(" ")}>
                {riskLabel(riskScore)} · {(riskScore * 100).toFixed(0)}%
              </span>
            )}
            <span className={["rounded px-2.5 py-1 text-xs font-medium", statusClasses].join(" ")}>
              {statusLabel}
            </span>
            <button
              onClick={runDemoPipeline}
              disabled={pipelineRunning || pipelineDone}
              className="rounded bg-[#111] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#333] transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              {pipelineRunning ? "Running…" : pipelineDone ? "Investigation Complete" : "Run Investigation"}
            </button>
            <button
              onClick={exportPdf}
              disabled={exportingPdf || !pipelineDone}
              className="rounded border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              title={!pipelineDone ? "Run investigation first" : "Export PDF"}
            >
              {exportingPdf ? "Generating…" : "Export PDF"}
            </button>
          </div>
        </div>
      </header>

      {/* ── Tabs ───────────────────────────────────────────────────────── */}
      <div className="shrink-0 flex items-center gap-0 border-b border-gray-200 bg-white px-6">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={[
              "flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-xs font-medium transition-colors",
              activeTab === tab.key
                ? "border-gray-900 text-gray-900"
                : "border-transparent text-gray-400 hover:text-gray-600",
            ].join(" ")}
          >
            {tab.label}
            {tab.count !== null && (
              <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold text-gray-500">
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Tab content ────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-5">

        {/* Overview */}
        {activeTab === "overview" && (
          <OverviewTab detail={detail} riskScore={riskScore} />
        )}

        {/* Investigation */}
        {activeTab === "investigation" && (
          <InvestigationTab
            steps={pipelineSteps}
            running={pipelineRunning}
            done={pipelineDone}
            onRun={runDemoPipeline}
          />
        )}

        {/* Narrative */}
        {activeTab === "narrative" && (
          <NarrativeTabContent
            narrative={narrative}
            sections={narrativeSections}
            evidenceMap={evidenceMap}
            approved={approved}
            editingKey={editingKey}
            editDraft={editDraft}
            pipelineDone={pipelineDone}
            onApprove={approveSection}
            onStartEdit={(key, content) => { setEditingKey(key); setEditDraft(content); }}
            onSaveEdit={saveEdit}
            onCancelEdit={() => setEditingKey(null)}
            onEditDraftChange={setEditDraft}
            onEvidenceClick={setActiveEvidenceRef}
            onRunPipeline={runDemoPipeline}
          />
        )}

        {/* Screening */}
        {activeTab === "screening" && (
          <ScreeningTab results={DEMO_FULL_SCREENING[id] ?? []} />
        )}

        {/* Audit Trail */}
        {activeTab === "audit" && (
          <AuditTrailTab entries={DEMO_AUDIT_TRAILS[id] ?? []} />
        )}
      </div>
    </div>
  );
}

// ===========================================================================
// Overview Tab
// ===========================================================================

function OverviewTab({
  detail,
  riskScore,
}: {
  detail: CaseDetail;
  riskScore: number | null;
}) {
  const caseTitle = detail.case.title;
  const step = detail.investigation_steps.find((s) => s.name === "parse");
  const gatherStep = detail.investigation_steps.find((s) => s.name === "gather");
  const analyzeStep = detail.investigation_steps.find((s) => s.name === "analyze");
  const src = step?.source_data as Record<string, unknown> | null;
  const gSrc = gatherStep?.source_data as Record<string, unknown> | null;
  const aSrc = analyzeStep?.source_data as Record<string, unknown> | null;

  const facts: { label: string; value: string }[] = [];
  if (src?.account_holder) facts.push({ label: "Subject",       value: String(src.account_holder) });
  if (src?.alert_type)     facts.push({ label: "Alert type",    value: String(src.alert_type) });
  if (src?.account_number) facts.push({ label: "Account",       value: String(src.account_number) });
  if (src?.currency)       facts.push({ label: "Currency",      value: String(src.currency) });
  if (src?.nationality)    facts.push({ label: "Nationality",   value: String(src.nationality) });
  if (gSrc?.account_history_days || gSrc?.transaction_history_days)
                           facts.push({ label: "History loaded", value: `${gSrc?.account_history_days ?? gSrc?.transaction_history_days} days` });
  if (aSrc?.recommended_action)
                           facts.push({ label: "Recommendation", value: String(aSrc.recommended_action).replace(/_/g, " ") });

  const patterns = (aSrc?.patterns_detected as string[] | undefined) ?? [];

  return (
    <div className="space-y-4 max-w-3xl">
      {/* Case info */}
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-4">Case Information</p>
        <div className="grid grid-cols-2 gap-x-8 gap-y-3">
          {facts.map((f) => (
            <div key={f.label}>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">{f.label}</p>
              <p className="text-sm text-gray-900 font-medium mt-0.5">{f.value}</p>
            </div>
          ))}
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Case ID</p>
            <p className="text-sm font-mono text-gray-900 mt-0.5">{detail.case.id.slice(-8).toUpperCase()}</p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Created</p>
            <p className="text-sm text-gray-900 mt-0.5">{fmtDate(detail.case.created_at)}</p>
          </div>
        </div>
        {detail.case.description && (
          <p className="mt-4 text-xs text-gray-500 border-t border-gray-100 pt-4 leading-relaxed">
            {detail.case.description}
          </p>
        )}
      </div>

      {/* Risk & patterns */}
      {(riskScore != null || patterns.length > 0) && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-4">Risk Assessment</p>
          <div className="flex flex-wrap items-start gap-6">
            {riskScore != null && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1">Risk Score</p>
                <span className={["rounded px-3 py-1 text-sm font-bold", riskColors(riskScore)].join(" ")}>
                  {riskLabel(riskScore)} · {(riskScore * 100).toFixed(0)}%
                </span>
              </div>
            )}
            {patterns.length > 0 && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-2">Patterns detected</p>
                <div className="flex flex-wrap gap-1.5">
                  {patterns.map((p) => (
                    <span key={p} className="rounded bg-orange-50 px-2.5 py-1 text-xs font-semibold text-orange-700 ring-1 ring-orange-200">
                      {p.replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Timeline */}
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-4">Timeline</p>
        <div className="space-y-0">
          {detail.investigation_steps.map((step, i) => (
            <div key={step.id} className="flex gap-4">
              <div className="flex flex-col items-center">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-green-500 text-[9px] font-bold text-white shrink-0">✓</div>
                {i < detail.investigation_steps.length - 1 && (
                  <div className="w-px flex-1 bg-green-200 my-0.5" style={{ minHeight: "16px" }} />
                )}
              </div>
              <div className="pb-4 min-w-0">
                <p className="text-xs font-semibold text-gray-900">{step.description}</p>
                <p className="text-[10px] text-gray-400 mt-0.5">{fmtDate(step.created_at)}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// Investigation Tab
// ===========================================================================

function InvestigationTab({
  steps,
  running,
  done,
  onRun,
}: {
  steps: { key: string; label: string; detail: string; state: StepState }[];
  running: boolean;
  done: boolean;
  onRun: () => void;
}) {
  return (
    <div className="max-w-3xl space-y-4">
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500">Investigation Pipeline</h3>
            <p className="text-[10px] text-gray-400 mt-0.5">5-step evidence-first pipeline. Steps 1–4 deterministic. Step 5 LLM from verified evidence only.</p>
          </div>
          {!done && !running && (
            <button
              onClick={onRun}
              className="rounded bg-[#111] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#333] transition-colors"
            >
              Run Investigation
            </button>
          )}
          {running && (
            <span className="flex items-center gap-1.5 text-xs text-blue-600">
              <span className="inline-block h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
              Running…
            </span>
          )}
          {done && !running && (
            <span className="flex items-center gap-1.5 text-xs text-green-600 font-semibold">
              <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
              Complete
            </span>
          )}
        </div>

        {/* Step list */}
        <div className="space-y-2">
          {steps.map((step, i) => (
            <div
              key={step.key}
              className={[
                "flex items-start gap-4 rounded-lg border p-4 transition-all",
                step.state === "done"
                  ? "border-green-200 bg-green-50/40"
                  : step.state === "running"
                    ? "border-blue-200 bg-blue-50/40"
                    : "border-gray-100 bg-white",
              ].join(" ")}
            >
              <div
                className={[
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold",
                  step.state === "done"
                    ? "bg-green-500 text-white"
                    : step.state === "running"
                      ? "bg-blue-500 text-white animate-pulse"
                      : "bg-gray-100 text-gray-400",
                ].join(" ")}
              >
                {step.state === "done" ? "✓" : i + 1}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-0.5">
                  <p
                    className={[
                      "text-xs font-bold tracking-wider",
                      step.state === "done"
                        ? "text-green-700"
                        : step.state === "running"
                          ? "text-blue-600"
                          : "text-gray-300",
                    ].join(" ")}
                  >
                    {step.label}
                  </p>
                  {step.state === "running" && (
                    <span className="text-[10px] text-blue-500 animate-pulse">processing…</span>
                  )}
                </div>
                <p
                  className={[
                    "text-xs leading-relaxed",
                    step.state === "done"
                      ? "text-green-700/80"
                      : step.state === "running"
                        ? "text-blue-600/80"
                        : "text-gray-300",
                  ].join(" ")}
                >
                  {step.state !== "pending" ? step.detail : "Waiting…"}
                </p>
              </div>
            </div>
          ))}
        </div>

        {done && (
          <div className="mt-4 rounded border border-green-200 bg-green-50 px-4 py-3 text-xs text-green-700">
            ✓ Investigation complete. Navigate to the <strong>Narrative</strong> tab to review and approve sections.
          </div>
        )}
      </div>
    </div>
  );
}

// ===========================================================================
// Narrative Tab
// ===========================================================================

function NarrativeTabContent({
  narrative,
  sections,
  evidenceMap,
  approved,
  editingKey,
  editDraft,
  pipelineDone,
  onApprove,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
  onEditDraftChange,
  onEvidenceClick,
  onRunPipeline,
}: {
  narrative: { id: string; version: number; title: string; status: string } | null;
  sections: NarrativeSection[];
  evidenceMap: Map<string, EvidenceLink>;
  approved: number;
  editingKey: string | null;
  editDraft: string;
  pipelineDone: boolean;
  onApprove: (key: string, action: "approve" | "reject") => void;
  onStartEdit: (key: string, content: string) => void;
  onSaveEdit: (key: string) => void;
  onCancelEdit: () => void;
  onEditDraftChange: (v: string) => void;
  onEvidenceClick: (ref: string) => void;
  onRunPipeline: () => void;
}) {
  if (!pipelineDone || !narrative) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
        <div className="rounded-full bg-gray-100 p-4">
          <span className="text-2xl text-gray-400">▤</span>
        </div>
        <p className="text-sm font-medium text-gray-700">No narrative yet</p>
        <p className="text-xs text-gray-400 max-w-xs">
          Run the investigation pipeline to generate a SAR narrative with inline evidence citations.
        </p>
        <button
          onClick={onRunPipeline}
          className="rounded bg-[#111] px-4 py-2 text-xs font-semibold text-white hover:bg-[#333] transition-colors"
        >
          Run Investigation →
        </button>
      </div>
    );
  }

  const pending  = sections.filter((s) => s.approval_status === "pending").length;
  const rejected = sections.filter((s) => s.approval_status === "rejected").length;

  return (
    <div className="max-w-3xl space-y-3">
      {/* Header */}
      <div className="rounded-lg border border-gray-200 bg-white px-5 py-4">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1">SAR Narrative</p>
            <p className="text-sm font-semibold text-gray-900">{narrative.title}</p>
          </div>
          <span className="text-xs font-medium text-gray-400">v{narrative.version}</span>
        </div>
        <div className="mt-3 flex items-center gap-4 text-xs border-t border-gray-100 pt-3">
          <span className="flex items-center gap-1.5 text-gray-500">
            <span className="inline-block h-2 w-2 rounded-full bg-green-400" />
            {approved} approved
          </span>
          {rejected > 0 && (
            <span className="flex items-center gap-1.5 text-gray-500">
              <span className="inline-block h-2 w-2 rounded-full bg-red-400" />
              {rejected} flagged
            </span>
          )}
          <span className="flex items-center gap-1.5 text-gray-500">
            <span className="inline-block h-2 w-2 rounded-full bg-gray-300" />
            {pending} pending
          </span>
          <span className="ml-auto text-[10px] text-gray-400 bg-blue-50 px-2 py-0.5 rounded">
            Click <span className="font-mono font-semibold text-blue-600">[EVID-XXX]</span> to see source data
          </span>
        </div>
      </div>

      {/* Sections */}
      {sections.map((section) => {
        const isEditing  = editingKey === section.section_key;
        const hasInsuf   = section.content.includes("INSUFFICIENT EVIDENCE");
        const confidence = hasInsuf ? 0 : section.approval_status === "rejected" ? 0.2 : null;

        return (
          <div
            key={section.section_key}
            className={[
              "rounded-lg border bg-white transition-colors",
              section.approval_status === "approved"
                ? "border-green-200"
                : section.approval_status === "rejected"
                  ? "border-red-200"
                  : "border-gray-200",
            ].join(" ")}
          >
            {/* Section header */}
            <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold text-gray-900">{section.title}</h4>
                {hasInsuf && (
                  <span className="rounded bg-red-100 px-2 py-0.5 text-[10px] font-semibold uppercase text-red-600 ring-1 ring-red-200">
                    Needs Input
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {confidence != null && <ConfidencePill confidence={confidence} />}
                <span
                  className={[
                    "text-xs font-semibold",
                    section.approval_status === "approved"
                      ? "text-green-600"
                      : section.approval_status === "rejected"
                        ? "text-red-600"
                        : "text-gray-400",
                  ].join(" ")}
                >
                  {section.approval_status === "approved" ? "Approved" : section.approval_status === "rejected" ? "Flagged" : "Pending"}
                </span>
              </div>
            </div>

            {/* Section body */}
            <div className="px-5 py-4">
              {isEditing ? (
                <div className="space-y-2">
                  <textarea
                    value={editDraft}
                    onChange={(e) => onEditDraftChange(e.target.value)}
                    className="w-full rounded border border-gray-200 bg-amber-50 p-3 text-sm text-gray-800 leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-200 resize-y min-h-[140px]"
                    autoFocus
                  />
                  <p className="text-[10px] text-amber-600 bg-amber-50 px-2 py-1 rounded">
                    Human-edited text — tracked as analyst revision
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => onSaveEdit(section.section_key)}
                      className="rounded bg-[#111] px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-800 transition-colors"
                    >
                      Save
                    </button>
                    <button
                      onClick={onCancelEdit}
                      className="rounded border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <SectionContent
                  content={section.content}
                  onEvidenceClick={onEvidenceClick}
                />
              )}
            </div>

            {/* Section footer */}
            {!isEditing && (
              <div className="flex items-center justify-between border-t border-gray-100 px-5 py-2.5">
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => onApprove(section.section_key, "approve")}
                    disabled={section.approval_status === "approved" || hasInsuf}
                    className={[
                      "rounded px-3 py-1 text-xs font-semibold transition-colors",
                      section.approval_status === "approved"
                        ? "bg-green-100 text-green-700 cursor-default"
                        : hasInsuf
                          ? "bg-gray-50 text-gray-300 cursor-not-allowed"
                          : "bg-green-50 text-green-700 hover:bg-green-100",
                    ].join(" ")}
                  >
                    {section.approval_status === "approved" ? "Approved ✓" : "Approve"}
                  </button>
                  <button
                    onClick={() => onApprove(section.section_key, "reject")}
                    disabled={section.approval_status === "rejected"}
                    className={[
                      "rounded px-3 py-1 text-xs font-semibold transition-colors",
                      section.approval_status === "rejected"
                        ? "bg-red-100 text-red-700 cursor-default"
                        : "bg-gray-50 text-gray-500 hover:bg-red-50 hover:text-red-600",
                    ].join(" ")}
                  >
                    {section.approval_status === "rejected" ? "Flagged" : "Flag"}
                  </button>
                </div>
                <div className="flex items-center gap-3 text-[10px] text-gray-400">
                  <button
                    onClick={() => onStartEdit(section.section_key, section.content)}
                    className="hover:text-gray-700 transition-colors"
                  >
                    Edit
                  </button>
                  {section.approved_at && (
                    <span>
                      {section.approval_status === "approved" ? "Approved" : "Updated"}{" "}
                      {new Date(section.approved_at).toLocaleString("en-GB", {
                        day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
                      })}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section content — renders prose with clickable [EVID-XXX] badges
// ---------------------------------------------------------------------------

function SectionContent({
  content,
  onEvidenceClick,
}: {
  content: string;
  onEvidenceClick: (ref: string) => void;
}) {
  const SPLIT_RE = /(\[EVID-\d+\]|INSUFFICIENT EVIDENCE)/g;
  const parts = content.split(SPLIT_RE);

  return (
    <p className="text-sm text-gray-700 leading-relaxed">
      {parts.map((part, i) => {
        if (part === "INSUFFICIENT EVIDENCE") {
          return (
            <mark key={i} className="rounded bg-red-100 px-1 py-0.5 text-red-700 font-semibold not-italic">
              INSUFFICIENT EVIDENCE
            </mark>
          );
        }
        if (/^\[EVID-\d+\]$/.test(part)) {
          const ref = part.slice(1, -1);
          return (
            <button
              key={i}
              onClick={() => onEvidenceClick(ref)}
              className="mx-0.5 cursor-pointer rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-mono text-blue-600 ring-1 ring-blue-200 hover:bg-blue-100 hover:ring-blue-400 transition-colors"
              title="Click to view source evidence"
            >
              {part}
            </button>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </p>
  );
}

// ===========================================================================
// Screening Tab
// ===========================================================================

function ScreeningTab({
  results,
}: {
  results: { id: string; list_name: string; status: string; match_confidence: number; entity_name: string; snippet: string; source_url: string | null }[];
}) {
  const hits     = results.filter((r) => r.status === "hit");
  const partials = results.filter((r) => r.status === "potential_match");
  const clears   = results.filter((r) => r.status === "clear");

  function statusStyle(status: string) {
    if (status === "hit")           return { border: "border-red-200",    bg: "bg-red-50",     badge: "bg-red-100 text-red-700 ring-red-300",         label: "HIT" };
    if (status === "potential_match") return { border: "border-orange-200", bg: "bg-orange-50", badge: "bg-orange-100 text-orange-700 ring-orange-200", label: "PARTIAL MATCH" };
    return                                   { border: "border-green-100", bg: "bg-green-50/30", badge: "bg-green-100 text-green-700 ring-green-200",  label: "CLEAR" };
  }

  return (
    <div className="max-w-3xl space-y-4">
      {/* Summary bar */}
      <div className="flex items-center gap-0 rounded-lg border border-gray-200 bg-white overflow-hidden">
        {[
          { label: "Hits", count: hits.length, color: hits.length > 0 ? "text-red-600" : "text-gray-400" },
          { label: "Partial Matches", count: partials.length, color: partials.length > 0 ? "text-orange-600" : "text-gray-400" },
          { label: "Clear", count: clears.length, color: "text-green-600" },
        ].map((s, i) => (
          <div key={i} className="flex flex-1 flex-col items-center gap-0.5 py-3 border-r border-gray-100 last:border-r-0">
            <span className={["text-xl font-bold tabular-nums", s.color].join(" ")}>{s.count}</span>
            <span className="text-[10px] font-medium uppercase tracking-wider text-gray-400">{s.label}</span>
          </div>
        ))}
      </div>

      {/* Results */}
      <div className="space-y-2">
        {results.map((r) => {
          const style = statusStyle(r.status);
          return (
            <div
              key={r.id}
              className={["rounded-lg border p-4", style.border, style.bg].join(" ")}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-semibold text-gray-900">{r.list_name}</span>
                    <span className="text-[10px] text-gray-500">·</span>
                    <span className="text-xs text-gray-600">{r.entity_name}</span>
                  </div>
                  <p className="text-xs text-gray-600 leading-relaxed">{r.snippet}</p>
                  {r.source_url && (
                    <a
                      href={r.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-1 inline-block text-[10px] text-blue-500 hover:underline"
                    >
                      View source ↗
                    </a>
                  )}
                </div>
                <div className="shrink-0 text-right">
                  <span className={["rounded px-2 py-0.5 text-[10px] font-bold ring-1", style.badge].join(" ")}>
                    {style.label}
                  </span>
                  {r.match_confidence > 0 && (
                    <p className="mt-1 text-xs font-semibold text-gray-600 tabular-nums">
                      {(r.match_confidence * 100).toFixed(0)}%
                    </p>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ===========================================================================
// Audit Trail Tab
// ===========================================================================

function AuditTrailTab({
  entries,
}: {
  entries: { id: string; timestamp: string; actor: string; action: string; detail: string; evidence_id?: string }[];
}) {
  return (
    <div className="max-w-3xl">
      <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
        <div className="border-b border-gray-100 px-5 py-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-gray-400">
            Audit Trail
            <span className="ml-2 font-normal normal-case text-gray-300">· {entries.length} entries · append-only</span>
          </p>
        </div>
        <div className="divide-y divide-gray-50">
          {entries.map((entry) => {
            const isHit = entry.action.toLowerCase().includes("hit") || entry.action.toLowerCase().includes("critical");
            const isAI  = entry.actor === "AI Agent";
            const isSys = entry.actor === "System";
            return (
              <div key={entry.id} className={["px-5 py-3", isHit ? "bg-red-50/40" : ""].join(" ")}>
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                      <span
                        className={[
                          "inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider",
                          isSys  ? "bg-gray-100 text-gray-500"
                          : isAI ? "bg-blue-100 text-blue-700"
                                 : "bg-purple-100 text-purple-700",
                        ].join(" ")}
                      >
                        {entry.actor}
                      </span>
                      <p className={["text-xs font-semibold", isHit ? "text-red-700" : "text-gray-900"].join(" ")}>
                        {entry.action}
                      </p>
                      {entry.evidence_id && (
                        <span className="font-mono text-[10px] text-blue-500 bg-blue-50 px-1 rounded">
                          {entry.evidence_id}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 leading-relaxed">{entry.detail}</p>
                  </div>
                  <p className="shrink-0 text-[10px] text-gray-400 whitespace-nowrap font-mono">
                    {new Date(entry.timestamp).toLocaleString("en-GB", {
                      day: "2-digit", month: "short",
                      hour: "2-digit", minute: "2-digit",
                    })}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// Evidence Modal
// ===========================================================================

function EvidenceModal({
  evidenceRef,
  evidence,
  onClose,
}: {
  evidenceRef: string;
  evidence: EvidenceLink | null;
  onClose: () => void;
}) {
  // Close on Escape
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const typeIcon: Record<string, string> = {
    investigation_step: "⬡",
    screening_result:   "⊗",
    kyc:                "◎",
    transaction:        "⇄",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/30 backdrop-blur-[1px]"
        onClick={onClose}
      />
      <div className="relative z-10 w-full max-w-md rounded-xl border border-gray-200 bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-bold text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
              {evidenceRef}
            </span>
            {evidence && (
              <span className="text-xs text-gray-500 capitalize">
                {typeIcon[evidence.source_type] ?? "◈"}{" "}
                {evidence.source_type.replace(/_/g, " ")}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 transition-colors text-sm"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-3">
          {evidence ? (
            <>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1">
                  Source Data
                </p>
                <p className="text-sm text-gray-800 leading-relaxed bg-gray-50 rounded p-3 font-mono text-xs">
                  {evidence.sentence_text ?? "No source text available"}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-0.5">Type</p>
                  <p className="text-gray-700 capitalize">{evidence.source_type.replace(/_/g, " ")}</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-0.5">Evidence ID</p>
                  <p className="font-mono text-gray-700">{evidenceRef}</p>
                </div>
                {evidence.step_id && (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-0.5">Step</p>
                    <p className="font-mono text-gray-700 truncate">{evidence.step_id}</p>
                  </div>
                )}
                {evidence.screening_result_id && (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-0.5">Screening Result</p>
                    <p className="font-mono text-gray-700 truncate">{evidence.screening_result_id}</p>
                  </div>
                )}
              </div>
              <div className="rounded bg-blue-50 border border-blue-100 px-3 py-2">
                <p className="text-[10px] text-blue-600 leading-relaxed">
                  Every factual claim in this narrative is linked to a verified evidence source. This citation was generated by deterministic Python code — not the LLM.
                </p>
              </div>
            </>
          ) : (
            <p className="text-sm text-gray-500">
              No evidence link found for <code className="font-mono">{evidenceRef}</code>.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// Small helpers
// ===========================================================================

function ConfidencePill({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const cls = pct >= 85 ? "bg-green-100 text-green-700" : pct >= 60 ? "bg-yellow-100 text-yellow-700" : "bg-red-100 text-red-700";
  return (
    <span className={["rounded px-2 py-0.5 text-[11px] font-semibold tabular-nums", cls].join(" ")}>
      {pct}%
    </span>
  );
}
