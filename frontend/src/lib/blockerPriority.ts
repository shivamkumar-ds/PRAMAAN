import type { ComplianceMatrixEntryRead, GapAnalysisEntry, RiskLevel } from "../api/types";

// docs/TENDER_ASSESSMENT_REDESIGN.md §4/§5 -- "Top Priorities" ranking.
// Every ComplianceMatrixEntryRead already carries a real risk_level
// (critical/high/medium/low); joining it to its GapAnalysisEntry by the
// existing requirement_id key (same exact-ID join mergeRequirementContext
// already uses, not fuzzy matching) lets blockers be ordered by severity
// instead of left in whatever order the backend returned them. This reuses
// an existing signal for a new purpose -- it does not invent one.
//
// A blocker whose matrix row can't be found, or whose risk_level is null,
// falls back to "unranked" (sorted after every ranked blocker, order
// otherwise stable) rather than being assigned a fabricated severity --
// explicit rule from the redesign doc's grounding check (§5).
const SEVERITY_ORDER: Record<RiskLevel, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

export interface RankedBlocker extends GapAnalysisEntry {
  riskLevel: RiskLevel | null;
}

// `blockers` is expected to already be a backend-classified subset --
// Phase 6 (architecture debate) repoints callers from a client-computed
// `mandatory && not_met` filter to one of remediation_summary's own
// buckets (qualification_gaps / blocked_items / action_required_items /
// etc.). This function only ranks by severity; it never decides what
// counts as a blocker -- that classification is entirely backend-owned
// (decision_engine.classify_remediation()).
export function rankBlockers(blockers: GapAnalysisEntry[], matrix: ComplianceMatrixEntryRead[]): RankedBlocker[] {
  const riskByRequirement = new Map<string, RiskLevel | null>();
  matrix.forEach((row) => riskByRequirement.set(row.requirement_id, row.risk_level));

  return blockers
    .map((g) => ({ ...g, riskLevel: riskByRequirement.get(g.requirement_id) ?? null }))
    .sort((a, b) => {
      const aRank = a.riskLevel ? SEVERITY_ORDER[a.riskLevel] : SEVERITY_ORDER.low + 1;
      const bRank = b.riskLevel ? SEVERITY_ORDER[b.riskLevel] : SEVERITY_ORDER.low + 1;
      return aRank - bRank;
    });
}
