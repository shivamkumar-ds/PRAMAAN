import type { RemediationSummary } from "../api/types";

// Shared, single-source-of-truth counting over remediation_summary --
// Action Center (list + detail cards) and Dashboard's Critical Gaps figure
// both need "how many items of each kind" without re-deriving what belongs
// in each bucket (that classification stays entirely backend-owned, see
// decision_engine.classify_remediation()). This only counts array lengths
// it's handed; it never re-decides membership.
//
// "Bid preparation" merges blocked_items + action_required_items into one
// figure -- both are "the bidder needs to prepare/complete something,"
// distinct from a genuine capability gap (qualification_gaps) per the
// Action Center design note. blocked_items and action_required_items
// remain separately available on RemediationSummary for anywhere that
// needs the mandatory/non-mandatory distinction (e.g. the existing
// Evaluation.tsx Analysis tab sections, unchanged by this file).
export interface RemediationCounts {
  qualification: number;
  bidPrep: number;
  coverage: number;
  humanReview: number;
  // Non-mandatory CAPABILITY_CLAIM items with a definitive NOT_MET verdict
  // (see decision_engine.classify_remediation()'s optional_capability_gaps
  // branch -- confirmed disjoint from every other bucket here, same
  // single-pass for/elif loop assigns each result to exactly one bucket).
  // Deliberately excluded from `total`/isFullyClear: these aren't a
  // qualification risk and don't block anything -- surfacing them as
  // "outstanding" would misrepresent them as blockers, which the backend
  // itself never treats them as (see compute_qualification()/
  // compute_bid_readiness(), neither of which looks at this bucket).
  reviewOptional: number;
  total: number;
}

export function remediationCounts(r: RemediationSummary): RemediationCounts {
  const qualification = r.qualification_gaps.length;
  const bidPrep = r.blocked_items.length + r.action_required_items.length;
  const coverage = r.coverage_gaps.length;
  const humanReview = r.human_review_items.length;
  const reviewOptional = r.optional_capability_gaps.length;
  return {
    qualification,
    bidPrep,
    coverage,
    humanReview,
    reviewOptional,
    total: qualification + bidPrep + coverage + humanReview,
  };
}

export function isFullyClear(r: RemediationSummary): boolean {
  return remediationCounts(r).total === 0;
}

// Typed progress summary -- replaces a single flat "N remaining" figure
// with per-kind counts (Action Center V-next). Deliberately takes the
// bid-prep remaining/confirmed split as separate params rather than
// re-deriving it here: that split (blocked_items + action_required_items,
// partitioned by item.confirmed) is owned by ActionCenter.tsx's
// splitBidPrep()/bidPrepItems() helpers, which already account for the
// themed-grouping presentation layer -- duplicating that logic here would
// risk the two drifting. "Needs review" merges coverage + human-review
// counts, matching the Action Center V-next "Needs Your Review" heading
// that itself merges coverage_gaps + human_review_items under one section.
export function formatTypedProgress(
  counts: RemediationCounts,
  bidPrepRemaining: number,
  bidPrepConfirmed: number
): string {
  const parts: string[] = [];
  if (counts.qualification > 0) {
    parts.push(`${counts.qualification} capability gap${counts.qualification === 1 ? "" : "s"} remaining`);
  }
  if (bidPrepRemaining > 0 || bidPrepConfirmed > 0) {
    const confirmedSuffix = bidPrepConfirmed > 0 ? ` (${bidPrepConfirmed} confirmed)` : "";
    parts.push(
      `${bidPrepRemaining} bid-preparation item${bidPrepRemaining === 1 ? "" : "s"} remaining${confirmedSuffix}`
    );
  }
  const needsReview = counts.coverage + counts.humanReview;
  if (needsReview > 0) {
    parts.push(`${needsReview} item${needsReview === 1 ? "" : "s"} need review`);
  }
  if (parts.length === 0) return "Nothing outstanding.";
  return parts.join(" · ");
}

// Worst-first ordering for the Action Center list -- matches the accent
// logic already used in Evaluation.tsx's Overview tab (no_go = danger,
// review/conditional_go = warning, go = success), just expressed as a
// sortable rank instead of a color.
export const RECOMMENDATION_URGENCY_RANK: Record<string, number> = {
  no_go: 0,
  review: 1,
  conditional_go: 2,
  go: 3,
};
