"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { listCases } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";
import {
  SAMPLE_CASES,
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey>("created_at");
  const [demoMode, setDemoMode] = useState(false);

  const isDemoAllowed = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

  const loadCases = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listCases({ limit: 100 });
      setCases(data);
      setDemoMode(false);
    } catch {
      if (isDemoAllowed) {
        setError("API unreachable — showing sample data.");
        setCases(SAMPLE_CASES);
        setDemoMode(true);
      } else {
        setError("Unable to reach investigation API. Check your connection or contact support.");
        setCases([]);
        setDemoMode(false);
      }
    } finally {
      setLoading(false);
    }
  }, [isDemoAllowed]);

  useEffect(() => {
    loadCases();
  }, [loadCases]);

  function loadSampleData() {
    if (!isDemoAllowed) return;
    setCases(SAMPLE_CASES);
    setDemoMode(true);
    setError(null);
    setLoading(false);
  }

  const sorted = [...cases].sort((a, b) => {
    const byCreated = () =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    const byRisk = () => (b.risk_score ?? 0) - (a.risk_score ?? 0);
    if (sort === "risk") return byRisk() || byCreated();
    if (sort === "status") {
      const s = a.status.localeCompare(b.status);
      return s !== 0 ? s : byCreated();
    }
    if (sort === "created_at") {
      const c = byCreated();
      return c !== 0 ? c : byRisk();
    }
    return byCreated() || byRisk();
  });

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Page header */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-surface-1 px-5">
        <div className="flex items-center gap-3">
          <h1 className="text-xs font-semibold uppercase tracking-wider text-white">
            Alert Queue
          </h1>
          {cases.length > 0 && (
            <span className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[10px] text-text-muted">
              {cases.length}
            </span>
          )}
          {demoMode && (
            <span className="rounded bg-accent-subtle px-1.5 py-0.5 font-mono text-[10px] font-medium text-accent-DEFAULT ring-1 ring-accent-DEFAULT/30">
              DEMO
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isDemoAllowed && (
            <button
              onClick={loadSampleData}
              className="rounded border border-border px-2.5 py-1 text-[11px] font-medium text-text-muted transition-colors hover:border-border-strong hover:text-white"
            >
              Sample Data
            </button>
          )}
          <button
            onClick={() => router.push("/dashboard/upload")}
            className="rounded bg-accent-DEFAULT px-2.5 py-1 text-[11px] font-semibold text-surface-base transition-colors hover:bg-accent-hover"
          >
            Upload Alerts
          </button>
        </div>
      </header>

      {/* Demo data banner — persistent, not dismissible */}
      {demoMode && (
        <div className="shrink-0 bg-red-900 px-5 py-2.5 border-b border-red-800">
          <p className="text-sm font-semibold text-white">
            ⚠ DEMO DATA — NOT REAL PIPELINE OUTPUT. API unreachable or demo mode enabled.
          </p>
        </div>
      )}

      {/* Error / info banner */}
      {error && !demoMode && (
        <div className="shrink-0 border-b border-red-200 bg-red-50 px-5 py-2.5">
          <p className="text-xs font-medium text-red-700">{error}</p>
        </div>
      )}

      {/* Stats bar */}
      {cases.length > 0 && (
        <div className="shrink-0 flex items-center border-b border-border bg-surface-1">
          {[
            { label: "Total", value: cases.length, color: "text-white" },
            {
              label: "Critical",
              value: cases.filter((c) => (c.risk_score ?? 0) >= 0.85).length,
              color: "text-danger-DEFAULT",
            },
            {
              label: "In Review",
              value: cases.filter((c) => c.status === "in_review").length,
              color: "text-accent-DEFAULT",
            },
            {
              label: "Closed",
              value: cases.filter((c) => c.status === "closed").length,
              color: "text-success-DEFAULT",
            },
          ].map((s, i) => (
            <div
              key={i}
              className="flex flex-col gap-0.5 border-r border-border px-5 py-2.5 last:border-r-0"
            >
              <span className={`font-mono text-base font-bold tabular-nums ${s.color}`}>
                {s.value}
              </span>
              <span className="text-[10px] uppercase tracking-wider text-text-muted">
                {s.label}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <LoadingSkeleton />
        ) : cases.length === 0 ? (
          <EmptyState
            isDemo={isDemoAllowed}
            onSample={isDemoAllowed ? loadSampleData : undefined}
          />
        ) : (
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 z-10 bg-surface-1">
              <tr className="border-b border-border">
                <Th>Case ID</Th>
                <Th>Customer</Th>
                <Th>Alert Type</Th>
                <SortableTh label="Risk" field="risk" current={sort} onSort={setSort} />
                <SortableTh label="Status" field="status" current={sort} onSort={setSort} />
                <SortableTh label="Created" field="created_at" current={sort} onSort={setSort} />
              </tr>
            </thead>
            <tbody>
              {sorted.map((c) => {
                const score = c.risk_score ?? null;
                const { label: statusLabel, classes: statusClasses } = statusMeta(c.status);
                return (
                  <tr
                    key={c.id}
                    onClick={() => {
                      window.location.href = `/dashboard/cases/${c.id}`;
                    }}
                    className="cursor-pointer border-b border-border transition-colors hover:bg-surface-2"
                  >
                    <td className="py-2.5 pl-5 pr-4 font-mono text-[11px] text-text-muted whitespace-nowrap">
                      {c.id.slice(-8).toUpperCase()}
                    </td>
                    <td className="py-2.5 pr-4 font-medium text-white whitespace-nowrap">
                      {parseCustomerName(c.title)}
                    </td>
                    <td className="py-2.5 pr-4 text-text-muted whitespace-nowrap">
                      {parseAlertType(c.title)}
                    </td>
                    <td className="py-2.5 pr-4 whitespace-nowrap">
                      {score != null ? (
                        <span
                          className={[
                            "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-semibold font-mono",
                            riskColors(score),
                          ].join(" ")}
                        >
                          {riskLabel(score)}
                          <span className="font-normal opacity-60">
                            {(score * 100).toFixed(0)}%
                          </span>
                        </span>
                      ) : (
                        <span className="text-text-faint">—</span>
                      )}
                    </td>
                    <td className="py-2.5 pr-4 whitespace-nowrap">
                      <span className={["rounded px-1.5 py-0.5 text-[11px] font-medium", statusClasses].join(" ")}>
                        {statusLabel}
                      </span>
                    </td>
                    <td className="py-2.5 pr-5 font-mono text-[11px] text-text-muted whitespace-nowrap">
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
    <th className="py-2 pl-5 pr-4 text-left text-[10px] font-semibold uppercase tracking-wider text-text-muted first:pl-5">
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
    <th className="py-2 pr-4 text-left">
      <button
        onClick={() => onSort(field)}
        className={[
          "flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider transition-colors",
          active ? "text-white" : "text-text-muted hover:text-white",
        ].join(" ")}
      >
        {label}
        <span className="text-[9px] opacity-60">{active ? "▼" : "⇅"}</span>
      </button>
    </th>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-px p-5">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="h-9 rounded bg-surface-2 animate-pulse" />
      ))}
    </div>
  );
}

function EmptyState({
  isDemo,
  onSample,
}: {
  isDemo: boolean;
  onSample?: (() => void) | undefined;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <p className="text-xs text-text-muted">
        {isDemo ? "Demo data not loaded." : "No cases available."}
      </p>
      <p className="mt-1 text-[11px] text-text-faint">
        {isDemo
          ? "Run: python3 scripts/seed_demo.py from apps/api (with .venv activated)."
          : onSample
            ? "Connect the API or load sample data to get started."
            : "Connect the API to get started."}
      </p>
      {onSample && (
        <button
          onClick={onSample}
          className="mt-5 rounded border border-border px-4 py-1.5 text-[11px] font-medium text-text-muted transition-colors hover:border-border-strong hover:text-white"
        >
          Try Sample Data
        </button>
      )}
    </div>
  );
}
