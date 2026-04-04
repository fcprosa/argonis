import type { CaseSummary, CaseDetail } from "./types";

// ---------------------------------------------------------------------------
// Sample cases — shown when "Try Sample Data" is clicked or API is unreachable
// ---------------------------------------------------------------------------

export const SAMPLE_CASES: CaseSummary[] = [
  {
    id: "demo-case-001",
    organization_id: "demo-org",
    alert_id: "demo-alert-001",
    title: "Investigation: Cash Structuring — Ahmad Al-Rashid",
    description: "Investigation complete. Narrative v1 ready for review.",
    status: "in_review",
    assigned_to: null,
    created_by: "demo",
    created_at: "2026-04-02T09:15:00Z",
    updated_at: "2026-04-02T09:47:00Z",
  },
  {
    id: "demo-case-002",
    organization_id: "demo-org",
    alert_id: "demo-alert-002",
    title: "Investigation: Wire Transfer Layering — Global Trade Corp Ltd",
    description: null,
    status: "open",
    assigned_to: null,
    created_by: "demo",
    created_at: "2026-04-02T11:30:00Z",
    updated_at: "2026-04-02T11:30:00Z",
  },
  {
    id: "demo-case-003",
    organization_id: "demo-org",
    alert_id: "demo-alert-003",
    title: "Investigation: Sanctions Match — Viktor Petrov",
    description: null,
    status: "open",
    assigned_to: null,
    created_by: "demo",
    created_at: "2026-04-03T08:05:00Z",
    updated_at: "2026-04-03T08:05:00Z",
  },
];

// ---------------------------------------------------------------------------
// Sample risk scores — derived from demo analysis step
// ---------------------------------------------------------------------------

export const SAMPLE_RISK_SCORES: Record<string, number> = {
  "demo-case-001": 0.87,
  "demo-case-002": 0.61,
  "demo-case-003": 0.94,
};

// ---------------------------------------------------------------------------
// Full sample case detail (demo-case-001 only — the "investigated" demo case)
// ---------------------------------------------------------------------------

