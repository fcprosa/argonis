import { track } from "@vercel/analytics";

/** Exactly four custom events — no PII beyond opaque case_id. */

export function trackSandboxView(): void {
  track("sandbox_view");
}

export function trackCaseOpen(caseId: string): void {
  track("case_open", { case_id: caseId });
}

export function trackEvidClick(): void {
  track("evid_click");
}

export function trackPdfExport(): void {
  track("pdf_export");
}
