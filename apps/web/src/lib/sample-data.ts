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
    risk_score: 0.87,
    recommended_action: "escalate",
  },
  {
    id: "demo-case-002",
    organization_id: "demo-org",
    alert_id: "demo-alert-002",
    title: "Investigation: Wire Transfer Layering — Global Trade Corp Ltd",
    description: "Investigation complete. Enhanced due diligence recommended.",
    status: "in_review",
    assigned_to: null,
    created_by: "demo",
    created_at: "2026-04-02T11:30:00Z",
    updated_at: "2026-04-02T14:55:00Z",
    risk_score: 0.61,
    recommended_action: "investigate",
  },
  {
    id: "demo-case-003",
    organization_id: "demo-org",
    alert_id: "demo-alert-003",
    title: "Investigation: Sanctions Match — Viktor Petrov",
    description: "OFAC SDN confirmed. SAR filing recommended. Case escalated.",
    status: "escalated",
    assigned_to: null,
    created_by: "demo",
    created_at: "2026-04-03T08:05:00Z",
    updated_at: "2026-04-03T10:22:00Z",
    risk_score: 0.94,
    recommended_action: "file_sar",
  },
];

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
            section_key: "subject_information",
            title: "Subject Information",
            content:
              "Ahmad Al-Rashid (DOB: 14 March 1978, nationality: Iraqi) holds a personal checking account (****4821) opened 12 January 2024 [EVID-001]. KYC documentation lists occupation as 'import consultant' with declared annual income of USD 45,000. Account activity over the preceding 90 days prior to this alert shows an average monthly cash deposit of USD 3,200 — the March 2026 deposits represent a 615% deviation from established baseline [EVID-004].",
            order_index: 0,
            approval_status: "approved",
            approved_by: "reviewer@demo.com",
            approved_at: "2026-04-02T14:10:00Z",
          },
          {
            id: "sec-002",
            section_key: "suspicious_activity_summary",
            title: "Suspicious Activity Summary",
            content:
              "Between 15 March and 28 March 2026, Ahmad Al-Rashid [EVID-001] conducted seven cash deposits totalling USD 68,450 across three branch locations. Each individual deposit fell below the USD 10,000 CTR threshold, ranging from USD 8,200 to USD 9,800 [EVID-002]. The deposits exhibit a statistically improbable clustering in the USD 9,000–9,900 band (confidence: 0.87), consistent with deliberate structuring to avoid Currency Transaction Report filing requirements under 31 U.S.C. § 5324 [EVID-003].",
            order_index: 1,
            approval_status: "pending",
            approved_by: null,
            approved_at: null,
          },
          {
            id: "sec-003",
            section_key: "detailed_narrative",
            title: "Detailed Narrative",
            content:
              "Structuring pattern confirmed across seven transactions [EVID-002]. Velocity anomaly detected: 7 deposits in 13 days versus historical baseline of 1.2 deposits per month [EVID-005]. Geographic dispersion across 3 branches (Downtown, Midtown, Airport) suggests deliberate avoidance of teller familiarity [EVID-006]. INSUFFICIENT EVIDENCE to confirm beneficial ownership of Al-Rashid Trading LLC — further KYC refresh required before this entity can be included in the SAR filing.",
            order_index: 2,
            approval_status: "rejected",
            approved_by: "reviewer@demo.com",
            approved_at: "2026-04-02T14:12:00Z",
          },
          {
            id: "sec-004",
            section_key: "supporting_evidence",
            title: "Supporting Evidence",
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
  // -------------------------------------------------------------------------
  // CASE-002: Wire Transfer Layering — Global Trade Corp Ltd
  // -------------------------------------------------------------------------
  "demo-case-002": {
    case: {
      id: "demo-case-002",
      organization_id: "demo-org",
      alert_id: "demo-alert-002",
      title: "Investigation: Wire Transfer Layering — Global Trade Corp Ltd",
      description: "Investigation complete. Enhanced due diligence recommended.",
      status: "in_review",
      assigned_to: null,
      created_by: "demo",
      created_at: "2026-04-02T11:30:00Z",
      updated_at: "2026-04-02T14:55:00Z",
    },
    investigation_steps: [
      {
        id: "step-002-parse",
        case_id: "demo-case-002",
        organization_id: "demo-org",
        name: "parse",
        description: "Parsed alert: 12 wire transfers, 3 entities, 4 jurisdictions",
        status: "completed",
        source_data: {
          alert_id: "AML-2026-00312",
          alert_type: "Wire Transfer Layering",
          account_holder: "Global Trade Corp Ltd",
          account_number: "****7703",
          total_amount_usd: 4200000,
          transaction_count: 12,
          jurisdictions: ["UAE", "Singapore", "Hong Kong", "UK"],
        },
        confidence_score: 1.0,
        created_by: "demo",
        created_at: "2026-04-02T11:32:00Z",
      },
      {
        id: "step-002-gather",
        case_id: "demo-case-002",
        organization_id: "demo-org",
        name: "gather",
        description: "Gathered KYC, corporate registry, 6 months transaction history",
        status: "completed",
        source_data: {
          kyc_profiles: 3,
          corporate_entities: 2,
          correspondent_banks: 4,
          transaction_history_days: 180,
          ubo_confirmed: false,
        },
        confidence_score: 0.95,
        created_by: "demo",
        created_at: "2026-04-02T11:34:00Z",
      },
      {
        id: "step-002-screen",
        case_id: "demo-case-002",
        organization_id: "demo-org",
        name: "screen",
        description: "Screened 3 entities — 0 OFAC hits, 1 adverse media flag",
        status: "completed",
        source_data: {
          entity_names: [
            "Global Trade Corp Ltd",
            "GTC Holdings FZE",
            "Chen Wei-Lin (Director)",
          ],
          ofac_hits: 0,
          adverse_media_flags: 1,
        },
        confidence_score: 1.0,
        created_by: "demo",
        created_at: "2026-04-02T11:38:00Z",
      },
      {
        id: "step-002-analyze",
        case_id: "demo-case-002",
        organization_id: "demo-org",
        name: "analyze",
        description: "Risk: ENHANCED_DUE_DILIGENCE (score 0.610)",
        status: "completed",
        source_data: {
          overall_risk_score: 0.61,
          recommended_action: "ENHANCED_DUE_DILIGENCE",
          patterns_detected: ["layering", "round_tripping", "jurisdiction_hopping"],
        },
        confidence_score: 0.61,
        created_by: "demo",
        created_at: "2026-04-02T11:44:00Z",
      },
    ],
    screening_results: [
      {
        id: "screen-002-001",
        case_id: "demo-case-002",
        organization_id: "demo-org",
        entity_name: "Global Trade Corp Ltd",
        match_confidence: 0.74,
        source_url: null,
        match_data: {
          list_name: "Adverse Media — Commercial DB",
          match_type: "name_news_association",
          snippet:
            "Global Trade Corp Ltd named in Singapore MAS enforcement action (2024) relating to undisclosed beneficial ownership and suspected trade misinvoicing across UAE free-zone entities.",
        },
        status: "pending",
        created_at: "2026-04-02T11:38:00Z",
      },
    ],
    narratives: [
      {
        id: "narrative-002",
        case_id: "demo-case-002",
        version: 1,
        title: "EDD Narrative — Global Trade Corp Ltd — Wire Transfer Layering",
        status: "in_review",
        narrative_sections: [
          {
            id: "sec-002-01",
            section_key: "subject_information",
            title: "Subject Information",
            content:
              "Global Trade Corp Ltd is a UK-registered trading company (Companies House no. 09847321) incorporated in 2019 [EVID-001]. The company lists two directors: Chen Wei-Lin (Singaporean national) and a nominee director service. Ultimate beneficial ownership (UBO) has not been confirmed — submitted UBO documentation references a Cayman Islands holding vehicle for which no registry records are publicly available [EVID-005]. GTC holds a sterling current account (****7703) opened 14 June 2022. Prior 12 months showed average monthly turnover of GBP 180,000; the disputed period represents a 1,033% deviation from baseline [EVID-002].",
            order_index: 0,
            approval_status: "approved",
            approved_by: "reviewer@demo.com",
            approved_at: "2026-04-02T16:10:00Z",
          },
          {
            id: "sec-002-02",
            section_key: "suspicious_activity_summary",
            title: "Suspicious Activity Summary",
            content:
              "Between 15 February and 31 March 2026, Global Trade Corp Ltd (GTC) [EVID-001] executed twelve wire transfers totalling USD 4,200,000 across correspondent banks in the UAE, Singapore, Hong Kong, and the United Kingdom [EVID-002]. The transfers exhibit a layering pattern consistent with trade-based money laundering: each leg involved a different counterparty bank and nominal trade justification, yet underlying invoices could not be independently verified [EVID-003]. An adverse media flag links GTC to a 2024 Singapore MAS enforcement action concerning undisclosed beneficial ownership [EVID-004]. Overall risk score: 0.61 (HIGH). Recommended action: Enhanced Due Diligence with 60-day monitoring.",
            order_index: 1,
            approval_status: "pending",
            approved_by: null,
            approved_at: null,
          },
          {
            id: "sec-002-03",
            section_key: "detailed_narrative",
            title: "Detailed Narrative",
            content:
              "Twelve outbound wires between 15 Feb and 31 Mar 2026 [EVID-002]. Round-trip pattern confirmed: USD 1.4M originated from a UAE free-zone entity (GTC Holdings FZE), transited via Singapore and Hong Kong shell accounts, and re-entered the UK account within 14 days under trade description 'commodity settlement' [EVID-003]. Invoice amounts do not correspond to prevailing commodity prices for the stated goods (aluminium ingots) by a margin of 340%. Jurisdiction-hopping across four FATF-monitored territories without evident commercial rationale. INSUFFICIENT EVIDENCE to confirm the identity of the Singapore transit account beneficial owners — subpoena or MLA request required.",
            order_index: 2,
            approval_status: "approved",
            approved_by: "reviewer@demo.com",
            approved_at: "2026-04-02T16:12:00Z",
          },
          {
            id: "sec-002-04",
            section_key: "supporting_evidence",
            title: "Supporting Evidence",
            content:
              "Apply Enhanced Due Diligence (EDD) measures under JMLSG Guidance Part I, Chapter 5. Require certified UBO documentation within 21 days; suspend international wire facilities pending receipt. Initiate 60-day transaction monitoring uplift. File Defence Against Money Laundering (DAML) consent request with the National Crime Agency (NCA) before processing further international transfers. INSUFFICIENT EVIDENCE to recommend SAR filing at this stage — adverse media hit is investigative, not confirmatory; EDD outcome should determine whether a SAR is warranted.",
            order_index: 3,
            approval_status: "pending",
            approved_by: null,
            approved_at: null,
          },
        ],
        created_by: "demo",
        created_at: "2026-04-02T11:50:00Z",
        updated_at: "2026-04-02T16:12:00Z",
      },
    ],
    evidence_links: [
      {
        id: "el-002-01",
        narrative_id: "narrative-002",
        organization_id: "demo-org",
        evidence_ref: "EVID-001",
        source_type: "investigation_step",
        step_id: "step-002-parse",
        screening_result_id: null,
        char_offset_start: null,
        char_offset_end: null,
        sentence_text: "Global Trade Corp Ltd — KYC profile + Companies House record confirmed",
        created_at: "2026-04-02T11:50:00Z",
      },
      {
        id: "el-002-02",
        narrative_id: "narrative-002",
        organization_id: "demo-org",
        evidence_ref: "EVID-002",
        source_type: "investigation_step",
        step_id: "step-002-analyze",
        screening_result_id: null,
        char_offset_start: null,
        char_offset_end: null,
        sentence_text: "12 wire transfers, total USD 4,200,000, 15 Feb–31 Mar 2026",
        created_at: "2026-04-02T11:50:00Z",
      },
      {
        id: "el-002-03",
        narrative_id: "narrative-002",
        organization_id: "demo-org",
        evidence_ref: "EVID-003",
        source_type: "investigation_step",
        step_id: "step-002-analyze",
        screening_result_id: null,
        char_offset_start: null,
        char_offset_end: null,
        sentence_text: "layering_check: round_trip confirmed, invoice_discrepancy=340%",
        created_at: "2026-04-02T11:50:00Z",
      },
      {
        id: "el-002-04",
        narrative_id: "narrative-002",
        organization_id: "demo-org",
        evidence_ref: "EVID-004",
        source_type: "screening_result",
        step_id: null,
        screening_result_id: "screen-002-001",
        char_offset_start: null,
        char_offset_end: null,
        sentence_text: "Adverse media: Singapore MAS enforcement action 2024",
        created_at: "2026-04-02T11:50:00Z",
      },
      {
        id: "el-002-05",
        narrative_id: "narrative-002",
        organization_id: "demo-org",
        evidence_ref: "EVID-005",
        source_type: "investigation_step",
        step_id: "step-002-gather",
        screening_result_id: null,
        char_offset_start: null,
        char_offset_end: null,
        sentence_text: "UBO: Cayman Islands vehicle — no public registry records found",
        created_at: "2026-04-02T11:50:00Z",
      },
    ],
  },

  // -------------------------------------------------------------------------
  // CASE-003: Sanctions Match — Viktor Petrov
  // -------------------------------------------------------------------------
  "demo-case-003": {
    case: {
      id: "demo-case-003",
      organization_id: "demo-org",
      alert_id: "demo-alert-003",
      title: "Investigation: Sanctions Match — Viktor Petrov",
      description: "OFAC SDN confirmed. SAR filing recommended. Case escalated.",
      status: "escalated",
      assigned_to: null,
      created_by: "demo",
      created_at: "2026-04-03T08:05:00Z",
      updated_at: "2026-04-03T10:22:00Z",
    },
    investigation_steps: [
      {
        id: "step-003-parse",
        case_id: "demo-case-003",
        organization_id: "demo-org",
        name: "parse",
        description: "Parsed alert: 8 transactions, USD 890,000, Russian passport holder",
        status: "completed",
        source_data: {
          alert_id: "AML-2026-00394",
          alert_type: "Sanctions Name Match",
          account_holder: "Viktor Petrov",
          account_number: "****2291",
          currency: "USD",
          total_amount_usd: 890000,
          transaction_count: 8,
          nationality: "RU",
          passport_number: "****4417",
        },
        confidence_score: 1.0,
        created_by: "demo",
        created_at: "2026-04-03T08:07:00Z",
      },
      {
        id: "step-003-gather",
        case_id: "demo-case-003",
        organization_id: "demo-org",
        name: "gather",
        description: "Gathered KYC, account history 180 days, dormancy analysis",
        status: "completed",
        source_data: {
          kyc_profiles: 1,
          account_history_days: 180,
          dormancy_period_days: 142,
          sudden_activity_usd: 890000,
          pep_status: false,
        },
        confidence_score: 1.0,
        created_by: "demo",
        created_at: "2026-04-03T08:09:00Z",
      },
      {
        id: "step-003-screen",
        case_id: "demo-case-003",
        organization_id: "demo-org",
        name: "screen",
        description: "Screened 2 entities — 1 OFAC SDN hit (96% confidence)",
        status: "completed",
        source_data: {
          entity_names: ["Viktor Petrov", "Viktor A. Petrov"],
          ofac_hits: 1,
          adverse_media_flags: 2,
          match_confidence: 0.96,
        },
        confidence_score: 0.96,
        created_by: "demo",
        created_at: "2026-04-03T08:13:00Z",
      },
      {
        id: "step-003-analyze",
        case_id: "demo-case-003",
        organization_id: "demo-org",
        name: "analyze",
        description: "Risk: IMMEDIATE_SAR_FILING (score 0.940) — sanctions confirmed",
        status: "completed",
        source_data: {
          overall_risk_score: 0.94,
          recommended_action: "IMMEDIATE_SAR_FILING",
          patterns_detected: ["sanctions_match", "dormant_account_reactivation", "high_velocity"],
          ofac_program: "RUSSIA-EO14024",
        },
        confidence_score: 0.94,
        created_by: "demo",
        created_at: "2026-04-03T08:18:00Z",
      },
    ],
    screening_results: [
      {
        id: "screen-003-001",
        case_id: "demo-case-003",
        organization_id: "demo-org",
        entity_name: "Viktor Petrov",
        match_confidence: 0.96,
        source_url: "https://sanctionssearch.ofac.treas.gov/",
        match_data: {
          list_name: "OFAC SDN List",
          match_type: "fuzzy_name_dob",
          snippet:
            "PETROV, Viktor Alekseyevich; DOB 03 Sep 1971; POB Yekaterinburg, Russia; nationality RUS; Program: RUSSIA-EO14024; listed 22 Feb 2022.",
        },
        status: "pending",
        created_at: "2026-04-03T08:13:00Z",
      },
    ],
    narratives: [
      {
        id: "narrative-003",
        case_id: "demo-case-003",
        version: 1,
        title: "SAR Narrative — Viktor Petrov — OFAC Sanctions Match",
        status: "in_review",
        narrative_sections: [
          {
            id: "sec-003-01",
            section_key: "subject_information",
            title: "Subject Information",
            content:
              "Viktor Alekseyevich Petrov (DOB: 3 Sep 1971, Yekaterinburg, Russia) [EVID-001] holds account ****2291 opened 4 November 2021 under Russian passport ****4417. KYC documentation lists occupation as 'energy consultant' with declared annual income of USD 120,000. The account recorded no activity between 14 September 2025 and 4 March 2026 (142-day dormancy period) [EVID-003]. No PEP designation was flagged at onboarding; however, the OFAC SDN listing post-dates account opening and was not captured in the initial screening cycle [EVID-002].",
            order_index: 0,
            approval_status: "approved",
            approved_by: "reviewer@demo.com",
            approved_at: "2026-04-03T09:45:00Z",
          },
          {
            id: "sec-003-02",
            section_key: "suspicious_activity_summary",
            title: "Suspicious Activity Summary",
            content:
              "On 3 April 2026, an automated name-screening alert flagged Viktor Petrov (DOB: 3 September 1971, Russian national) [EVID-001] as a potential match against the OFAC Specially Designated Nationals (SDN) List under Executive Order 14024 (Russia-related sanctions). Screening analysis returned a 96% confidence match [EVID-002]. The subject holds a USD current account (****2291) that was dormant for 142 days before eight inbound transfers totalling USD 890,000 were received between 1 and 30 March 2026 [EVID-003]. The combination of confirmed OFAC SDN match, sudden dormant-account reactivation, and high-velocity inflows constitutes a critical risk event requiring immediate regulatory action.",
            order_index: 1,
            approval_status: "approved",
            approved_by: "reviewer@demo.com",
            approved_at: "2026-04-03T09:47:00Z",
          },
          {
            id: "sec-003-03",
            section_key: "detailed_narrative",
            title: "Detailed Narrative",
            content:
              "Eight inbound wire transfers received 1–30 March 2026 [EVID-003]: USD 95,000 / 120,000 / 85,000 / 200,000 / 110,000 / 75,000 / 105,000 / 100,000. All originate from a single counterparty SWIFT code (ROSB RU MM — Rosbank Moscow), a sanctioned correspondent institution under OFAC RUSSIA-EO14024 [EVID-004]. Velocity anomaly: 8 transactions in 30 days versus zero transactions in preceding 142 days. No outbound activity observed — funds remain on deposit. INSUFFICIENT EVIDENCE to determine the ultimate beneficial source of funds beyond the Rosbank counterparty at this stage.",
            order_index: 2,
            approval_status: "pending",
            approved_by: null,
            approved_at: null,
          },
          {
            id: "sec-003-04",
            section_key: "supporting_evidence",
            title: "Supporting Evidence",
            content:
              "Immediate actions required: (1) Freeze account ****2291 under OFAC blocking obligations — funds received from a sanctioned counterparty must be blocked and reported within 10 business days per 31 CFR § 501.603. (2) File Suspicious Activity Report with FinCEN citing OFAC SDN match + sanctions-linked wire transfers. (3) File OFAC blocking report via OFAC's e-licensing system. (4) Escalate to BSA/OFAC Compliance Officer for board-level notification. (5) Do NOT notify the customer — tipping-off prohibition applies under 31 U.S.C. § 5318(g)(2).",
            order_index: 3,
            approval_status: "pending",
            approved_by: null,
            approved_at: null,
          },
        ],
        created_by: "demo",
        created_at: "2026-04-03T08:25:00Z",
        updated_at: "2026-04-03T09:47:00Z",
      },
    ],
    evidence_links: [
      {
        id: "el-003-01",
        narrative_id: "narrative-003",
        organization_id: "demo-org",
        evidence_ref: "EVID-001",
        source_type: "investigation_step",
        step_id: "step-003-parse",
        screening_result_id: null,
        char_offset_start: null,
        char_offset_end: null,
        sentence_text: "Viktor Petrov — DOB 3 Sep 1971, passport ****4417, Russian national",
        created_at: "2026-04-03T08:25:00Z",
      },
      {
        id: "el-003-02",
        narrative_id: "narrative-003",
        organization_id: "demo-org",
        evidence_ref: "EVID-002",
        source_type: "screening_result",
        step_id: null,
        screening_result_id: "screen-003-001",
        char_offset_start: null,
        char_offset_end: null,
        sentence_text: "OFAC SDN match: PETROV, Viktor Alekseyevich — confidence 96% — RUSSIA-EO14024",
        created_at: "2026-04-03T08:25:00Z",
      },
      {
        id: "el-003-03",
        narrative_id: "narrative-003",
        organization_id: "demo-org",
        evidence_ref: "EVID-003",
        source_type: "investigation_step",
        step_id: "step-003-analyze",
        screening_result_id: null,
        char_offset_start: null,
        char_offset_end: null,
        sentence_text: "8 transfers USD 890,000 in 30 days; 142-day dormancy prior",
        created_at: "2026-04-03T08:25:00Z",
      },
      {
        id: "el-003-04",
        narrative_id: "narrative-003",
        organization_id: "demo-org",
        evidence_ref: "EVID-004",
        source_type: "investigation_step",
        step_id: "step-003-screen",
        screening_result_id: null,
        char_offset_start: null,
        char_offset_end: null,
        sentence_text: "Counterparty SWIFT: ROSB RU MM (Rosbank Moscow) — sanctioned under EO14024",
        created_at: "2026-04-03T08:25:00Z",
      },
    ],
  },
};

