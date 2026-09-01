import type { GapAnalysisEntry } from "../api/types";

// Frontend-only presentation grouping over the ALREADY-CLASSIFIED
// FUTURE_CONTRACTUAL_COMMITMENT subset of remediation_summary.action_required_items
// (non-blocked, unconfirmed -- see callers in ActionCenter.tsx). This module
// never re-decides which bucket a requirement belongs to (that's
// decision_engine.classify_remediation(), server-side, unchanged) -- it only
// clusters an already-given list of GapAnalysisEntry by a keyword match on
// `description`, for display. Deliberately no backend call, no new schema.
//
// Taxonomy grounded in real extracted requirement text from Indian public-
// works/CPPP-style tenders (see backend/tests fixtures and
// docs/07_AI_Agent_Architecture.md's FUTURE_CONTRACTUAL_COMMITMENT examples:
// PPE, safety, labour-law compliance during execution) -- the five themes
// below (four keyword themes + Other fallback) cover the domains that
// actually recur in that requirement text: workplace safety, statutory
// labour compliance, vehicles/transport on site, and general site-execution
// obligations to the Engineer-in-Charge. No theme was invented without a
// matching keyword rationale; "Other" is the deliberate catch-all so a
// requirement is never silently dropped for not matching a theme.

export type ActionCenterThemeKey = "safety_ppe" | "labour_compliance" | "vehicle_transport" | "site_execution" | "other";

export interface ActionCenterTheme {
  key: ActionCenterThemeKey;
  label: string;
  description: string;
}

export const ACTION_CENTER_THEMES: Record<ActionCenterThemeKey, ActionCenterTheme> = {
  safety_ppe: {
    key: "safety_ppe",
    label: "Safety & PPE",
    description: "Workplace safety, protective equipment, and accident-prevention obligations.",
  },
  labour_compliance: {
    key: "labour_compliance",
    label: "Labour & statutory compliance",
    description: "Employment-law and statutory labour obligations during execution.",
  },
  vehicle_transport: {
    key: "vehicle_transport",
    label: "Vehicle & transport",
    description: "Vehicle, driver, and site-transport conduct requirements.",
  },
  site_execution: {
    key: "site_execution",
    label: "Site execution & operational obligations",
    description: "Day-to-day site conduct and cooperation obligations owed to the Engineer-in-Charge.",
  },
  other: {
    key: "other",
    label: "Other execution commitments",
    description: "Future contractual commitments that don't fit the categories above.",
  },
};

// Ordered, most-specific-first -- a requirement is assigned to the first
// theme whose keyword list matches (see classifyTheme below), so this order
// is the tie-break when text could plausibly match more than one theme
// (e.g. "vehicle" plus "safety" in the same sentence resolves to Safety &
// PPE, the more liability-sensitive category, ahead of Vehicle & transport).
const THEME_KEYWORDS: { key: ActionCenterThemeKey; keywords: string[] }[] = [
  {
    key: "safety_ppe",
    keywords: [
      "safety", "ppe", "personal protective equipment", "protective equipment", "helmet",
      "safety net", "safety belt", "hazardous", "injury", "accident", "first aid",
    ],
  },
  {
    key: "labour_compliance",
    keywords: [
      "labour law", "labor law", "wages act", "provident fund", "employees' state insurance",
      "employees state insurance", "esi", "workmen compensation", "workmen's compensation",
      "industrial disputes act", "labour licence", "labour license", "18 years of age",
      "contract labour", "contract labor", "minimum wages",
    ],
  },
  {
    key: "vehicle_transport",
    keywords: [
      "vehicle", "driver", "driving licence", "driving license", "speed limit",
      "gas cylinder", "transport", "lashed", "loaded",
    ],
  },
  {
    key: "site_execution",
    keywords: [
      "engineer-in-charge", "engineer in charge", "site", "drawings", "materials inspection",
      "completion schedule", "maintenance period", "hindrance register",
      "cooperate with other contractors", "cooperate with other agencies",
    ],
  },
];

export function classifyTheme(description: string | null | undefined): ActionCenterThemeKey {
  const text = (description || "").toLowerCase();
  for (const { key, keywords } of THEME_KEYWORDS) {
    if (keywords.some((kw) => text.includes(kw))) return key;
  }
  return "other";
}

// A themed group -- only ever produced for 2+ items (see groupByTheme()'s
// "no group of 1" rule below). `items` order matches input order.
export interface ThemedGroup {
  theme: ActionCenterTheme;
  items: GapAnalysisEntry[];
}

export interface ThemedGrouping {
  groups: ThemedGroup[];
  // Individual items -- either a theme with only 1 match (design rule: a
  // 1-item "group" renders as an individual item, not a collapsible group
  // of one), or items in the "other" bucket when that bucket itself has
  // fewer than 2 items. Order: original input order.
  individual: GapAnalysisEntry[];
}

// Pure function: groups `items` (already filtered by the caller to the
// FUTURE_CONTRACTUAL_COMMITMENT subset of action_required_items) by theme.
// Design rule (frozen): a theme with only 1 item never renders as a
// collapsible "group of 1" -- it's demoted to `individual` alongside every
// other ungrouped item, so the UI never shows a single-row accordion.
export function groupByTheme(items: GapAnalysisEntry[]): ThemedGrouping {
  const buckets = new Map<ActionCenterThemeKey, GapAnalysisEntry[]>();
  for (const item of items) {
    const key = classifyTheme(item.description);
    const bucket = buckets.get(key) ?? [];
    bucket.push(item);
    buckets.set(key, bucket);
  }

  const groups: ThemedGroup[] = [];
  const individual: GapAnalysisEntry[] = [];

  // Preserve original item order for the individual list by re-walking
  // `items` rather than flattening bucket-by-bucket -- otherwise a
  // demoted 1-item theme would jump to wherever its bucket happened to be
  // inserted rather than staying where it appeared in the source list.
  const groupedKeys = new Set<ActionCenterThemeKey>();
  for (const [key, bucketItems] of buckets) {
    if (bucketItems.length >= 2) {
      groups.push({ theme: ACTION_CENTER_THEMES[key], items: bucketItems });
      groupedKeys.add(key);
    }
  }
  for (const item of items) {
    const key = classifyTheme(item.description);
    if (!groupedKeys.has(key)) individual.push(item);
  }

  // Stable, deterministic group order -- THEME_KEYWORDS order, then
  // "other" last (it's the fallback, so it always trails specific themes).
  const order: ActionCenterThemeKey[] = [...THEME_KEYWORDS.map((t) => t.key), "other"];
  groups.sort((a, b) => order.indexOf(a.theme.key) - order.indexOf(b.theme.key));

  return { groups, individual };
}
