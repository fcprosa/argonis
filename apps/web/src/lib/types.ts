// TypeScript types that mirror the FastAPI response schemas exactly.
// Never import from here in Server Components that run at build time —
// these are purely for client-side type safety.

export interface CaseSummary {
  id: string;
  organization_id: string;
  alert_id: string | null;
  title: string;
  description: string | null;
  status: "open" | "in_review" | "escalated" | "closed";
  assigned_to: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface InvestigationStep {
  id: string;
  case_id: string;
  organization_id: string;
  name: "parse" | "gather" | "screen" | "analyze" | "pipeline_error";
  description: string;
  status: "completed" | "completed_with_warnings" | "failed";
  source_data: Record<string, unknown> | null;
  confidence_score: number | null;
  created_by: string;
  created_at: string;
}

export interface ScreeningResult {
  id: string;
  case_id: string;
  organization_id: string;
  entity_name: string;
  match_confidence: number;
  source_url: string | null;
  match_data: {
    list_name: string;
    match_type: string;
    snippet: string;
  } | null;
  status: "pending" | "reviewed" | "dismissed";
  created_at: string;
}

export type SectionKey =
  | "subject_information"
  | "suspicious_activity_summary"
  | "detailed_narrative"
  | "supporting_evidence";

export interface NarrativeSection {
  id: string;
  section_key: SectionKey | (string & {});
  title: string;
  content: string;
  order_index: number;
  approval_status: "pending" | "approved" | "rejected";
  approved_by: string | null;
  approved_at: string | null;
}

export interface NarrativeRow {
  id: string;
  case_id: string;
  version: number;
  title: string;
  status: "draft" | "in_review" | "approved" | "rejected";
  narrative_sections: NarrativeSection[];
  is_partial_screening?: boolean;
  screening_gaps?: string[];
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface EvidenceLink {
  id: string;
  narrative_id: string;
  organization_id: string;
  evidence_ref: string;
  source_type: string;
  step_id: string | null;
  screening_result_id: string | null;
  char_offset_start: number | null;
  char_offset_end: number | null;
  sentence_text: string | null;
  created_at: string;
}

export interface CaseDetail {
  case: {
    id: string;
    organization_id: string;
    alert_id: string | null;
    title: string;
    description: string | null;
    status: string;
    assigned_to: string | null;
    created_by: string;
    created_at: string;
    updated_at: string;
  };
  investigation_steps: InvestigationStep[];
  screening_results: ScreeningResult[];
  narratives: NarrativeRow[];
  evidence_links: EvidenceLink[];
}

export interface NarrativeDetail {
  id: string;
  case_id: string;
  version: number;
  title: string;
  status: string;
  sections: NarrativeSection[];
  evidence_links: EvidenceLink[];
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface InvestigateResponse {
  case_id: string;
  alert_id: string;
  status: string;
  message: string;
}

export interface AlertImport {
  case_id?: string;
  customer_name: string;
  alert_type: string;
  risk_score?: number;
  status?: string;
  created_at?: string;
}

export interface BatchAlertsResponse {
  imported: number;
  case_ids: string[];
}
