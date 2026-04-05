import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Argonis — AML Investigation Platform",
  description:
    "From alert to SAR narrative in 60 seconds. Evidence-first architecture: every sentence traces to a verified data source.",
};

// ---------------------------------------------------------------------------
// Accent colour used throughout
// ---------------------------------------------------------------------------
const Y = "#E8FF4D"; // yellow-green accent

export default function HomePage() {
  return (
    <div
      style={{ backgroundColor: "#0A0A0A", color: "#FFFFFF" }}
      className="min-h-screen font-sans antialiased"
    >
      {/* ── Nav ─────────────────────────────────────────────────────────── */}
      <nav
        style={{ backgroundColor: "#0A0A0A", borderBottom: "1px solid #1F1F1F" }}
        className="flex h-14 items-center justify-between px-8 sticky top-0 z-10"
        aria-label="Main navigation"
      >
        <span
          className="text-sm font-semibold tracking-widest uppercase"
          style={{ color: "#FFFFFF" }}
        >
          ARGONIS
        </span>
        <div className="flex items-center gap-6">
          <Link
            href="/dashboard"
            className="text-xs font-medium transition-colors"
            style={{ color: "#9CA3AF" }}
          >
            Dashboard
          </Link>
          <Link
            href="/dashboard"
            className="rounded px-4 py-2 text-xs font-semibold transition-opacity hover:opacity-90"
            style={{ backgroundColor: Y, color: "#0A0A0A" }}
          >
            Live Demo →
          </Link>
        </div>
      </nav>

      {/* ── Hero ────────────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-5xl px-8 pt-24 pb-20">
        <div
          className="mb-6 inline-block rounded px-3 py-1 text-xs font-semibold tracking-wider uppercase"
          style={{ backgroundColor: "#1A1A1A", color: Y }}
        >
          AML · Compliance · RegTech
        </div>

        <h1
          className="text-5xl font-bold leading-tight tracking-tight mb-6"
          style={{ maxWidth: "720px" }}
        >
          AML Investigations:{" "}
          <span style={{ color: Y }}>From Alert to Narrative</span>{" "}
          in 60 Seconds
        </h1>

        <p
          className="text-lg leading-relaxed mb-10"
          style={{ color: "#9CA3AF", maxWidth: "560px" }}
        >
          Every fact in the narrative traces to a verified data source.
          Zero hallucination by design.
        </p>

        <div className="flex items-center gap-4">
          <Link
            href="/dashboard"
            className="rounded px-6 py-3 text-sm font-semibold transition-opacity hover:opacity-90"
            style={{ backgroundColor: Y, color: "#0A0A0A" }}
          >
            See Live Demo →
          </Link>
          <a
            href="https://calendly.com/argonis/demo"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded border px-6 py-3 text-sm font-medium transition-colors hover:border-white"
            style={{ borderColor: "#333333", color: "#9CA3AF" }}
          >
            Book a Demo
          </a>
        </div>
      </section>

      {/* ── Divider ─────────────────────────────────────────────────────── */}
      <div style={{ borderTop: "1px solid #1A1A1A" }} />

      {/* ── Problem stats ───────────────────────────────────────────────── */}
      <section className="mx-auto max-w-5xl px-8 py-20">
        <p
          className="text-xs font-semibold tracking-widest uppercase mb-12"
          style={{ color: "#555555" }}
        >
          The AML Investigation Crisis
        </p>

        <div className="grid grid-cols-3 gap-0">
          {[
            {
              stat: "$8.8B",
              label: "fines issued to financial institutions for AML failures in 2023",
            },
            {
              stat: "95%",
              label: "of AML alerts are false positives, consuming analyst time on noise",
            },
            {
              stat: "21 hrs",
              label: "average time to complete one SAR investigation end-to-end",
            },
          ].map(({ stat, label }, i) => (
            <div
              key={i}
              className="pr-10"
              style={{
                borderLeft: i > 0 ? "1px solid #1F1F1F" : undefined,
                paddingLeft: i > 0 ? "2.5rem" : undefined,
              }}
            >
              <div
                className="text-5xl font-bold tracking-tight mb-3"
                style={{ color: Y }}
              >
                {stat}
              </div>
              <p className="text-sm leading-relaxed" style={{ color: "#6B7280" }}>
                {label}
              </p>
            </div>
          ))}
        </div>
      </section>

      <div style={{ borderTop: "1px solid #1A1A1A" }} />

      {/* ── Differentiators ─────────────────────────────────────────────── */}
      <section className="mx-auto max-w-5xl px-8 py-20">
        <p
          className="text-xs font-semibold tracking-widest uppercase mb-12"
          style={{ color: "#555555" }}
        >
          Built different. Here&apos;s why.
        </p>

        <div className="grid grid-cols-3 gap-10">
          {[
            {
              title: "Evidence-first architecture",
              body: "The LLM writes prose. Python code detects patterns. Every sentence maps to a real data source — investigation step, OFAC hit, or transaction record. Nothing is invented.",
            },
            {
              title: "European compliance ready",
              body: "AMLD6, FATF, PSD2. Built for EMIs, payment processors, and challenger banks expanding in the EU. SAR output follows JMLSG and EBA guidelines out of the box.",
            },
            {
              title: "Analysts in control",
              body: "Per-section approval. Inline evidence links. Confidence scores on every finding. Regulators can audit every decision. Human sign-off is never optional.",
            },
          ].map(({ title, body }, i) => (
            <div key={i}>
              <div
                className="w-8 h-px mb-5"
                style={{ backgroundColor: Y }}
              />
              <h3
                className="text-sm font-semibold mb-3"
                style={{ color: "#FFFFFF" }}
              >
                {title}
              </h3>
              <p className="text-sm leading-relaxed" style={{ color: "#6B7280" }}>
                {body}
              </p>
            </div>
          ))}
        </div>
      </section>

      <div style={{ borderTop: "1px solid #1A1A1A" }} />

      {/* ── How it works ────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-5xl px-8 py-20">
        <p
          className="text-xs font-semibold tracking-widest uppercase mb-12"
          style={{ color: "#555555" }}
        >
          How it works
        </p>

        <div className="grid grid-cols-4 gap-0">
          {[
            {
              n: "01",
              icon: "↑",
              title: "Upload alert",
              body: "CSV batch or REST API. Accepts any alert format — structuring, sanctions, velocity, TBML.",
            },
            {
              n: "02",
              icon: "⬡",
              title: "Agent investigates",
              body: "Screens OFAC SDN, OpenSanctions, adverse media. Detects transaction patterns. Gathers KYC context.",
            },
            {
              n: "03",
              icon: "▤",
              title: "Narrative generated",
              body: "Each sentence is anchored to a verified evidence source. No free-form generation.",
            },
            {
              n: "04",
              icon: "✓",
              title: "Analyst approves",
              body: "Review section by section. Accept, reject, or edit. Confidence scores visible throughout.",
            },
          ].map(({ n, icon, title, body }, i) => (
            <div
              key={i}
              className="pr-8"
              style={{
                borderLeft: i > 0 ? "1px solid #1F1F1F" : undefined,
                paddingLeft: i > 0 ? "2rem" : undefined,
              }}
            >
              <div
                className="text-xs font-mono mb-4"
                style={{ color: "#333333" }}
              >
                {n}
              </div>
              <div
                className="text-2xl mb-4"
                style={{ color: Y }}
              >
                {icon}
              </div>
              <h3
                className="text-sm font-semibold mb-2"
                style={{ color: "#FFFFFF" }}
              >
                {title}
              </h3>
              <p className="text-xs leading-relaxed" style={{ color: "#6B7280" }}>
                {body}
              </p>
            </div>
          ))}
        </div>
      </section>

      <div style={{ borderTop: "1px solid #1A1A1A" }} />

      {/* ── Founder credibility ─────────────────────────────────────────── */}
      <section className="mx-auto max-w-5xl px-8 py-20">
        <p
          className="text-xs font-semibold tracking-widest uppercase mb-12"
          style={{ color: "#555555" }}
        >
          Built by someone who&apos;s done the work
        </p>
        <div className="flex items-start gap-10">
          <div className="shrink-0 pt-1">
            <div className="w-8 h-px" style={{ backgroundColor: Y }} />
          </div>
          <p
            className="text-lg leading-relaxed"
            style={{ color: "#9CA3AF", maxWidth: "640px" }}
          >
            Argonis was built by a former JPMorgan GFCC investigator who spent
            two years writing AML investigation narratives and filing SARs across
            Investigations and Sanctions/Blocked Assets. EU citizen. Trilingual
            (English, Portuguese, Spanish). Relocating to Europe to serve the
            market firsthand.
          </p>
        </div>
      </section>

      <div style={{ borderTop: "1px solid #1A1A1A" }} />

      {/* ── Comparison table ────────────────────────────────────────────── */}
      <section className="mx-auto max-w-5xl px-8 py-20">
        <p
          className="text-xs font-semibold tracking-widest uppercase mb-10"
          style={{ color: "#555555" }}
        >
          How it&apos;s different
        </p>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr style={{ borderBottom: "1px solid #1F1F1F" }}>
                {["", "Bretton AI", "Lucinity", "Nasdaq Verafin", "Argonis"].map(
                  (h, i) => (
                    <th
                      key={i}
                      className={[
                        "pb-4 text-left text-xs font-semibold tracking-wider",
                        i === 0
                          ? "pr-6 w-40"
                          : i === 4
                            ? "pl-6 uppercase"
                            : "px-6",
                      ].join(" ")}
                      style={{
                        color: i === 4 ? Y : i === 0 ? "#333333" : "#555555",
                      }}
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {[
                [
                  "Architecture",
                  "LLM-driven",
                  "AI copilot",
                  "Enterprise platform",
                  "Evidence-first",
                ],
                [
                  "Narrative source",
                  "LLM generates",
                  "LLM assists",
                  "Template-based",
                  "LLM assembles from verified data",
                ],
                [
                  "Fact verification",
                  "Post-hoc review",
                  "Manual",
                  "Manual",
                  "Inline — every claim linked to source",
                ],
                [
                  "European focus",
                  "US-first",
                  "Nordic-first",
                  "US enterprise",
                  "AMLD6-native, built for EU EMIs",
                ],
                ["Deployment", "Months", "Weeks", "Months", "Days"],
                [
                  "Hallucination risk",
                  "Medium",
                  "Medium",
                  "Low",
                  "Near-zero by design",
                ],
              ].map((row, ri) => (
                <tr key={ri} style={{ borderBottom: "1px solid #151515" }}>
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      className={[
                        "py-3.5 text-sm",
                        ci === 0 ? "pr-6 text-xs font-semibold uppercase tracking-wider" : ci === 4 ? "pl-6 font-semibold" : "px-6",
                      ].join(" ")}
                      style={{
                        color:
                          ci === 4
                            ? Y
                            : ci === 0
                              ? "#444444"
                              : "#6B7280",
                      }}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div style={{ borderTop: "1px solid #1A1A1A" }} />

      {/* ── Final CTA ───────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-5xl px-8 py-24 text-center">
        <h2
          className="text-4xl font-bold tracking-tight mb-4"
        >
          Ready to see it?
        </h2>
        <p
          className="text-sm mb-10"
          style={{ color: "#6B7280" }}
        >
          No sign-up required. Full demo data included.
        </p>
        <Link
          href="/dashboard"
          className="inline-block rounded px-8 py-4 text-sm font-semibold transition-opacity hover:opacity-90"
          style={{ backgroundColor: Y, color: "#0A0A0A" }}
        >
          Try the live demo →
        </Link>
      </section>

      {/* ── Footer ──────────────────────────────────────────────────────── */}
      <footer
        style={{ borderTop: "1px solid #1A1A1A" }}
        className="px-8 py-8"
      >
        <div className="mx-auto max-w-5xl flex items-center justify-between gap-6 flex-wrap">
          <p className="text-xs" style={{ color: "#333333" }}>
            Argonis — AML Investigation Platform · Built for European compliance
          </p>
          <div className="flex items-center gap-6">
            <a
              href="/privacy"
              className="text-xs transition-colors hover:text-white"
              style={{ color: "#333333" }}
            >
              Privacy Policy
            </a>
            <a
              href="mailto:daniel@argonis.ai"
              className="text-xs transition-colors hover:text-white"
              style={{ color: "#333333" }}
            >
              Contact
            </a>
            <a
              href="https://www.linkedin.com/company/argonis"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs transition-colors hover:text-white"
              style={{ color: "#333333" }}
            >
              LinkedIn
            </a>
            <p className="text-xs" style={{ color: "#222222" }}>
              © 2026
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
