"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { batchImportAlerts } from "@/lib/api";
import type { AlertImport } from "@/lib/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Stage = "upload" | "map" | "preview";

interface ParsedCSV {
  headers: string[];
  rows: string[][];
}

const TARGET_FIELDS: { key: keyof AlertImport; label: string; required: boolean }[] = [
  { key: "customer_name", label: "Customer Name", required: true },
  { key: "alert_type",    label: "Alert Type",    required: true },
  { key: "case_id",       label: "Case ID",       required: false },
  { key: "risk_score",    label: "Risk Score",    required: false },
  { key: "status",        label: "Status",        required: false },
  { key: "created_at",    label: "Created At",    required: false },
];

const SKIP = "__skip__";

// ---------------------------------------------------------------------------
// CSV parser (handles quoted fields)
// ---------------------------------------------------------------------------

function parseCSV(text: string): ParsedCSV {
  const lines = text.trim().split(/\r?\n/);

  function parseLine(line: string): string[] {
    const fields: string[] = [];
    let cur = "";
    let inQuote = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i]!;
      if (ch === '"') {
        if (inQuote && line[i + 1] === '"') { cur += '"'; i++; }
        else inQuote = !inQuote;
      } else if (ch === "," && !inQuote) {
        fields.push(cur.trim());
        cur = "";
      } else {
        cur += ch;
      }
    }
    fields.push(cur.trim());
    return fields;
  }

  const headers = parseLine(lines[0] ?? "");
  const rows = lines
    .slice(1)
    .filter((l) => l.trim().length > 0)
    .map(parseLine);

  return { headers, rows };
}

// ---------------------------------------------------------------------------
// Auto-detect column → target field mapping
// ---------------------------------------------------------------------------

const DETECTION_PATTERNS: Record<string, string[]> = {
  case_id:       ["caseid", "case_id", "alertid", "alert_id", "case", "id", "ref"],
  customer_name: ["customername", "customer_name", "customer", "clientname", "client_name", "client", "name", "subject"],
  alert_type:    ["alerttype", "alert_type", "type", "category", "alertcategory", "alert_category"],
  risk_score:    ["riskscore", "risk_score", "risk", "score", "risklevel", "risk_level"],
  status:        ["status", "state"],
  created_at:    ["createdat", "created_at", "created", "date", "timestamp", "datetime", "alert_date"],
};

function autoDetect(headers: string[]): Record<string, string> {
  const mapping: Record<string, string> = {};
  for (const [field, patterns] of Object.entries(DETECTION_PATTERNS)) {
    for (const header of headers) {
      const norm = header.toLowerCase().replace(/[\s_\-]/g, "");
      if (patterns.includes(norm)) {
        mapping[field] = header;
        break;
      }
    }
  }
  return mapping;
}

// ---------------------------------------------------------------------------
// Build AlertImport rows from CSV + mapping
// ---------------------------------------------------------------------------

