"use client";

export function DemoModeBanner() {
  if (process.env.NEXT_PUBLIC_DEMO_MODE !== "true") return null;
  return (
    <div
      className="shrink-0 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2"
      role="status"
    >
      <p className="text-[11px] leading-snug text-amber-200">
        DEMO MODE — Synthetic transaction data. Live OFAC SDN list (18,698 entries). No
        real customer PII. Investigations pre-computed for latency reasons.
      </p>
    </div>
  );
}