// ---------------------------------------------------------------------------
// Demo pipeline step definitions (for animated investigation in demo mode)
// ---------------------------------------------------------------------------

export interface DemoPipelineStep {
  key: string;
  label: string;
  detail: string;
  durationMs: number;
}

export const DEMO_PIPELINES: Record<string, DemoPipelineStep[]> = {
  "demo-case-001": [
    { key: "parse",   label: "PARSE",   detail: "Alert parsed — AML-2026-00147 · Cash Structuring · 47 transactions extracted", durationMs: 800 },
    { key: "gather",  label: "GATHER",  detail: "KYC retrieved · 47 transactions loaded · 6 branch locations identified · 90-day history", durationMs: 1700 },
    { key: "screen",  label: "SCREEN",  detail: "OFAC SDN: Clear · OpenSanctions: Clear · PEP: Clear · Adverse Media: 0 hits", durationMs: 2000 },
    { key: "analyze", label: "ANALYZE", detail: "Structuring detected (87% confidence) · Velocity anomaly +615% vs baseline · Branch dispersion flagged", durationMs: 1800 },
    { key: "narrate", label: "NARRATE", detail: "Narrative generated — 4 sections · 892 words · all claims anchored to evidence", durationMs: 3200 },
  ],
  "demo-case-002": [
    { key: "parse",   label: "PARSE",   detail: "Alert parsed — AML-2026-00312 · Wire Transfer Layering · 23 inbound + 19 outbound wires", durationMs: 800 },
    { key: "gather",  label: "GATHER",  detail: "3 entities profiled · 180-day history · UBO unconfirmed (Cayman vehicle) · 4 correspondent banks", durationMs: 1700 },
    { key: "screen",  label: "SCREEN",  detail: "OFAC SDN: Clear · OpenSanctions: Clear · Adverse Media: 1 hit (MAS enforcement action 2024)", durationMs: 2100 },
    { key: "analyze", label: "ANALYZE", detail: "Layering detected (61% confidence) · Round-trip pattern confirmed · Invoice discrepancy 340%", durationMs: 1800 },
    { key: "narrate", label: "NARRATE", detail: "EDD narrative generated — 4 sections · 1,024 words · DAML consent request recommended", durationMs: 3400 },
  ],
  "demo-case-003": [
    { key: "parse",   label: "PARSE",   detail: "Alert parsed — AML-2026-00394 · Sanctions Name Match · Russian national · 8 transactions · USD 890,000", durationMs: 600 },
    { key: "gather",  label: "GATHER",  detail: "KYC loaded · 142-day dormancy confirmed · USD 890,000 sudden inflow from Rosbank Moscow", durationMs: 1400 },
    { key: "screen",  label: "SCREEN",  detail: "OFAC SDN: HIT 96% — PETROV, Viktor Alekseyevich — EO14024 · Rosbank counterparty sanctioned", durationMs: 1800 },
    { key: "analyze", label: "ANALYZE", detail: "Sanctions match confirmed (94% confidence) · Dormant account reactivation · IMMEDIATE SAR FILING", durationMs: 1600 },
    { key: "narrate", label: "NARRATE", detail: "SAR narrative generated — 4 sections · 978 words · Account freeze + OFAC blocking report required", durationMs: 2800 },
  ],
};