function buildAlerts(
  csv: ParsedCSV,
  mapping: Record<string, string>,
): AlertImport[] {
  const indexOf = (col: string) => csv.headers.indexOf(col);

  return csv.rows.map((row) => {
    const get = (field: string): string | undefined => {
      const col = mapping[field];
      if (!col || col === SKIP) return undefined;
      const i = indexOf(col);
      return i >= 0 ? (row[i] ?? "").trim() || undefined : undefined;
    };

    const scoreRaw = get("risk_score");
    const score = scoreRaw != null ? parseFloat(scoreRaw) : undefined;

    return {
      case_id:       get("case_id"),
      customer_name: get("customer_name") ?? "Unknown",
      alert_type:    get("alert_type") ?? "Unknown",
      risk_score:    score != null && !isNaN(score) ? score : undefined,
      status:        get("status"),
      created_at:    get("created_at"),
    };
  });
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function UploadPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [stage, setStage] = useState<Stage>("upload");
  const [dragging, setDragging] = useState(false);
  const [csv, setCsv] = useState<ParsedCSV | null>(null);
  const [fileName, setFileName] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ---- file handling -------------------------------------------------------

  function loadFile(file: File) {
    setError(null);
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      try {
        const parsed = parseCSV(text);
        if (parsed.headers.length === 0 || parsed.rows.length === 0) {
          setError("CSV appears empty or has no data rows.");
          return;
        }
        setCsv(parsed);
        setFileName(file.name);
        setMapping(autoDetect(parsed.headers));
        setStage("map");
      } catch {
        setError("Could not parse the file. Make sure it is a valid CSV.");
      }
    };
    reader.readAsText(file);
  }

  function onFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) loadFile(file);
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) loadFile(file);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- import --------------------------------------------------------------

  async function runImport() {
    if (!csv) return;
    setImporting(true);
    setError(null);
    const alerts = buildAlerts(csv, mapping);
    try {
      await batchImportAlerts(alerts);
      router.push("/dashboard");
    } catch {
      setError("API unreachable — the alerts could not be saved. Check that the backend is running.");
      setImporting(false);
    }
  }

  // ---- mapping validation --------------------------------------------------

  const missingRequired = TARGET_FIELDS
    .filter((f) => f.required && (!mapping[f.key] || mapping[f.key] === SKIP))
    .map((f) => f.label);

  const alerts = csv ? buildAlerts(csv, mapping) : [];
  const preview = alerts.slice(0, 5);

  // =========================================================================
  // Render
  // =========================================================================

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Page header */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-6">
        <h1 className="text-sm font-semibold text-gray-900 tracking-tight">
          Upload Alerts
        </h1>
        {stage !== "upload" && (
          <button
            onClick={() => { setCsv(null); setStage("upload"); setError(null); }}
            className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            ← Start over
          </button>
        )}
      </header>

      {/* Error banner */}
      {error && (
        <div className="shrink-0 border-b border-red-200 bg-red-50 px-6 py-2">
          <p className="text-xs text-red-700">{error}</p>
        </div>
      )}

      <div className="flex-1 overflow-auto px-6 py-6">

        {/* ---------------------------------------------------------------- */}
        {/* STAGE 1: Upload                                                  */}
        {/* ---------------------------------------------------------------- */}
        {stage === "upload" && (
          <div className="mx-auto max-w-xl space-y-4">
            {/* Drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => fileInputRef.current?.click()}
              className={[
                "flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-8 py-16 cursor-pointer transition-colors select-none",
                dragging
                  ? "border-gray-400 bg-gray-50"
                  : "border-gray-200 hover:border-gray-300 hover:bg-gray-50/50",
              ].join(" ")}
            >
              <span className="text-3xl text-gray-300">↑</span>
              <p className="text-sm font-medium text-gray-600">
                Drop a CSV file here, or click to browse
              </p>
              <p className="text-xs text-gray-400">
                .csv files only · any column order accepted
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={onFileInputChange}
              />
            </div>

            {/* Sample download */}
            <div className="flex items-center justify-between rounded border border-gray-100 bg-gray-50 px-4 py-3">
              <div>
                <p className="text-xs font-medium text-gray-700">
                  Don&apos;t have a file yet?
                </p>
                <p className="text-xs text-gray-400">
                  Download the template with 5 sample AML alerts.
                </p>
              </div>
              <a
                href="/sample-alerts.csv"
                download="sample-alerts.csv"
                className="rounded border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 transition-colors whitespace-nowrap"
              >
                Try sample CSV
              </a>
            </div>

            {/* Format hint */}
            <p className="text-center text-xs text-gray-300">
              Expected columns (any names accepted — you&apos;ll map them next):{" "}
              <span className="font-mono">case_id, customer_name, alert_type, risk_score, status, created_at</span>
            </p>
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* STAGE 2: Column mapper                                           */}
        {/* ---------------------------------------------------------------- */}
        {stage === "map" && csv && (
          <div className="mx-auto max-w-xl space-y-6">
            <div className="rounded border border-gray-100 bg-gray-50 px-4 py-2 text-xs text-gray-500">
              <span className="font-medium text-gray-700">{fileName}</span>
              {" "}· {csv.rows.length} row{csv.rows.length !== 1 ? "s" : ""} · {csv.headers.length} columns detected
            </div>

            <div>
              <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-400">
                Map your columns
              </p>
              <div className="space-y-2">
                {TARGET_FIELDS.map((field) => (
                  <div
                    key={field.key}
                    className="flex items-center justify-between gap-4 rounded border border-gray-100 bg-white px-4 py-2.5"
                  >
                    <div className="min-w-0">
                      <span className="text-sm font-medium text-gray-800">
                        {field.label}
                      </span>
                      {field.required && (
                        <span className="ml-1.5 text-red-400 text-xs">*</span>
                      )}
                    </div>
                    <select
                      value={mapping[field.key] ?? SKIP}
                      onChange={(e) =>
                        setMapping((prev) => ({ ...prev, [field.key]: e.target.value }))
                      }
                      className="rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700 focus:outline-none focus:ring-1 focus:ring-gray-400"
                    >
                      <option value={SKIP}>— skip —</option>
                      {csv.headers.map((h) => (
                        <option key={h} value={h}>
                          {h}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            </div>

            {missingRequired.length > 0 && (
              <p className="text-xs text-red-500">
                Required: {missingRequired.join(", ")}
              </p>
            )}

            <button
              disabled={missingRequired.length > 0}
              onClick={() => setStage("preview")}
              className="w-full rounded bg-[#111] py-2 text-xs font-medium text-white hover:bg-[#222] transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              Preview {csv.rows.length} alert{csv.rows.length !== 1 ? "s" : ""} →
            </button>
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* STAGE 3: Preview + import                                        */}
        {/* ---------------------------------------------------------------- */}
        {stage === "preview" && csv && (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                Preview — first {Math.min(5, csv.rows.length)} of {csv.rows.length} rows
              </p>
              <button
                onClick={() => setStage("map")}
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                ← Edit mapping
              </button>
            </div>

            <div className="overflow-auto rounded border border-gray-100">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50">
                    <Th>Customer</Th>
                    <Th>Alert Type</Th>
                    <Th>Risk Score</Th>
                    <Th>Status</Th>
                    <Th>Case ID</Th>
                    <Th>Created At</Th>
                  </tr>
                </thead>
                <tbody>
                  {preview.map((a, i) => (
                    <tr key={i} className="border-b border-gray-50 last:border-0">
                      <td className="px-3 py-2 font-medium text-gray-800">{a.customer_name}</td>
                      <td className="px-3 py-2 text-gray-600">{a.alert_type}</td>
                      <td className="px-3 py-2 text-gray-600">
                        {a.risk_score != null
                          ? <RiskBadge score={a.risk_score} />
                          : <span className="text-gray-300">—</span>}
                      </td>
                      <td className="px-3 py-2 text-gray-500">{a.status ?? "open"}</td>
                      <td className="px-3 py-2 font-mono text-gray-400">{a.case_id ?? "—"}</td>
                      <td className="px-3 py-2 text-gray-400">
                        {a.created_at ? new Date(a.created_at).toLocaleDateString("en-GB") : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {csv.rows.length > 5 && (
              <p className="text-xs text-gray-400">
                +{csv.rows.length - 5} more row{csv.rows.length - 5 !== 1 ? "s" : ""} not shown
              </p>
            )}

            <button
              onClick={runImport}
              disabled={importing}
              className="rounded bg-[#111] px-6 py-2 text-xs font-medium text-white hover:bg-[#222] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {importing
                ? "Importing…"
                : `Import ${alerts.length} alert${alerts.length !== 1 ? "s" : ""}`}
            </button>
          </div>
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
    <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-gray-400">
      {children}
    </th>
  );
}

function RiskBadge({ score }: { score: number }) {
  let label = "LOW";
  let cls = "bg-gray-100 text-gray-600";
  if (score >= 0.85) { label = "CRITICAL"; cls = "bg-red-100 text-red-700"; }
  else if (score >= 0.65) { label = "HIGH"; cls = "bg-orange-100 text-orange-700"; }
  else if (score >= 0.40) { label = "MEDIUM"; cls = "bg-yellow-100 text-yellow-700"; }

  return (
    <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold ${cls}`}>
      {label}
      <span className="font-normal opacity-70">{(score * 100).toFixed(0)}%</span>
    </span>
  );
}