export const SAMPLE_CASE_DETAIL: Record<string, CaseDetail> = {
  "demo-case-001": {
    case: {
      id: "demo-case-001",
      organization_id: "demo-org",
      alert_id: "demo-alert-001",
      title: "Investigation: Cash Structuring — Ahmad Al-Rashid",
      description: "Investigation complete. Narrative v1 ready for review.",
      status: "in_review",
      assigned_to: null,
      created_by: "demo",
      created_at: "2026-04-02T09:15:00Z",
      updated_at: "2026-04-02T09:47:00Z",
    },
    investigation_steps: [
      {
        id: "step-parse-001",
        case_id: "demo-case-001",
        organization_id: "demo-org",
        name: "parse",
        description: "Parsed alert into structured data",
        status: "completed",
        source_data: {
          alert_id: "AML-2026-00147",
          alert_type: "Cash Structuring",
          account_holder: "Ahmad Al-Rashid",
          account_number: "****4821",
          currency: "USD",
          reporting_threshold: 10000,
        },
        confidence_score: 1.0,
        created_by: "demo",
        created_at: "2026-04-02T09:17:00Z",
      },
      {
        id: "step-gather-001",
        case_id: "demo-case-001",
        organization_id: "demo-org",
        name: "gather",
        description: "Gathered KYC profiles, relationships, history",
        status: "completed",
        source_data: {
          kyc_profiles: 1,
          account_relationships: 3,
          transaction_history_days: 90,
        },
        confidence_score: 1.0,
        created_by: "demo",
        created_at: "2026-04-02T09:18:00Z",
      },
      {
        id: "step-screen-001",
        case_id: "demo-case-001",
        organization_id: "demo-org",
        name: "screen",
        description: "Screened 2 entities — 1 hit",
        status: "completed",
        source_data: {
          entity_names: ["Ahmad Al-Rashid", "Al-Rashid Trading LLC"],
          hits: 1,
        },
        confidence_score: 1.0,
        created_by: "demo",
        created_at: "2026-04-02T09:22:00Z",
      },
      {
        id: "step-analyze-001",
        case_id: "demo-case-001",
        organization_id: "demo-org",
        name: "analyze",
        description: "Risk: SAR_FILING (score 0.870)",
        status: "completed",
        source_data: {
          overall_risk_score: 0.87,
          recommended_action: "SAR_FILING",
          patterns_detected: ["structuring", "velocity"],
        },
        confidence_score: 0.87,
        created_by: "demo",
        created_at: "2026-04-02T09:25:00Z",
      },
    ],
    screening_results: [
      {
        id: "screen-001",
        case_id: "demo-case-001",
        organization_id: "demo-org",
        entity_name: "Ahmad Al-Rashid",
        match_confidence: 0.91,
        source_url: "https://sanctionssearch.ofac.treas.gov/",
        match_data: {
          list_name: "OFAC SDN List",
          match_type: "fuzzy_name",
          snippet:
            "AL-RASHID, Ahmad; DOB 14 Mar 1978; POB Baghdad, Iraq; nationality IRQ",
        },
        status: "pending",
        created_at: "2026-04-02T09:22:00Z",
      },
    ],
    narratives: [
      {
        id: "narrative-001",
        case_id: "demo-case-001",
        version: 1,
        title: "SAR Narrative — Ahmad Al-Rashid — Cash Structuring",
        status: "in_review",
        narrative_sections: [
          {
            id: "sec-001",
            section_key: "executive_summary",
            title: "Executive Summary",
            content:
              "Between 15 March and 28 March 2026, Ahmad Al-Rashid [EVID-001] conducted seven cash deposits totalling USD 68,450 across three branch locations. Each individual deposit fell below the USD 10,000 CTR threshold, ranging from USD 8,200 to USD 9,800 [EVID-002]. The deposits exhibit a statistically improbable clustering in the USD 9,000–9,900 band (confidence: 0.87), consistent with deliberate structuring to avoid Currency Transaction Report filing requirements under 31 U.S.C. § 5324 [EVID-003].",
            order_index: 0,
            approval_status: "approved",
            approved_by: "reviewer@demo.com",
            approved_at: "2026-04-02T14:10:00Z",
          },
          {
            id: "sec-002",
            section_key: "subject_profile",
            title: "Subject Profile",
            content:
              "Ahmad Al-Rashid (DOB: 14 March 1978, nationality: Iraqi) holds a personal checking account (****4821) opened 12 January 2024 [EVID-004]. KYC documentation lists occupation as 'import consultant' with declared annual income of USD 45,000. Account activity over the preceding 90 days prior to this alert shows an average monthly cash deposit of USD 3,200 — the March 2026 deposits represent a 615% deviation from established baseline [EVID-005].",
            order_index: 1,
            approval_status: "pending",
            approved_by: null,
            approved_at: null,
          },
          {
            id: "sec-003",
            section_key: "transaction_analysis",
            title: "Transaction Analysis",
            content:
              "Structuring pattern confirmed across seven transactions [EVID-002]. Velocity anomaly detected: 7 deposits in 13 days versus historical baseline of 1.2 deposits per month [EVID-005]. Geographic dispersion across 3 branches (Downtown, Midtown, Airport) suggests deliberate avoidance of teller familiarity [EVID-006]. INSUFFICIENT EVIDENCE to confirm beneficial ownership of Al-Rashid Trading LLC — further KYC refresh required before this entity can be included in the SAR filing.",
            order_index: 2,
            approval_status: "rejected",
            approved_by: "reviewer@demo.com",
            approved_at: "2026-04-02T14:12:00Z",
          },
          {
            id: "sec-004",
            section_key: "recommendation",
            title: "Recommendation",
            content:
              "File Suspicious Activity Report with FinCEN under 31 CFR 1020.320. Recommended SAR narrative characterisation: 'structuring to evade CTR reporting'. Freeze discretionary account access pending BSA officer review. INSUFFICIENT EVIDENCE to recommend account closure at this stage — no confirmed funds destination identified.",
            order_index: 3,
            approval_status: "pending",
            approved_by: null,
            approved_at: null,
          },
        ],
        created_by: "demo",
        created_at: "2026-04-02T09:30:00Z",
        updated_at: "2026-04-02T14:12:00Z",
      },
    ],
    evidence_links: [
      {
        id: "el-001",
        narrative_id: "narrative-001",
        organization_id: "demo-org",
        evidence_ref: "EVID-001",
        source_type: "investigation_step",
        step_id: "step-parse-001",
        screening_result_id: null,
        char_offset_start: null,
        char_offset_end: null,
        sentence_text: "Ahmad Al-Rashid KYC profile confirmed",
        created_at: "2026-04-02T09:30:00Z",
      },
      {
        id: "el-002",
        narrative_id: "narrative-001",
        organization_id: "demo-org",
        evidence_ref: "EVID-002",
        source_type: "investigation_step",
        step_id: "step-analyze-001",
        screening_result_id: null,
        char_offset_start: null,
        char_offset_end: null,
        sentence_text: "7 transactions: $8,200 / $9,400 / $9,800 / $9,100 / $8,750 / $9,600 / $9,600",
        created_at: "2026-04-02T09:30:00Z",
      },
      {
        id: "el-003",
        narrative_id: "narrative-001",
        organization_id: "demo-org",
        evidence_ref: "EVID-003",
        source_type: "investigation_step",
        step_id: "step-analyze-001",
        screening_result_id: null,
        char_offset_start: null,
        char_offset_end: null,
        sentence_text: "structuring_check: confidence=0.87, 7 deposits in band [8000, 10000)",
        created_at: "2026-04-02T09:30:00Z",
      },
    ],
  },
  "demo-case-002": {
    case: {
      id: "demo-case-002",
      organization_id: "demo-org",
      alert_id: "demo-alert-002",
      title: "Investigation: Wire Transfer Layering — Global Trade Corp Ltd",
      description: null,
      status: "open",
      assigned_to: null,
      created_by: "demo",
      created_at: "2026-04-02T11:30:00Z",
      updated_at: "2026-04-02T11:30:00Z",
    },
    investigation_steps: [],
    screening_results: [],
    narratives: [],
    evidence_links: [],
  },
  "demo-case-003": {
    case: {
      id: "demo-case-003",
      organization_id: "demo-org",
      alert_id: "demo-alert-003",
      title: "Investigation: Sanctions Match — Viktor Petrov",
      description: null,
      status: "open",
      assigned_to: null,
      created_by: "demo",
      created_at: "2026-04-03T08:05:00Z",
      updated_at: "2026-04-03T08:05:00Z",
    },
    investigation_steps: [],
    screening_results: [],
    narratives: [],
    evidence_links: [],
  },
};

