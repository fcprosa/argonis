"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { listCases } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";
import {
  SAMPLE_CASES,
  SAMPLE_RISK_SCORES,
  parseAlertType,
  parseCustomerName,
  riskLabel,
  riskColors,
  statusMeta,
  fmtDate,
} from "@/lib/sample-data";

type SortKey = "risk" | "created_at" | "status";

export default function AlertQueuePage() {
  const router = useRouter();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [riskScores, setRiskScores] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey>("risk");
  const [demoMode, setDemoMode] = useState(false);

  const loadCases = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listCases({ limit: 100 });
      // Extract risk scores from investigation_steps where available
      // (list endpoint doesn't include steps; we use description hints)
      const scores: Record<string, number> = {};
      data.forEach((c) => {
        const m = c.description?.match(/score (0\.\d+)/);
        if (m && m[1] != null) scores[c.id] = parseFloat(m[1]);
      });
      setCases(data);
      setRiskScores(scores);
      setDemoMode(false);
    } catch {
      setError("API unreachable — showing sample data.");
      setCases(SAMPLE_CASES);
      setRiskScores(SAMPLE_RISK_SCORES);
      setDemoMode(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCases();
  }, [loadCases]);

  function loadSampleData() {
    setCases(SAMPLE_CASES);
    setRiskScores(SAMPLE_RISK_SCORES);
    setDemoMode(true);
    setError(null);
    setLoading(false);
  }

  const sorted = [...cases].sort((a, b) => {
    if (sort === "risk") {
      return (riskScores[b.id] ?? 0) - (riskScores[a.id] ?? 0);
    }
    if (sort === "status") {
      return a.status.localeCompare(b.status);
    }
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Page header */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-6">
        <div className="flex items-center gap-4">
          <h1 className="text-sm font-semibold text-gray-900 tracking-tight">
            Alert Queue
          </h1>
          {cases.length > 0 && (
            <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500">
              {cases.length}
            </span>
          )}
          {demoMode && (
            <span className="rounded bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-700 ring-1 ring-yellow-300">
              DEMO
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadSampleData}
            className="rounded border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
          >
            Try Sample Data
          </button>
          <button
            onClick={() => router.push("/dashboard/upload")}
            className="rounded bg-[#111] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#333] transition-colors"
          >
            Upload Alerts
          </button>
        </div>
      </header>

      {/* Error banner */}
      {error && (
        <div className="shrink-0 border-b border-yellow-200 bg-yellow-50 px-6 py-2">
          <p className="text-xs text-yellow-700">{error}</p>
        </div>
      )}

      {/* Table area */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {loading ? (
          <LoadingSkeleton />
        ) : cases.length === 0 ? (
          <EmptyState onSample={loadSampleData} />
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <Th>Case ID</Th>
                <Th>Customer</Th>
                <Th>Alert Type</Th>
                <SortableTh
                  label="Risk Score"
                  field="risk"
                  current={sort}
                  onSort={setSort}
                />
                <SortableTh
                  label="Status"
                  field="status"
                  current={sort}
                  onSort={setSort}
                />
                <SortableTh
                  label="Created"
                  field="created_at"
                  current={sort}
                  onSort={setSort}
                />
              </tr>
            </thead>
            <tbody>
              {sorted.map((c, i) => {
                const score = riskScores[c.id];
                const { label: statusLabel, classes: statusClasses } =
                  statusMeta(c.status);
                return (
                  <tr
                    key={c.id}
                    onClick={() => router.push(`/dashboard/cases/${c.id}`)}
                    className={[
                      "cursor-pointer border-b border-gray-100 transition-colors",
                      i % 2 === 0 ? "bg-white" : "bg-gray-50/50",
                      "hover:bg-blue-50/50",
                    ].join(" ")}
                  >
                    <td className="py-3 pl-0 pr-4 font-mono text-xs text-gray-400 whitespace-nowrap">
                      {c.id.slice(-8).toUpperCase()}
                    </td>
                    <td className="py-3 pr-4 font-medium text-gray-900 whitespace-nowrap">
                      {parseCustomerName(c.title)}
                    </td>
                    <td className="py-3 pr-4 text-gray-600 whitespace-nowrap">
                      {parseAlertType(c.title)}
                    </td>
                    <td className="py-3 pr-4 whitespace-nowrap">
                      {score != null ? (
                        <span
                          className={[
                            "inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold",
                            riskColors(score),
                          ].join(" ")}
                        >
                          {riskLabel(score)}
                          <span className="font-normal opacity-70">
                            {(score * 100).toFixed(0)}%
                          </span>
                        </span>
                      ) : (
                        <span className="text-gray-300">—</span>
                      )}
                    </td>
                    <td className="py-3 pr-4 whitespace-nowrap">
                      <span
                        className={[
                          "rounded px-2 py-0.5 text-xs font-medium",
                          statusClasses,
                        ].join(" ")}
                      >
                        {statusLabel}
                      </span>
                    </td>
                    <td className="py-3 pr-0 text-xs text-gray-400 whitespace-nowrap">
                      {fmtDate(c.created_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="pb-2 pr-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
      {children}
    </th>
  );
}

function SortableTh({
  label,
  field,
  current,
  onSort,
}: {
  label: string;
  field: SortKey;
  current: SortKey;
  onSort: (f: SortKey) => void;
}) {
  const active = current === field;
  return (
    <th className="pb-2 pr-4 text-left">
      <button
        onClick={() => onSort(field)}
        className={[
          "flex items-center gap-1 text-xs font-semibold uppercase tracking-wider transition-colors",
          active ? "text-gray-900" : "text-gray-400 hover:text-gray-600",
        ].join(" ")}
      >
        {label}
        <span className="text-[10px]">{active ? "▼" : "⇅"}</span>
      </button>
    </th>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-2 animate-pulse">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="h-10 rounded bg-gray-100" />
      ))}
    </div>
  );
}

function EmptyState({ onSample }: { onSample: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <p className="text-sm text-gray-400">No cases found.</p>
      <p className="mt-1 text-xs text-gray-300">
        Connect the API or load sample data to get started.
      </p>
      <button
        onClick={onSample}
        className="mt-4 rounded border border-gray-200 px-4 py-2 text-xs font-medium text-gray-600 hover:bg-gray-50"
      >
        Try Sample Data
      </button>
    </div>
  );
}
