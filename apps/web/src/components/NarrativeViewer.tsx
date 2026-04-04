"use client";

import { useState } from "react";
import { approveNarrativeSections, editNarrativeSection } from "@/lib/api";
import type { NarrativeRow, EvidenceLink, NarrativeSection } from "@/lib/types";

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
    [...narrative.narrative_sections].sort(
      (a, b) => a.order_index - b.order_index,
    ),
  );
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<string>("");
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [approvingKey, setApprovingKey] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

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
      // Demo mode: optimistic update only
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

  return (
    <div className="space-y-3">
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

      {/* Sections */}
      {sections.map((section) => {
        const confidence = sectionConfidence(section);
        const isEditing = editingKey === section.section_key;
        const isSaving = savingKey === section.section_key;
        const isApproving = approvingKey === section.section_key;
        const hasInsufficient = section.content.includes("INSUFFICIENT EVIDENCE");

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
              <div className="flex items-center gap-3">
                <h4 className="text-sm font-semibold text-gray-900">
                  {section.title}
                </h4>
                {hasInsufficient && (
                  <span className="rounded bg-red-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-600 ring-1 ring-red-200">
                    Needs Input
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {/* Confidence indicator */}
                {confidence != null && (
                  <ConfidencePill confidence={confidence} />
                )}
                {/* Approval badge */}
                <ApprovalBadge status={section.approval_status} />
              </div>
            </div>

            {/* Section body */}
            <div className="px-5 py-4">
              {isEditing ? (
                <div className="space-y-2">
                  <textarea
                    value={editDraft}
                    onChange={(e) => setEditDraft(e.target.value)}
                    className="w-full rounded border border-gray-200 bg-gray-50 p-3 text-sm text-gray-800 leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-200 resize-y min-h-[120px]"
                    autoFocus
                  />
                  {saveError && (
                    <p className="text-xs text-red-600">{saveError}</p>
                  )}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => saveEdit(section)}
                      disabled={isSaving}
                      className="rounded bg-[#111] px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-800 disabled:opacity-50 transition-colors"
                    >
                      {isSaving ? "Saving…" : "Save"}
                    </button>
                    <button
                      onClick={() => setEditingKey(null)}
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
                  {/* Approve */}
                  <button
                    onClick={() => handleApprove(section, "approve")}
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

                  {/* Flag / Reject */}
                  <button
                    onClick={() => handleApprove(section, "reject")}
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
                  {/* Edit */}
                  <button
                    onClick={() => startEdit(section)}
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
      })}
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
  // Build evidence ref → sentence_text map for tooltips
  const evidenceMap = new Map<string, string>();
  evidenceLinks.forEach((el) => {
    if (el.sentence_text) {
      evidenceMap.set(el.evidence_ref, el.sentence_text);
    }
  });

  // Split on [EVID-XXX] tokens and INSUFFICIENT EVIDENCE
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
          const ref = part.slice(1, -1); // "EVID-001"
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
