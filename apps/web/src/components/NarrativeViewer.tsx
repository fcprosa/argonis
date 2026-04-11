"use client";

import { useState, useMemo } from "react";
import { approveNarrativeSections, editNarrativeSection } from "@/lib/api";
import type { NarrativeRow, EvidenceLink, NarrativeSection, SectionKey } from "@/lib/types";

// ---------------------------------------------------------------------------
// Section metadata — canonical ordering + display info for pipeline keys
// ---------------------------------------------------------------------------

interface SectionMeta {
  key: SectionKey;
  displayTitle: string;
  description: string;
}

const SECTION_METADATA: SectionMeta[] = [
  {
    key: "subject_information",
    displayTitle: "Subject Information",
    description: "Identity, KYC profile, beneficial ownership, and screening results",
  },
  {
    key: "suspicious_activity_summary",
    displayTitle: "Suspicious Activity Summary",
    description: "Executive-level summary of why this activity is suspicious",
  },
  {
    key: "detailed_narrative",
    displayTitle: "Detailed Narrative",
    description: "Chronological account of the suspicious activity with cited evidence",
  },
  {
    key: "supporting_evidence",
    displayTitle: "Supporting Evidence",
    description: "Key evidence items, categories, and how each supports the filing decision",
  },
];

const KNOWN_KEYS = new Set<string>(SECTION_METADATA.map((m) => m.key));

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  narrative: NarrativeRow;
  evidenceLinks: EvidenceLink[];
  overallConfidence: number | null;
  demoMode: boolean;
  onSectionApproved: () => Promise<void>;
}

