// Auto-generated skeleton — replace with: pnpm --filter @argonis/db db:generate
// after connecting a Supabase project.

export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[];

// ---------------------------------------------------------------------------
// Enum types (mirrored from Postgres)
// ---------------------------------------------------------------------------
export type UserRole            = "admin" | "analyst" | "reviewer";
export type AlertStatus         = "new" | "reviewing" | "escalated" | "closed";
export type AlertSeverity       = "low" | "medium" | "high" | "critical";
export type CaseStatus          = "open" | "in_review" | "escalated" | "closed";
export type StepStatus          = "pending" | "running" | "completed" | "failed";
export type ScreeningStatus     = "pending" | "confirmed" | "dismissed";
export type NarrativeStatus     = "draft" | "in_review" | "approved" | "rejected";
export type ApprovalStatus      = "pending" | "approved" | "rejected";
export type EvidenceSourceType  = "investigation_step" | "screening_result" | "alert" | "external";
export type AuditAction         = "INSERT" | "UPDATE" | "DELETE";

// ---------------------------------------------------------------------------
// Row types
// ---------------------------------------------------------------------------
export interface Database {
  public: {
    Tables: {
      organizations: {
        Row: {
          id:         string;
          name:       string;
          slug:       string;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?:        string;
          name:       string;
          slug:       string;
          created_at?: string;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["organizations"]["Insert"]>;
      };

      users: {
        Row: {
          id:              string;
          organization_id: string;
          email:           string;
          full_name:       string | null;
          role:            UserRole;
          created_at:      string;
          updated_at:      string;
        };
        Insert: {
          id:              string;
          organization_id: string;
          email:           string;
          full_name?:      string | null;
          role?:           UserRole;
          created_at?:     string;
          updated_at?:     string;
        };
        Update: Partial<Database["public"]["Tables"]["users"]["Insert"]>;
      };

      alerts: {
        Row: {
          id:              string;
          organization_id: string;
          title:           string;
          description:     string | null;
          status:          AlertStatus;
          severity:        AlertSeverity;
          source:          string;
          raw_data:        Json | null;
          created_by:      string | null;
          created_at:      string;
          updated_at:      string;
        };
        Insert: {
          id?:             string;
          organization_id: string;
          title:           string;
          description?:    string | null;
          status?:         AlertStatus;
          severity?:       AlertSeverity;
          source:          string;
          raw_data?:       Json | null;
          created_by?:     string | null;
          created_at?:     string;
          updated_at?:     string;
        };
        Update: Partial<Database["public"]["Tables"]["alerts"]["Insert"]>;
      };

      cases: {
        Row: {
          id:              string;
          organization_id: string;
          alert_id:        string | null;
          title:           string;
          description:     string | null;
          status:          CaseStatus;
          assigned_to:     string | null;
          created_by:      string;
          created_at:      string;
          updated_at:      string;
        };
        Insert: {
          id?:             string;
          organization_id: string;
          alert_id?:       string | null;
          title:           string;
          description?:    string | null;
          status?:         CaseStatus;
          assigned_to?:    string | null;
          created_by:      string;
          created_at?:     string;
          updated_at?:     string;
        };
        Update: Partial<Database["public"]["Tables"]["cases"]["Insert"]>;
      };

      investigation_steps: {
        Row: {
          id:               string;
          organization_id:  string;
          case_id:          string;
          name:             string;
          description:      string | null;
          status:           StepStatus;
          source_data:      Json | null;
          confidence_score: number | null;
          created_by:       string | null;
          created_at:       string;
          updated_at:       string;
        };
        Insert: {
          id?:              string;
          organization_id:  string;
          case_id:          string;
          name:             string;
          description?:     string | null;
          status?:          StepStatus;
          source_data?:     Json | null;
          confidence_score?: number | null;
          created_by?:      string | null;
          created_at?:      string;
          updated_at?:      string;
        };
        Update: Partial<Database["public"]["Tables"]["investigation_steps"]["Insert"]>;
      };

      screening_results: {
        Row: {
          id:               string;
          organization_id:  string;
          case_id:          string;
          entity_name:      string;
          match_confidence: number;
          source_url:       string | null;
          match_data:       Json | null;
          status:           ScreeningStatus;
          reviewed_by:      string | null;
          reviewed_at:      string | null;
          created_at:       string;
          updated_at:       string;
        };
        Insert: {
          id?:              string;
          organization_id:  string;
          case_id:          string;
          entity_name:      string;
          match_confidence: number;
          source_url?:      string | null;
          match_data?:      Json | null;
          status?:          ScreeningStatus;
          reviewed_by?:     string | null;
          reviewed_at?:     string | null;
          created_at?:      string;
          updated_at?:      string;
        };
        Update: Partial<Database["public"]["Tables"]["screening_results"]["Insert"]>;
      };

      narratives: {
        Row: {
          id:              string;
          organization_id: string;
          case_id:         string;
          version:         number;
          title:           string;
          status:          NarrativeStatus;
          parent_id:       string | null;
          created_by:      string;
          created_at:      string;
          updated_at:      string;
        };
        Insert: {
          id?:             string;
          organization_id: string;
          case_id:         string;
          version?:        number;
          title:           string;
          status?:         NarrativeStatus;
          parent_id?:      string | null;
          created_by:      string;
          created_at?:     string;
          updated_at?:     string;
        };
        Update: Partial<Database["public"]["Tables"]["narratives"]["Insert"]>;
      };

      narrative_sections: {
        Row: {
          id:              string;
          organization_id: string;
          narrative_id:    string;
          section_key:     string;
          title:           string;
          content:         string;
          order_index:     number;
          approval_status: ApprovalStatus;
          approved_by:     string | null;
          approved_at:     string | null;
          created_at:      string;
          updated_at:      string;
        };
        Insert: {
          id?:              string;
          organization_id:  string;
          narrative_id:     string;
          section_key:      string;
          title:            string;
          content?:         string;
          order_index?:     number;
          approval_status?: ApprovalStatus;
          approved_by?:     string | null;
          approved_at?:     string | null;
          created_at?:      string;
          updated_at?:      string;
        };
        Update: Partial<Database["public"]["Tables"]["narrative_sections"]["Insert"]>;
      };

      evidence_links: {
        Row: {
          id:                    string;
          organization_id:       string;
          narrative_id:          string;
          section_id:            string;
          sentence_text:         string;
          char_offset_start:     number;
          char_offset_end:       number;
          source_type:           EvidenceSourceType;
          investigation_step_id: string | null;
          screening_result_id:   string | null;
          alert_id:              string | null;
          external_url:          string | null;
          external_title:        string | null;
          created_by:            string | null;
          created_at:            string;
        };
        Insert: {
          id?:                    string;
          organization_id:        string;
          narrative_id:           string;
          section_id:             string;
          sentence_text:          string;
          char_offset_start:      number;
          char_offset_end:        number;
          source_type:            EvidenceSourceType;
          investigation_step_id?: string | null;
          screening_result_id?:   string | null;
          alert_id?:              string | null;
          external_url?:          string | null;
          external_title?:        string | null;
          created_by?:            string | null;
          created_at?:            string;
        };
        // No Update — evidence_links are immutable (RLS blocks UPDATE)
        Update: never;
      };

      audit_log: {
        Row: {
          id:              string;
          organization_id: string | null;
          user_id:         string | null;
          action:          AuditAction;
          table_name:      string;
          record_id:       string;
          old_data:        Json | null;
          new_data:        Json | null;
          ip_address:      string | null;
          created_at:      string;
        };
        Insert: never; // written by triggers only
        Update: never; // append-only
      };
    };

    Views:   Record<string, never>;
    Functions: {
      auth_org_id: {
        Args:    Record<string, never>;
        Returns: string;
      };
    };
    Enums: {
      user_role:            UserRole;
      alert_status:         AlertStatus;
      alert_severity:       AlertSeverity;
      case_status:          CaseStatus;
      step_status:          StepStatus;
      screening_status:     ScreeningStatus;
      narrative_status:     NarrativeStatus;
      approval_status:      ApprovalStatus;
      evidence_source_type: EvidenceSourceType;
      audit_action:         AuditAction;
    };
  };
}