// ---------------------------------------------------------------------------
// Full screening panel data (includes Clear results, not just hits)
// ---------------------------------------------------------------------------

export interface FullScreeningResult {
  id: string;
  list_name: string;
  status: "clear" | "potential_match" | "hit";
  match_confidence: number;
  entity_name: string;
  snippet: string;
  source_url: string | null;
}

export const DEMO_FULL_SCREENING: Record<string, FullScreeningResult[]> = {
  "demo-case-001": [
    { id: "fsr-001-01", list_name: "OFAC SDN List",           status: "clear", match_confidence: 0,    entity_name: "Ahmad Al-Rashid",       snippet: "No match found in OFAC Specially Designated Nationals and Blocked Persons list.",     source_url: "https://sanctionssearch.ofac.treas.gov/" },
    { id: "fsr-001-02", list_name: "OpenSanctions",           status: "clear", match_confidence: 0,    entity_name: "Ahmad Al-Rashid",       snippet: "No match found across UN, EU, UK, and 40+ national sanctions lists.",               source_url: null },
    { id: "fsr-001-03", list_name: "PEP Database",            status: "clear", match_confidence: 0,    entity_name: "Ahmad Al-Rashid",       snippet: "Subject is not a Politically Exposed Person (PEP). No government or senior official role identified.", source_url: null },
    { id: "fsr-001-04", list_name: "Adverse Media",           status: "clear", match_confidence: 0,    entity_name: "Ahmad Al-Rashid",       snippet: "0 relevant adverse media results. Queries: financial crime, sanctions, regulatory action.",           source_url: null },
  ],
  "demo-case-002": [
    { id: "fsr-002-01", list_name: "OFAC SDN List",           status: "clear",          match_confidence: 0,    entity_name: "Global Trade Corp Ltd",    snippet: "No match found for entity name against OFAC SDN list.",                        source_url: "https://sanctionssearch.ofac.treas.gov/" },
    { id: "fsr-002-02", list_name: "OpenSanctions",           status: "clear",          match_confidence: 0,    entity_name: "Global Trade Corp Ltd",    snippet: "No match found across UN, EU, UK, and 40+ national sanctions lists.",         source_url: null },
    { id: "fsr-002-03", list_name: "OFAC SDN List — Director", status: "potential_match", match_confidence: 0.72, entity_name: "Chen Wei-Lin (Director)", snippet: "CHEN, Wei-Lin — DOB circa 1968 — Singapore national. 72% fuzzy name match. Below 85% confirmation threshold. Flagged for analyst review.", source_url: "https://sanctionssearch.ofac.treas.gov/" },
    { id: "fsr-002-04", list_name: "Adverse Media",           status: "hit",            match_confidence: 0.74, entity_name: "Global Trade Corp Ltd",    snippet: "Singapore MAS enforcement action (2024) — undisclosed beneficial ownership, suspected trade misinvoicing across UAE free-zone entities.", source_url: null },
  ],
  "demo-case-003": [
    { id: "fsr-003-01", list_name: "OFAC SDN List",    status: "hit",            match_confidence: 0.96, entity_name: "Viktor Petrov", snippet: "PETROV, Viktor Alekseyevich — DOB 03 Sep 1971, Yekaterinburg, Russia — Program: RUSSIA-EO14024 — designated 22 Feb 2022.",              source_url: "https://sanctionssearch.ofac.treas.gov/" },
    { id: "fsr-003-02", list_name: "OpenSanctions",    status: "hit",            match_confidence: 0.94, entity_name: "Viktor Petrov", snippet: "Viktor A. Petrov — Russian Federation — OFAC, EU Council, UKFCO concurrent designation. Energy sector sanctions.",                      source_url: null },
    { id: "fsr-003-03", list_name: "Adverse Media",    status: "hit",            match_confidence: 0.88, entity_name: "Viktor Petrov", snippet: "Multiple media reports (Reuters, FT, Bloomberg): sanctioned Russian national, asset freeze across EU and US jurisdictions, 2022 designation.", source_url: null },
    { id: "fsr-003-04", list_name: "PEP Database",     status: "potential_match", match_confidence: 0.65, entity_name: "Viktor Petrov", snippet: "Former board member of state energy company — elevated PEP classification. Secondary screening recommended.",                           source_url: null },
  ],
};

