"use client";

import type {
  CaseSummary,
  CaseDetail,
  InvestigateResponse,
  NarrativeDetail,
  NarrativeSection,
  AlertImport,
  BatchAlertsResponse,
} from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Read the Supabase JWT stored after login. */
function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("argonis_token");
}

/** Store a JWT (call this after Supabase sign-in). */
export function setToken(token: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem("argonis_token", token);
  }
}

export function clearToken(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem("argonis_token");
  }
}

export class ApiError extends Error {
  constructor(
    public readonly httpStatus: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      // ignore JSON parse error
    }
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------

export function batchImportAlerts(
  alerts: AlertImport[],
): Promise<BatchAlertsResponse> {
  return req<BatchAlertsResponse>("/alerts/batch", {
    method: "POST",
    body: JSON.stringify({ alerts }),
  });
}

// ---------------------------------------------------------------------------
// Cases
// ---------------------------------------------------------------------------

export function listCases(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<CaseSummary[]> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return req<CaseSummary[]>(`/cases${q ? `?${q}` : ""}`);
}

export function getCase(id: string): Promise<CaseDetail> {
  return req<CaseDetail>(`/cases/${id}`);
}

// ---------------------------------------------------------------------------
// Investigations
// ---------------------------------------------------------------------------

export function runInvestigation(body: {
  alert_id?: string;
  alert_data?: Record<string, unknown>;
}): Promise<InvestigateResponse> {
  return req<InvestigateResponse>("/investigate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// Narratives
// ---------------------------------------------------------------------------

export function getNarrative(id: string): Promise<NarrativeDetail> {
  return req<NarrativeDetail>(`/narratives/${id}`);
}

export function approveNarrativeSections(
  narrativeId: string,
  body: {
    section_keys: string[];
    action: "approve" | "reject";
    comment?: string;
  },
): Promise<unknown> {
  return req(`/narratives/${narrativeId}/approve`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function editNarrativeSection(
  narrativeId: string,
  sectionKey: string,
  body: { content: string; title?: string },
): Promise<NarrativeSection> {
  return req<NarrativeSection>(
    `/narratives/${narrativeId}/sections/${sectionKey}`,
    {
      method: "PUT",
      body: JSON.stringify(body),
    },
  );
}
