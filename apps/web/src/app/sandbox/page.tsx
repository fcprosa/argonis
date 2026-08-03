"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { listCases, getCaseMetadata } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";
import { parseCustomerName, riskColors, riskLabel } from "@/lib/sample-data";
import {
  detectDemoKey,
  displayTypologyLabel,
  publicSourceAttribution,
  type DemoTypologyKey,
} from "@/lib/demo-display";
import { trackSandboxView } from "@/lib/track";

const HERO_LINE =
  "AML investigation drafts where every claim is traceable and screening gaps are declared";

const DISCLAIMER =
  "Synthetic typology reconstruction inspired by public enforcement findings. Subjects are fictional; sanctioned counterparties are real OFAC SDN entries.";

const FEEDBACK_EMAIL = "danielcamachorosa@gmail.com";

function demoKeyFor(caseRow: CaseSummary): DemoTypologyKey | null {
  return detectDemoKey(caseRow.title, caseRow.source_metadata);
}

function customerFor(caseRow: CaseSummary): string {
  return parseCustomerName(caseRow.title);
}

export default function SandboxPage() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [featuredPartial, setFeaturedPartial] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listCases({ limit: 100 });
      setCases(data);
      const featured = data.find((c) => c.source_metadata?.is_featured === true);
      if (featured) {
        try {
          const meta = await getCaseMetadata(featured.id);
          setFeaturedPartial((meta.coverage_gaps?.length ?? 0) > 0);
        } catch {
          // Featured card still renders; partial badge omitted if metadata fails.
          setFeaturedPartial(false);
        }
      }
    } catch {
      setError("Unable to load demo cases. Check that the API is reachable.");
      setCases([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    trackSandboxView();
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const { featured, support } = useMemo(() => {
    const featuredCase =
      cases.find((c) => c.source_metadata?.is_featured === true) ?? null;
    const supportCases = cases.filter(
      (c) => c.source_metadata?.is_featured !== true,
    );
    return { featured: featuredCase, support: supportCases };
  }, [cases]);

  return (
    <div className="min-h-screen bg-surface-base text-white">
      <header className="border-b border-border px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
          <Link
            href="/"
            className="text-xs font-semibold uppercase tracking-widest text-white"
          >
            Argonis
          </Link>
          <span className="text-[10px] uppercase tracking-wider text-text-muted">
            Public sandbox
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-12">
        <section className="mb-8 sm:mb-10">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-accent-DEFAULT">
            Sandbox
          </p>
          <h1 className="text-xl font-semibold leading-snug tracking-tight text-white sm:text-2xl">
            {HERO_LINE}
          </h1>
        </section>

        {loading && (
          <p className="text-sm text-text-muted">Loading demo cases…</p>
        )}
        {error && (
          <p className="mb-6 text-sm text-danger-DEFAULT" role="alert">
            {error}
          </p>
        )}

        {!loading && !error && featured && (
          <FeaturedCard
            caseRow={featured}
            showPartialBadge={featuredPartial}
          />
        )}

        {!loading && !error && support.length > 0 && (
          <section className="mt-6 space-y-3">
            <h2 className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
              More reconstructions
            </h2>
            <ul className="space-y-3">
              {support.map((c) => (
                <li key={c.id}>
                  <SupportCard caseRow={c} />
                </li>
              ))}
            </ul>
          </section>
        )}

        {!loading && !error && !featured && cases.length === 0 && (
          <p className="text-sm text-text-muted">No demo cases available.</p>
        )}

        <section className="mt-10 border-t border-border pt-8">
          <p className="text-sm text-text-muted leading-relaxed">{DISCLAIMER}</p>
        </section>

        <section className="mt-8 pb-4">
          <a
            href={`mailto:${FEEDBACK_EMAIL}`}
            className="inline-flex text-sm font-semibold text-accent-DEFAULT underline-offset-4 hover:underline"
          >
            Questions or feedback? Email me directly
          </a>
          <p className="mt-2 break-all font-mono text-xs text-white">
            {FEEDBACK_EMAIL}
          </p>
          <p className="mt-2 text-xs text-text-muted">I reply within a day.</p>
        </section>
      </main>
    </div>
  );
}

function FeaturedCard({
  caseRow,
  showPartialBadge,
}: {
  caseRow: CaseSummary;
  showPartialBadge: boolean;
}) {
  const score = caseRow.risk_score ?? null;
  const key = demoKeyFor(caseRow);
  const customer = customerFor(caseRow);
  const typology = key ? displayTypologyLabel(key) : caseRow.title;

  return (
    <article className="rounded-lg border border-amber-500/40 bg-surface-1 p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
          Featured
        </span>
        {showPartialBadge && (
          <span className="rounded border border-orange-500/40 bg-orange-500/10 px-1.5 py-0.5 text-[10px] font-semibold leading-snug text-orange-300">
            Partial screening — coverage gap declared
          </span>
        )}
      </div>

      <h2 className="text-base font-semibold text-white sm:text-lg">
        {typology}
      </h2>
      <p className="mt-1 break-words text-sm text-text-muted">{customer}</p>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        {score != null ? (
          <span
            className={[
              "inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold",
              riskColors(score),
            ].join(" ")}
          >
            {riskLabel(score)}
            <span className="font-normal opacity-60">
              {(score * 100).toFixed(0)}%
            </span>
          </span>
        ) : (
          <span className="text-xs text-text-faint">Risk —</span>
        )}
      </div>

      {key && <PublicSource demoKey={key} />}

      <Link
        href={`/dashboard/cases/${caseRow.id}`}
        className="mt-4 inline-flex text-sm font-semibold text-accent-DEFAULT underline-offset-4 hover:underline"
      >
        Open investigation →
      </Link>
    </article>
  );
}

function SupportCard({ caseRow }: { caseRow: CaseSummary }) {
  const score = caseRow.risk_score ?? null;
  const key = demoKeyFor(caseRow);
  const customer = customerFor(caseRow);
  const typology = key ? displayTypologyLabel(key) : caseRow.title;

  return (
    <article className="rounded-lg border border-border bg-surface-1 p-4">
      <h3 className="text-sm font-semibold text-white">{typology}</h3>
      <p className="mt-1 break-words text-xs text-text-muted">{customer}</p>
      <div className="mt-2">
        {score != null ? (
          <span
            className={[
              "inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold",
              riskColors(score),
            ].join(" ")}
          >
            {riskLabel(score)}
            <span className="font-normal opacity-60">
              {(score * 100).toFixed(0)}%
            </span>
          </span>
        ) : null}
      </div>
      {key && <PublicSource demoKey={key} />}
      <Link
        href={`/dashboard/cases/${caseRow.id}`}
        className="mt-3 inline-flex text-xs font-semibold text-accent-DEFAULT underline-offset-4 hover:underline"
      >
        Open investigation →
      </Link>
    </article>
  );
}

function PublicSource({ demoKey }: { demoKey: DemoTypologyKey }) {
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