// ---------------------------------------------------------------------------
// Audit trail entries per case
// ---------------------------------------------------------------------------

export interface AuditEntry {
  id: string;
  timestamp: string;
  actor: string;
  action: string;
  detail: string;
  evidence_id?: string;
}

export const DEMO_AUDIT_TRAILS: Record<string, AuditEntry[]> = {
  "demo-case-001": [
    { id: "aud-001-01", timestamp: "2026-04-02T09:15:00Z", actor: "System",              action: "Case created",                       detail: "Alert AML-2026-00147 ingested via real-time transaction monitoring. Cash structuring trigger threshold breached." },
    { id: "aud-001-02", timestamp: "2026-04-02T09:16:45Z", actor: "AI Agent",            action: "Step 1 PARSE — complete (0.8s)",      detail: "Alert parsed into structured schema. 47 transactions extracted. Currency: GBP. Reporting threshold: £10,000." },
    { id: "aud-001-03", timestamp: "2026-04-02T09:18:12Z", actor: "AI Agent",            action: "Step 2 GATHER — complete (1.7s)",     detail: "KYC data retrieved. 47 cash deposits loaded. 6 branch locations identified. 90-day transaction history compiled." },
    { id: "aud-001-04", timestamp: "2026-04-02T09:22:05Z", actor: "AI Agent",            action: "Step 3 SCREEN — complete (2.0s)",     detail: "OFAC SDN: Clear · OpenSanctions: Clear · PEP: Clear · Adverse Media: 0 hits. 2 entities screened." },
    { id: "aud-001-05", timestamp: "2026-04-02T09:25:33Z", actor: "AI Agent",            action: "Step 4 ANALYZE — complete (1.8s)",   detail: "Structuring pattern detected (0.87 confidence). Velocity anomaly: +615% vs 90-day baseline. Branch dispersion across 6 locations.", evidence_id: "EVID-003" },
    { id: "aud-001-06", timestamp: "2026-04-02T09:30:18Z", actor: "AI Agent",            action: "Step 5 NARRATE — complete (3.2s)",   detail: "SAR narrative generated — 4 sections, 892 words. All factual claims anchored to verified evidence sources." },
    { id: "aud-001-07", timestamp: "2026-04-02T14:10:44Z", actor: "analyst@argonis.ai",  action: "Section approved — Executive Summary", detail: "Approved without changes.", evidence_id: "EVID-001" },
    { id: "aud-001-08", timestamp: "2026-04-02T14:12:07Z", actor: "analyst@argonis.ai",  action: "Section flagged — Transaction Analysis", detail: "Flagged: UBO of Al-Rashid Trading LLC unconfirmed. KYC refresh required before entity can be named in SAR." },
  ],
  "demo-case-002": [
    { id: "aud-002-01", timestamp: "2026-04-02T11:30:00Z", actor: "System",              action: "Case created",                       detail: "Alert AML-2026-00312 ingested. Wire transfer layering trigger — 23 inbound, 19 outbound within 48 hours." },
    { id: "aud-002-02", timestamp: "2026-04-02T11:32:14Z", actor: "AI Agent",            action: "Step 1 PARSE — complete (0.8s)",      detail: "Alert parsed. 23 inbound wires, 19 outbound wires, 8 jurisdictions, €2.1M total volume." },
    { id: "aud-002-03", timestamp: "2026-04-02T11:34:45Z", actor: "AI Agent",            action: "Step 2 GATHER — complete (1.7s)",     detail: "3 entities profiled (GTC Ltd, GTC Holdings FZE, Chen Wei-Lin). UBO unconfirmed — Cayman Islands holding vehicle, no public registry." },
    { id: "aud-002-04", timestamp: "2026-04-02T11:38:22Z", actor: "AI Agent",            action: "Step 3 SCREEN — complete (2.1s)",     detail: "OFAC SDN: Clear · OpenSanctions: Clear · Director partial match: 72% (below threshold) · Adverse Media: 1 hit (MAS 2024)." },
    { id: "aud-002-05", timestamp: "2026-04-02T11:44:08Z", actor: "AI Agent",            action: "Step 4 ANALYZE — complete (1.8s)",   detail: "Layering confirmed (0.61 confidence). Round-trip funds: UAE → Singapore → Hong Kong → UK under 'commodity settlement'. Invoice discrepancy: 340%.", evidence_id: "EVID-003" },
    { id: "aud-002-06", timestamp: "2026-04-02T11:50:33Z", actor: "AI Agent",            action: "Step 5 NARRATE — complete (3.4s)",   detail: "EDD narrative generated — 4 sections, 1,024 words. DAML consent request recommended. SAR deferred pending EDD outcome." },
    { id: "aud-002-07", timestamp: "2026-04-02T16:10:19Z", actor: "analyst@argonis.ai",  action: "Section approved — Executive Summary",    detail: "Approved — overall risk characterisation and MAS reference verified." },
    { id: "aud-002-08", timestamp: "2026-04-02T16:12:41Z", actor: "analyst@argonis.ai",  action: "Section approved — Transaction Analysis", detail: "Approved — DAML referral language and NCA process steps verified against current guidance." },
  ],
  "demo-case-003": [
    { id: "aud-003-01", timestamp: "2026-04-03T08:05:00Z", actor: "System",              action: "Case created",                         detail: "Alert AML-2026-00394 ingested. OFAC name-screening alert — automatic case creation triggered." },
    { id: "aud-003-02", timestamp: "2026-04-03T08:07:09Z", actor: "AI Agent",            action: "Step 1 PARSE — complete (0.6s)",        detail: "Alert parsed. Viktor Petrov, Russian national, passport ****4417. 8 transactions, USD 890,000, account ****2291." },
    { id: "aud-003-03", timestamp: "2026-04-03T08:09:22Z", actor: "AI Agent",            action: "Step 2 GATHER — complete (1.4s)",       detail: "KYC loaded. 142-day account dormancy confirmed (14 Sep 2025 – 4 Mar 2026). USD 890,000 sudden inflow from Rosbank Moscow." },
    { id: "aud-003-04", timestamp: "2026-04-03T08:13:47Z", actor: "AI Agent",            action: "Step 3 SCREEN — CRITICAL HIT (1.8s)",   detail: "OFAC SDN HIT: PETROV, Viktor Alekseyevich — confidence 96% — Program: RUSSIA-EO14024 — designated 22 Feb 2022. Counterparty ROSB RU MM (Rosbank) also sanctioned.", evidence_id: "EVID-002" },
    { id: "aud-003-05", timestamp: "2026-04-03T08:18:33Z", actor: "AI Agent",            action: "Step 4 ANALYZE — complete (1.6s)",     detail: "Sanctions match confirmed (0.94 confidence). Dormant account reactivation pattern. 8 inbound transfers from sanctioned correspondent. IMMEDIATE SAR FILING required.", evidence_id: "EVID-002" },
    { id: "aud-003-06", timestamp: "2026-04-03T08:25:11Z", actor: "AI Agent",            action: "Step 5 NARRATE — complete (2.8s)",     detail: "SAR narrative generated — 4 sections, 978 words. Account freeze instructions + OFAC blocking report procedures documented." },
    { id: "aud-003-07", timestamp: "2026-04-03T09:45:30Z", actor: "analyst@argonis.ai",  action: "Section approved — Executive Summary",  detail: "Approved. OFAC match verified against live SDN database. Match parameters cross-checked: name, DOB, nationality.", evidence_id: "EVID-002" },
    { id: "aud-003-08", timestamp: "2026-04-03T09:47:15Z", actor: "analyst@argonis.ai",  action: "Section approved — Subject Profile",    detail: "Approved. Passport details, dormancy timeline, and KYC data cross-checked against source records.", evidence_id: "EVID-001" },
    { id: "aud-003-09", timestamp: "2026-04-03T09:55:44Z", actor: "bso@argonis.ai",      action: "Case escalated to BSA/OFAC Officer",    detail: "Account ****2291 freeze initiated pending OFAC blocking report. Board notification triggered. Tipping-off prohibition in effect." },
  ],
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

/** Get severity colour classes — dark theme */
export function riskColors(score: number): string {
  if (score >= 0.85)
    return "bg-danger-subtle text-danger-DEFAULT ring-1 ring-danger-DEFAULT/30";
  if (score >= 0.65)
    return "bg-warn-subtle text-warn-DEFAULT ring-1 ring-warn-DEFAULT/30";
  if (score >= 0.40)
    return "bg-accent-subtle text-accent-DEFAULT ring-1 ring-accent-DEFAULT/30";
  return "bg-surface-3 text-text-muted ring-1 ring-border";
}

/** Map case status to display label + colour — dark theme */
export function statusMeta(
  status: string,
): { label: string; classes: string } {
  switch (status) {
    case "open":
      return { label: "Pending", classes: "bg-surface-3 text-text-muted" };
    case "in_review":
      return { label: "In Review", classes: "bg-accent-subtle text-accent-DEFAULT" };
    case "escalated":
      return { label: "Escalated", classes: "bg-warn-subtle text-warn-DEFAULT" };
    case "closed":
      return { label: "Closed", classes: "bg-success-subtle text-success-DEFAULT" };
    default:
      return { label: status, classes: "bg-surface-3 text-text-muted" };
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
