import type { ComplianceMatrixEntryRead, GapAnalysisEntry } from "../api/types";

// Every compliance-matrix row on its own only carries a requirement_id --
// no requirement text. gap_analysis entries (for every non-"met" row) DO
// carry the requirement's description + type + mandatory flag. Joining the
// two by requirement_id gives every row a real, human heading instead of
// the generic reasoning text or a raw evidence dump standing in for one.
// For the remaining "met" rows (which never appear in gap_analysis because
// there's nothing to flag), `notes` is already a well-written one-line
// justification, so it's the next best heading -- `supporting_evidence`
// (the raw matched record) is demoted to a collapsible detail either way.
// Used by the mission page (Evaluation.tsx) and its PDF export
// (lib/pdfReport.ts) so both render the same requirement text instead of
// two divergent copies. (Reports.tsx, an earlier separate consumer, was
// retired as a duplicate browse view over the same mission data --
// see docs/TENDER_JOURNEY_DEFERRED_ENHANCEMENTS.md.)
export function mergeRequirementContext(matrix: ComplianceMatrixEntryRead[], gaps: GapAnalysisEntry[]) {
  const byRequirement = new Map<string, GapAnalysisEntry>();
  gaps.forEach((g) => byRequirement.set(g.requirement_id, g));

  return matrix.map((entry) => {
    const gap = byRequirement.get(entry.requirement_id);
    return {
      ...entry,
      heading: gap?.description ?? entry.notes ?? "Requirement detail unavailable.",
      requirementType: gap?.requirement_type ?? null,
      mandatory: gap?.mandatory ?? null,
      // Additive (docs/TENDER_ASSESSMENT_IMPLEMENTATION_PLAN.md Phase 1) --
      // gap_analysis's own forward-looking/retrospective reason text,
      // threaded through so the Why/What-Would-It-Take tiers can render it
      // without a second lookup. Existing consumers (Reports.tsx/
      // pdfReport.ts) ignore unknown fields, so this is safe for them.
      reason: gap?.reason ?? null,
      // Architecture debate Phase 6 -- threaded through purely for display
      // (a small badge on the Compliance Matrix row); the classification
      // itself is never re-derived from this, only rendered.
      requirementNature: gap?.requirement_nature ?? null,
    };
  });
}

export type MergedComplianceEntry = ReturnType<typeof mergeRequirementContext>[number];