// ---------------------------------------------------------------------------
// Helpers to parse titles
// ---------------------------------------------------------------------------

/** "Investigation: Cash Structuring — Ahmad Al-Rashid" → "Cash Structuring" */
export function parseAlertType(title: string): string {
  const match = title.match(/Investigation:\s*([^—]+)/);
  return match ? (match[1]?.trim() ?? title) : title;
}

/** "Investigation: Cash Structuring — Ahmad Al-Rashid" → "Ahmad Al-Rashid" */
export function parseCustomerName(title: string): string {
  const match = title.match(/—\s*(.+)$/);
  return match ? (match[1]?.trim() ?? "—") : "—";
}

/** Get severity label from risk score */
export function riskLabel(score: number): string {
  if (score >= 0.85) return "CRITICAL";
  if (score >= 0.65) return "HIGH";
  if (score >= 0.40) return "MEDIUM";
  return "LOW";
}

/** Get severity colour classes */
export function riskColors(score: number): string {
  if (score >= 0.85)
    return "bg-red-100 text-red-700 ring-1 ring-red-300";
  if (score >= 0.65)
    return "bg-orange-100 text-orange-700 ring-1 ring-orange-300";
  if (score >= 0.40)
    return "bg-yellow-100 text-yellow-700 ring-1 ring-yellow-300";
  return "bg-gray-100 text-gray-600 ring-1 ring-gray-300";
}

/** Map case status to display label + colour */
export function statusMeta(
  status: string,
): { label: string; classes: string } {
  switch (status) {
    case "open":
      return { label: "Pending", classes: "bg-gray-100 text-gray-600" };
    case "in_review":
      return { label: "In Review", classes: "bg-blue-100 text-blue-700" };
    case "escalated":
      return {
        label: "Escalated",
        classes: "bg-orange-100 text-orange-700",
      };
    case "closed":
      return { label: "Closed", classes: "bg-green-100 text-green-700" };
    default:
      return { label: status, classes: "bg-gray-100 text-gray-500" };
  }
}

/** Format ISO timestamp → "2 Apr 2026, 09:15" */
export function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
