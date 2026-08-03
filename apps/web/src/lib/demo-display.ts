import type { ScreeningResult } from "./types";

export type DemoTypologyKey = "starling_bank" | "td_bank" | "danske_bank";

export type DemoSourceMetadata = {
  is_featured?: boolean;
  source_name?: string;
  source_url?: string;
  regulator?: string;
  [key: string]: unknown;
} | null;

const DEMO_KEYS: DemoTypologyKey[] = [
  "starling_bank",
  "td_bank",
  "danske_bank",
];

const SUBJECT_HINTS: { pattern: RegExp; key: DemoTypologyKey }[] = [
  { pattern: /\bMeridian\b/i, key: "starling_bank" },
  { pattern: /\bNorthgate\b/i, key: "td_bank" },
  { pattern: /\bBaltic\b/i, key: "danske_bank" },
];

const SOURCE_URL_HINTS: { pattern: RegExp; key: DemoTypologyKey }[] = [
  { pattern: /fca\.org\.uk/i, key: "starling_bank" },
  { pattern: /starling/i, key: "starling_bank" },
  { pattern: /td-bank|td_bank|\/td\b/i, key: "td_bank" },
  { pattern: /danske/i, key: "danske_bank" },
];

const SLUG_SANITIZE: [RegExp, string][] = [
  [/\bDemo:\s*starling_bank\b/gi, "Partial screening / coverage gap"],
  [/\bDemo:\s*td_bank\b/gi, "Structuring"],
  [/\bDemo:\s*danske_bank\b/gi, "Layering"],
  [/\bstarling_bank\b/gi, "Partial screening / coverage gap"],
  [/\btd_bank\b/gi, "Structuring"],
  [/\bdanske_bank\b/gi, "Layering"],
];

/**
 * Detect demo typology from case title, source_metadata, or known subject names.
 */
export function detectDemoKey(
  caseTitle: string,
  sourceMetadata?: DemoSourceMetadata,
): DemoTypologyKey | null {
  const demoPrefix = caseTitle.match(/^Demo:\s*(\w+)\s*—/i);
  if (demoPrefix?.[1]) {
    const slug = demoPrefix[1].toLowerCase();
    if ((DEMO_KEYS as string[]).includes(slug)) {
      return slug as DemoTypologyKey;
    }
  }

  const lower = caseTitle.toLowerCase();
  for (const key of DEMO_KEYS) {
    if (lower.includes(key)) return key;
  }

  if (sourceMetadata?.is_featured === true) {
    return "starling_bank";
  }

  const sourceUrl =
    typeof sourceMetadata?.source_url === "string"
      ? sourceMetadata.source_url
      : "";
  if (sourceUrl) {
    for (const { pattern, key } of SOURCE_URL_HINTS) {
      if (pattern.test(sourceUrl)) return key;
    }
  }

  for (const { pattern, key } of SUBJECT_HINTS) {
    if (pattern.test(caseTitle)) return key;
  }

  return null;
}

export function displayAlertRef(key: DemoTypologyKey): string {
  switch (key) {
    case "starling_bank":
      return "ENF-PARTIAL-2024-001";
    case "td_bank":
      return "ENF-STRUCT-2024-001";
    case "danske_bank":
      return "ENF-LAYER-2024-001";
  }
}

export function displayTypologyLabel(key: DemoTypologyKey): string {
  switch (key) {
    case "starling_bank":
      return "Partial screening / coverage gap";
    case "td_bank":
      return "Structuring";
    case "danske_bank":
      return "Layering";
  }
}

export function displayCaseTitle(
  key: DemoTypologyKey,
  customerName: string,
): string {
  return `${displayTypologyLabel(key)} — ${customerName}`;
}

export function publicSourceAttribution(key: DemoTypologyKey): {
  label: string;
  url: string;
} {
  switch (key) {
    case "starling_bank":
      return {
        label:
          "Inspired by public enforcement action: FCA Final Notice — Starling Bank Limited (Sept 2024)",
        url: "https://www.fca.org.uk/news/press-releases/fca-fines-starling-bank-failings-financial-crime-systems-and-controls",
      };
    case "td_bank":
      return {
        label:
          "Inspired by public enforcement action: United States v. TD Bank, N.A. (2024)",
        url: "https://www.justice.gov/criminal/case/united-states-america-v-td-bank-na",
      };
    case "danske_bank":
      return {
        label:
          "Inspired by public enforcement action: United States v. Danske Bank A/S (2022)",
        url: "https://www.justice.gov/archives/opa/pr/danske-bank-pleads-guilty-fraud-us-banks-multi-billion-dollar-scheme-access-us-financial",
      };
  }
}

/** Replace internal demo slugs so UI never leaks starling_bank / td_bank / etc. */
export function sanitizeDisplayText(text: string): string {
  let out = text;
  for (const [pattern, replacement] of SLUG_SANITIZE) {
    out = out.replace(pattern, replacement);
  }
  return out;
}

export interface KeywordGroup {
  entity: string;
  count: number;
  hits: ScreeningResult[];
}

export interface GroupedScreeningResults {
  exact: ScreeningResult[];
  keywordGroups: KeywordGroup[];
}

function isExactHit(r: ScreeningResult): boolean {
  const matchType = r.match_data?.match_type ?? "";
  if (matchType === "exact") return true;
  const listName = r.match_data?.list_name ?? "";
  if (
    r.match_confidence >= 0.99 &&
    (/SDN/i.test(listName) || /OFAC/i.test(listName))
  ) {
    return true;
  }
  return false;
}

/**
 * Split screening results into exact hits (shown first) and keyword groups
 * collapsed by entity_name.
 */
export function groupScreeningResults(
  results: ScreeningResult[],
): GroupedScreeningResults {
  const exact: ScreeningResult[] = [];
  const keyword: ScreeningResult[] = [];

  for (const r of results) {
    if (isExactHit(r)) exact.push(r);
    else keyword.push(r);
  }

  exact.sort((a, b) => b.match_confidence - a.match_confidence);

  const byEntity = new Map<string, ScreeningResult[]>();
  for (const r of keyword) {
    const key = r.entity_name || "Unknown";
    const list = byEntity.get(key);
    if (list) list.push(r);
    else byEntity.set(key, [r]);
  }

  const keywordGroups: KeywordGroup[] = [...byEntity.entries()]
    .map(([entity, hits]) => ({
      entity,
      count: hits.length,
      hits: hits.sort((a, b) => b.match_confidence - a.match_confidence),
    }))
    .sort((a, b) => b.count - a.count);

  return { exact, keywordGroups };
}
