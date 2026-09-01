import type { RecommendationType, RemediationSummary } from "../api/types";

// docs/TENDER_ASSESSMENT_REDESIGN.md §3/§4 -- the Assessment tier opens
// with a spoken claim, not a labeled data point, and the claim's tone must
// be honest about how confident the AI actually is. Go/No-Go get a plain
// declarative sentence; Review/Conditional get calibrated-uncertainty
// framing -- a different tone, not a weaker version of the same one,
// because `review` specifically means the AI doesn't have a confident
// answer and a human needs to look.
export const ASSESSMENT_CLAIM: Record<RecommendationType, string> = {
  go: "We recommend proceeding with this bid.",
  no_go: "We recommend not bidding.",
  conditional_go: "This bid can proceed, with conditions attached.",
  review: "This one is close — here's the split, your judgment decides it.",
};

export function assessmentClaim(type: RecommendationType): string {
  return ASSESSMENT_CLAIM[type];
}

// The Assessment block's fourth line (§4, added in review): a single
// grounded business-consequence sentence.
//
// Architecture debate Phase 6: this used to be synthesized from whichever
// gap_analysis blocker ranked #1 by severity, with only a single
// eligibility-vs-everything-else distinction. That collapsed exactly the
// cases Phase 5's remediation_summary now separates server-side -- a
// genuine capability FAIL and a missing-EMD BLOCKED both produced the same
// generic "risk areas" sentence. Now driven directly by
// remediation_summary.qualification/bid_readiness (never re-derived from
// gap_analysis or the compliance matrix), so this sentence and the
// Analysis tab's own sectioning always agree with each other and with the
// backend's classification -- never a uniform template applied regardless
// of what actually drove the verdict, and never a claim about the tender
// issuer's own internal review process (§5's explicit rejection).
export function assessmentConsequence(
  type: RecommendationType,
  summary: RemediationSummary | undefined
): string | null {
  if (!summary) return null;

  // Genuine capability failure -- the only case that should ever use hard
  // disqualification language.
  if (summary.qualification === "fail") {
    return "Submitting this tender today is likely to fail technical qualification due to unresolved capability gaps.";
  }

  // Qualified (PASS or CONDITIONAL), but submission itself is blocked --
  // never phrased as a capability failure, since it isn't one.
  if (summary.bid_readiness === "blocked") {
    return `The company qualifies, but ${summary.blocked_items.length} mandatory submission item${
      summary.blocked_items.length === 1 ? "" : "s"
    } (e.g. EMD, DSC, portal registration) must be resolved before this bid can be submitted.`;
  }

  if (summary.qualification === "conditional") {
    return "Qualification is conditional -- some capability evidence needs review before this can be treated as a clean pass.";
  }

  if (summary.coverage_gaps.length > 0) {
    return `PRAMAAN could not fully evaluate ${summary.coverage_gaps.length} requirement${
      summary.coverage_gaps.length === 1 ? "" : "s"
    } -- this reflects a system coverage limitation, not a confirmed company deficiency.`;
  }

  if (summary.bid_readiness === "action_required" || summary.human_review_items.length > 0) {
    return "Proceeding requires completing the flagged preparation items and/or a human review of ambiguous evidence before submission.";
  }

  // Architecture debate Phase 6 (REVIEW-explainability gap): qualification
  // PASS + bid_readiness READY + a REVIEW recommendation means the only
  // remaining, backend-authoritative explanation is optional_capability_gaps
  // -- see decision_engine.classify_remediation()'s docstring for the proof
  // that this is the only item shape that can drive REVIEW from this exact
  // state. The Overview tab renders its own dedicated "Why REVIEW" box with
  // this same figure; this keeps the paragraph-level consequence sentence
  // consistent with it rather than falling through to the generic sentence
  // below.
  if (type === "review" && summary.optional_capability_gaps.length > 0) {
    return `Qualification and bid readiness are both otherwise clean, but ${
      summary.optional_capability_gaps.length
    } non-mandatory capability item${
      summary.optional_capability_gaps.length === 1 ? " isn't" : "s aren't"
    } currently met, which is what is driving this evaluation to REVIEW.`;
  }

  return type === "go"
    ? "Every mandatory requirement is met and the bid is ready to submit."
    : "Proceeding without addressing the flagged risk areas increases the likelihood of an unfavorable outcome.";
}
