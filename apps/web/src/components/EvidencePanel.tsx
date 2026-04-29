"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { EvidenceLink } from "@/lib/types";

const HIGHLIGHT_MS = 1500;

function rowFromLink(el: EvidenceLink): {
  id: string;
  category: string;
  fact: string;
  confidence: number;
} {
  const sd = el.source_data ?? {};
  const cat = String(sd.category ?? "unknown").toUpperCase();
  const desc = String(sd.description ?? "");
  const val = String(sd.value ?? "");
  const conf =
    typeof sd.confidence === "number" && !Number.isNaN(sd.confidence)
      ? Math.min(1, Math.max(0, sd.confidence))
      : 0.5;
  return {
    id: el.evidence_ref,
    category: cat,
    fact: `${desc}: ${val}`.trim().slice(0, 220) || el.sentence_text || el.evidence_ref,
    confidence: conf,
  };
}

export function EvidencePanel({ links }: { links: EvidenceLink[] }) {
  const rows = links.map(rowFromLink);
  const refs = useRef<Record<string, HTMLDivElement | null>>({});
  const [flashId, setFlashId] = useState<string | null>(null);

  const onHighlight = useCallback((ev: Event) => {
    const e = ev as CustomEvent<{ evidenceId: string }>;
    const id = e.detail?.evidenceId;
    if (!id) return;
    const node = refs.current[id];
    node?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setFlashId(id);
    window.setTimeout(() => setFlashId(null), HIGHLIGHT_MS);
  }, []);

  useEffect(() => {
    window.addEventListener("argonis:highlight-evidence", onHighlight);
    return () =>
      window.removeEventListener("argonis:highlight-evidence", onHighlight);
  }, [onHighlight]);

  if (rows.length === 0) {
    return (
      <div className="rounded border border-neutral-800 bg-neutral-900/50 p-4 text-xs text-neutral-500">
        No evidence links for this narrative.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-neutral-500">
        Evidence
      </h3>
      <div className="max-h-[calc(100vh-8rem)] space-y-2 overflow-y-auto pr-1">
        {rows.map((r) => (
          <div
            key={r.id}
            ref={(el) => {
              refs.current[r.id] = el;
            }}
            data-evidence-id={r.id}
            className={[
              "rounded border border-neutral-800 bg-neutral-900/40 p-3 transition-colors",
              flashId === r.id ? "animate-pulse bg-cyan-500/20 ring-1 ring-cyan-500/40" : "",
            ].join(" ")}
          >
            <div className="flex items-center gap-2">
              <span className="rounded border border-cyan-500/30 bg-cyan-500/10 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                {r.id}
              </span>
              <span className="rounded bg-neutral-800 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-neutral-400">
                {r.category}
              </span>
            </div>
            <p className="mt-2 text-xs leading-snug text-neutral-300">{r.fact}</p>
            <div className="mt-2 h-1 w-full overflow-hidden rounded bg-neutral-800">
              <div
                className="h-full rounded bg-cyan-600/70"
                style={{ width: `${Math.round(r.confidence * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