export function NarrativeViewer({
  narrative,
  evidenceLinks,
  overallConfidence,
  demoMode,
  onSectionApproved,
}: Props) {
  const [sections, setSections] = useState<NarrativeSection[]>(
    narrative.narrative_sections,
  );
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<string>("");
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [approvingKey, setApprovingKey] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Build a map of section_key → section for O(1) lookup
  const sectionMap = useMemo(() => {
    const map = new Map<string, NarrativeSection>();
    sections.forEach((s) => map.set(s.section_key, s));
    return map;
  }, [sections]);

  // Sections with keys NOT in SECTION_METADATA (unknown / future keys)
  const unknownSections = useMemo(
    () => sections.filter((s) => !KNOWN_KEYS.has(s.section_key)),
    [sections],
  );

  // ---------------------------------------------------------------------------
  // Confidence derivation per section
  // ---------------------------------------------------------------------------
  function sectionConfidence(section: NarrativeSection): number | null {
    if (section.content.includes("INSUFFICIENT EVIDENCE")) return 0;
    if (section.approval_status === "rejected") return 0.2;
    return overallConfidence;
  }

  // ---------------------------------------------------------------------------
  // Approve / reject
  // ---------------------------------------------------------------------------
  async function handleApprove(section: NarrativeSection, action: "approve" | "reject") {
    if (demoMode) {
      setSections((prev) =>
        prev.map((s) =>
          s.section_key === section.section_key
            ? { ...s, approval_status: action === "approve" ? "approved" : "rejected" }
            : s,
        ),
      );
      return;
    }

    setApprovingKey(section.section_key);
    try {
      await approveNarrativeSections(narrative.id, {
        section_keys: [section.section_key],
        action,
      });
      await onSectionApproved();
    } catch (err) {
      console.error("Approval failed:", err);
    } finally {
      setApprovingKey(null);
    }
  }

  // ---------------------------------------------------------------------------
  // Edit
  // ---------------------------------------------------------------------------
  function startEdit(section: NarrativeSection) {
    setEditingKey(section.section_key);
    setEditDraft(section.content);
    setSaveError(null);
  }

  async function saveEdit(section: NarrativeSection) {
    if (demoMode) {
      setSections((prev) =>
        prev.map((s) =>
          s.section_key === section.section_key
            ? { ...s, content: editDraft, approval_status: "pending" }
            : s,
        ),
      );
      setEditingKey(null);
      return;
    }

    setSavingKey(section.section_key);
    setSaveError(null);
    try {
      const updated = await editNarrativeSection(
        narrative.id,
        section.section_key,
        { content: editDraft },
      );
      setSections((prev) =>
        prev.map((s) => (s.section_key === updated.section_key ? updated : s)),
      );
      setEditingKey(null);
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : "Save failed",
      );
    } finally {
      setSavingKey(null);
    }
  }

  // ---------------------------------------------------------------------------
  // Summary bar
  // ---------------------------------------------------------------------------
  const approved = sections.filter((s) => s.approval_status === "approved").length;
  const rejected = sections.filter((s) => s.approval_status === "rejected").length;
  const pending = sections.filter((s) => s.approval_status === "pending").length;

  const isPartial = narrative.is_partial_screening ?? false;
  const screeningGaps = narrative.screening_gaps ?? [];
  const [partialDismissed, setPartialDismissed] = useState(false);

  return (
    <div className="space-y-3">
      {/* Demo data banner */}
      {demoMode && <DemoDataBanner />}

      {/* Partial screening coverage banner */}
      {isPartial && !partialDismissed && (
        <PartialScreeningBanner
          gaps={screeningGaps}
          onDismiss={() => setPartialDismissed(true)}
        />
      )}

      {/* Header */}
      <div className="rounded-lg border border-gray-200 bg-white px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
              Narrative
            </h3>
            <p className="text-sm font-semibold text-gray-900">{narrative.title}</p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="text-gray-400">v{narrative.version}</span>
            <NarrativeStatusBadge status={narrative.status} />
          </div>
        </div>

        {/* Approval summary */}
        <div className="mt-3 flex items-center gap-4 text-xs text-gray-500 border-t border-gray-100 pt-3">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-green-400" />
            {approved} approved
          </span>
          {rejected > 0 && (
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full bg-red-400" />
              {rejected} rejected
            </span>
          )}
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-gray-300" />
            {pending} pending
          </span>
          {sections.length > 0 && (
            <span className="ml-auto text-gray-400">
              {Math.round((approved / sections.length) * 100)}% complete
            </span>
          )}
        </div>
      </div>

      {/* Known sections — rendered in SECTION_METADATA order */}
      {SECTION_METADATA.map((meta) => {
        const section = sectionMap.get(meta.key);

        if (!section) {
          return (
            <MissingSectionPlaceholder
              key={meta.key}
              displayTitle={meta.displayTitle}
              description={meta.description}
            />
          );
        }

        return (
          <SectionCard
            key={meta.key}
            section={section}
            description={meta.description}
            confidence={sectionConfidence(section)}
            evidenceLinks={evidenceLinks}
            isEditing={editingKey === section.section_key}
            isSaving={savingKey === section.section_key}
            isApproving={approvingKey === section.section_key}
            editDraft={editDraft}
            saveError={editingKey === section.section_key ? saveError : null}
            onApprove={(action) => handleApprove(section, action)}
            onStartEdit={() => startEdit(section)}
            onSaveEdit={() => saveEdit(section)}
            onCancelEdit={() => setEditingKey(null)}
            onEditDraftChange={setEditDraft}
          />
        );
      })}

      {/* Unknown sections — rendered at the bottom with warning */}
      {unknownSections.length > 0 && (
        <>
          <UnknownSectionBanner count={unknownSections.length} />
          {unknownSections.map((section) => (
            <SectionCard
              key={section.section_key}
              section={section}
              description={null}
              confidence={sectionConfidence(section)}
              evidenceLinks={evidenceLinks}
              isEditing={editingKey === section.section_key}
              isSaving={savingKey === section.section_key}
              isApproving={approvingKey === section.section_key}
              editDraft={editDraft}
              saveError={editingKey === section.section_key ? saveError : null}
              onApprove={(action) => handleApprove(section, action)}
              onStartEdit={() => startEdit(section)}
              onSaveEdit={() => saveEdit(section)}
              onCancelEdit={() => setEditingKey(null)}
              onEditDraftChange={setEditDraft}
            />
          ))}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section card — renders one section with header, body, and actions
// ---------------------------------------------------------------------------

function SectionCard({
  section,
  description,
  confidence,
  evidenceLinks,
  isEditing,
  isSaving,
  isApproving,
  editDraft,
  saveError,
  onApprove,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
  onEditDraftChange,
}: {
  section: NarrativeSection;
  description: string | null;
  confidence: number | null;
  evidenceLinks: EvidenceLink[];
  isEditing: boolean;
  isSaving: boolean;
  isApproving: boolean;
  editDraft: string;
  saveError: string | null;
  onApprove: (action: "approve" | "reject") => void;
  onStartEdit: () => void;
  onSaveEdit: () => void;
  onCancelEdit: () => void;
  onEditDraftChange: (v: string) => void;
}) {
  const hasInsufficient = section.content.includes("INSUFFICIENT EVIDENCE");

  return (
    <div
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
        <div className="flex items-center gap-3">
          <div>
            <h4 className="text-sm font-semibold text-gray-900">
              {section.title}
            </h4>
            {description && (
              <p className="text-[10px] text-gray-400 mt-0.5">{description}</p>
            )}
          </div>
          {hasInsufficient && (
            <span className="rounded bg-red-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-600 ring-1 ring-red-200">
              Needs Input
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {confidence != null && (
            <ConfidencePill confidence={confidence} />
          )}
          <ApprovalBadge status={section.approval_status} />
        </div>
      </div>

      {/* Section body */}
      <div className="px-5 py-4">
        {isEditing ? (
          <div className="space-y-2">
            <textarea
              value={editDraft}
              onChange={(e) => onEditDraftChange(e.target.value)}
              className="w-full rounded border border-gray-200 bg-gray-50 p-3 text-sm text-gray-800 leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-200 resize-y min-h-[120px]"
              autoFocus
            />
            {saveError && (
              <p className="text-xs text-red-600">{saveError}</p>
            )}
            <div className="flex items-center gap-2">
              <button
                onClick={onSaveEdit}
                disabled={isSaving}
                className="rounded bg-[#111] px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-800 disabled:opacity-50 transition-colors"
              >
                {isSaving ? "Saving…" : "Save"}
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
            evidenceLinks={evidenceLinks}
          />
        )}
      </div>

      {/* Section footer — actions */}
      {!isEditing && (
        <div className="flex items-center justify-between border-t border-gray-100 px-5 py-2.5">
          <div className="flex items-center gap-1">
            <button
              onClick={() => onApprove("approve")}
              disabled={
                isApproving ||
                section.approval_status === "approved" ||
                hasInsufficient
              }
              title={
                hasInsufficient
                  ? "Resolve INSUFFICIENT EVIDENCE before approving"
                  : "Approve section"
              }
              className={[
                "rounded px-3 py-1 text-xs font-semibold transition-colors",
                section.approval_status === "approved"
                  ? "bg-green-100 text-green-700 cursor-default"
                  : hasInsufficient
                    ? "bg-gray-50 text-gray-300 cursor-not-allowed"
                    : "bg-green-50 text-green-700 hover:bg-green-100",
              ].join(" ")}
            >
              {isApproving ? "…" : section.approval_status === "approved" ? "Approved" : "Approve"}
            </button>

            <button
              onClick={() => onApprove("reject")}
              disabled={isApproving || section.approval_status === "rejected"}
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
              onClick={onStartEdit}
              className="hover:text-gray-700 transition-colors"
            >
              Edit
            </button>
            {section.approved_by && section.approved_at && (
              <span>
                {section.approval_status === "approved" ? "Approved" : "Updated"}{" "}
                {new Date(section.approved_at).toLocaleString("en-GB", {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Missing section placeholder — red warning for expected keys absent from API
// ---------------------------------------------------------------------------

function MissingSectionPlaceholder({
  displayTitle,
  description,
}: {
  displayTitle: string;
  description: string;
}) {
  return (
    <div className="rounded-lg border-2 border-dashed border-red-300 bg-red-50 px-5 py-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 text-red-500 text-sm">⚠</span>
        <div>
          <h4 className="text-sm font-semibold text-red-800">
            {displayTitle}
          </h4>
          <p className="text-[10px] text-red-500 mt-0.5">{description}</p>
          <p className="mt-2 text-xs font-medium text-red-700">
            Section missing from pipeline output — investigation incomplete.
          </p>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Unknown section banner — yellow warning for keys not in SECTION_METADATA
// ---------------------------------------------------------------------------

function UnknownSectionBanner({ count }: { count: number }) {
  return (
    <div className="rounded-lg border border-yellow-300 bg-yellow-50 px-5 py-3">
      <div className="flex items-center gap-2">
        <span className="text-yellow-600 text-sm">⚠</span>
        <p className="text-xs font-medium text-yellow-800">
          {count} unknown section{count > 1 ? "s" : ""} received from the pipeline.
          These section keys are not in the expected set and may indicate a pipeline version mismatch.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Partial screening coverage banner — dismissible per session, reappears on reload
// ---------------------------------------------------------------------------

function PartialScreeningBanner({
  gaps,
  onDismiss,
}: {
  gaps: string[];
  onDismiss: () => void;
}) {
  return (
    <div className="rounded-lg border border-yellow-400 bg-yellow-50 px-5 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <span className="mt-0.5 text-yellow-600 text-sm shrink-0">⚠</span>
          <div>
            <p className="text-sm font-semibold text-yellow-800">
              INCOMPLETE SCREENING COVERAGE
            </p>
            <p className="mt-1 text-xs text-yellow-700">
              {gaps.length > 0
                ? gaps.join("; ")
                : "One or more screening sources were unavailable."}
              {" "}Manual supplementation required before filing.
            </p>
          </div>
        </div>
        <button
          onClick={onDismiss}
          className="shrink-0 rounded p-1 text-yellow-500 hover:bg-yellow-100 hover:text-yellow-700 transition-colors"
          aria-label="Dismiss screening warning"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Demo data banner — unmissable, non-dismissible
// ---------------------------------------------------------------------------

export function DemoDataBanner() {
  return (
    <div className="rounded-lg bg-red-900 px-5 py-3">
      <p className="text-sm font-semibold text-white">
        ⚠ DEMO DATA — NOT REAL PIPELINE OUTPUT. API unreachable or demo mode enabled.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section content — renders prose with INSUFFICIENT EVIDENCE highlighted
// and [EVID-XXX] citations as badges
// ---------------------------------------------------------------------------

function SectionContent({
  content,
  evidenceLinks,
}: {
  content: string;
  evidenceLinks: EvidenceLink[];
}) {
  const evidenceMap = new Map<string, string>();
  evidenceLinks.forEach((el) => {
    if (el.sentence_text) {
      evidenceMap.set(el.evidence_ref, el.sentence_text);
    }
  });

  const SPLIT_RE = /(\[EVID-\d+\]|INSUFFICIENT EVIDENCE)/g;
  const parts = content.split(SPLIT_RE);

  return (
    <p className="text-sm text-gray-700 leading-relaxed">
      {parts.map((part, i) => {
        if (part === "INSUFFICIENT EVIDENCE") {
          return (
            <mark
              key={i}
              className="rounded bg-red-100 px-1 py-0.5 text-red-700 font-semibold not-italic"
            >
              INSUFFICIENT EVIDENCE
            </mark>
          );
        }
        if (/^\[EVID-\d+\]$/.test(part)) {
          const ref = part.slice(1, -1);
          const tip = evidenceMap.get(ref);
          return (
            <span
              key={i}
              title={tip ?? ref}
              className="mx-0.5 cursor-default rounded bg-blue-50 px-1 py-0.5 text-[11px] font-mono text-blue-600 ring-1 ring-blue-200 hover:bg-blue-100 transition-colors"
            >
              {part}
            </span>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Small sub-components
// ---------------------------------------------------------------------------

function ConfidencePill({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const classes =
    pct >= 85
      ? "bg-green-100 text-green-700"
      : pct >= 60
        ? "bg-yellow-100 text-yellow-700"
        : "bg-red-100 text-red-700";
  return (
    <span
      className={["rounded px-2 py-0.5 text-[11px] font-semibold tabular-nums", classes].join(" ")}
    >
      {pct}%
    </span>
  );
}

function ApprovalBadge({
  status,
}: {
  status: "pending" | "approved" | "rejected";
}) {
  const map = {
    pending: "text-gray-400",
    approved: "text-green-600 font-semibold",
    rejected: "text-red-600 font-semibold",
  } as const;
  const label = { pending: "Pending", approved: "Approved", rejected: "Flagged" };
  return (
    <span className={["text-xs", map[status]].join(" ")}>{label[status]}</span>
  );
}

function NarrativeStatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    draft: "bg-gray-100 text-gray-500",
    in_review: "bg-blue-100 text-blue-700",
    approved: "bg-green-100 text-green-700",
    rejected: "bg-red-100 text-red-700",
  };
  return (
    <span
      className={[
        "rounded px-2 py-0.5 text-[11px] font-medium capitalize",
        map[status] ?? "bg-gray-100 text-gray-500",
      ].join(" ")}
    >
      {status.replace("_", " ")}
    </span>
  );
}
