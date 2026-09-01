"""Pydantic schemas for Decision Intelligence — Compliance Matrix, Recommendation, Gap Analysis."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    CapabilityEntityType,
    ComplianceMatrixVerificationStatus,
    MatchStatus,
    RecommendationType,
    RequirementNature,
    RequirementType,
    RiskLevel,
)

# Architecture debate Phase 5: QualificationStatus/ReadinessStatus stay
# defined in app.agents.decision_engine (Phase 2 decision, unchanged —
# they're derived evaluation states, not database-backed enums, and
# app/models/enums.py's own docstring reserves it for enums that
# type-constrain an actual schema/DB column). Importing them here is a
# new precedent: no other app/schemas/*.py file previously imported from
# app.agents. Flagging deliberately rather than silently introducing it —
# the alternative (duplicating the enum in this file, or moving it to
# enums.py against the Phase 2 decision) both seemed worse: duplication
# risks drift, and moving it would contradict a decision already
# reviewed and approved. No circular-import risk: decision_engine.py
# does not import anything from app.schemas.decision.
from app.agents.decision_engine import QualificationStatus, ReadinessStatus


class EvidenceSourceRead(BaseModel):
    """
    Resolves ComplianceMatrix.evidence_reference (a CapabilityMapping id,
    opaque to the frontend) into the actual company record and source
    document that grounds a recommendation — the "Company Document" leg of
    the Decision Screen's signature evidence trail (DESIGN_SYSTEM.md §10:
    Recommendation -> Evidence -> Source Clause -> Company Document). Built
    by decision_service.resolve_evidence_sources() at response time; never
    stored — the underlying CapabilityMapping row is the source of truth.
    """

    entity_type: CapabilityEntityType
    label: str
    source_document_id: uuid.UUID | None
    source_document_name: str | None


class ComplianceMatrixEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    requirement_id: uuid.UUID
    status: MatchStatus
    supporting_evidence: str | None
    notes: str | None
    requires_verification: bool
    verification_reason: str | None
    risk_level: RiskLevel | None
    verification_status: ComplianceMatrixVerificationStatus
    matching_confidence: float | None
    evidence_reference: uuid.UUID | None
    # Added for the Decision Screen evidence trail (see DESIGN_SYSTEM.md
    # §10) — not present on the ComplianceMatrix ORM row itself, so these
    # two are NOT populated via model_validate()'s from_attributes; the
    # router attaches them explicitly via model_copy(update=...) once it
    # has looked up the owning Requirement and resolved the evidence
    # source. Both are optional and default to None so this stays a pure
    # additive change to the wire contract.
    source_page: int | None = None
    evidence_source: EvidenceSourceRead | None = None

    # Verification metadata (Compliance Verification UI). verified_by and
    # verified_at are already columns on the ComplianceMatrix ORM row, so
    # model_validate() populates them for free. verified_by_name is not --
    # same not-on-the-ORM-row treatment as evidence_source above, resolved
    # via decision_service.resolve_verifier_names() and attached the same
    # way (model_copy(update=...)) in _build_response(). All three are
    # additive and default to None so this stays a pure wire-contract
    # addition, matching source_page/evidence_source's own precedent.
    verified_by: uuid.UUID | None = None
    verified_by_name: str | None = None
    verified_at: datetime | None = None


class RecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mission_id: uuid.UUID
    recommendation_type: RecommendationType
    executive_summary: str | None
    risk_level: RiskLevel | None
    generated_at: datetime
    document_confidence: float | None
    entity_confidence: float | None
    matching_confidence: float | None
    recommendation_confidence: float | None
    overall_confidence: float | None
    snapshot_id: uuid.UUID | None


class GapAnalysisEntry(BaseModel):
    """Computed at response time from the Compliance Matrix, not a stored table — same
    principle as M4's freshness: derived data, not a new persistence concept."""

    requirement_id: uuid.UUID
    requirement_type: RequirementType
    description: str | None
    mandatory: bool
    status: MatchStatus
    reason: str | None
    source_page: int | None = None

    # Architecture debate Phase 5 additions. Both optional/defaulted so
    # this stays a pure additive wire-contract change, matching the
    # source_page/evidence_source precedent above. Populated from
    # decision_engine.reconstruct_match_result() — never independently
    # re-derived here, see decision_service.build_remediation_summary().
    requirement_nature: RequirementNature | None = None
    unsupported_domains: list[CapabilityEntityType] = []

    # Bid-readiness confirmation feature: whether a human has confirmed
    # this item (a SUBMISSION_GATING/FUTURE_CONTRACTUAL_COMMITMENT gap)
    # is actually prepared — see app/models/bid_readiness.py and
    # decision_engine.compute_bid_readiness()'s confirmed_requirement_ids
    # parameter. Deliberately keeps the item VISIBLE with its confirmed
    # state shown, rather than dropping it from gap_analysis/remediation_
    # summary once confirmed — the frozen design's explicit requirement.
    confirmed: bool = False
    confirmed_at: datetime | None = None

    # Qualification override feature: whether an administrator has
    # explicitly overridden this item (a mandatory CAPABILITY_CLAIM
    # qualification gap) despite no real capability evidence existing for
    # it yet — see app/models/qualification_override.py and
    # decision_engine.compute_qualification()'s overridden_requirement_ids
    # parameter. Unlike `confirmed` (which represents an already-true
    # fact), `overridden` represents an explicit, audited risk acceptance
    # — every consumer of this field MUST keep it visually distinct from
    # "requirement met," never silently absorbed into it. override_note
    # is required at creation time (OverrideRequirementRequest) precisely
    # so this audit trail always explains *why*.
    overridden: bool = False
    overridden_by: uuid.UUID | None = None
    overridden_by_name: str | None = None
    overridden_at: datetime | None = None
    override_note: str | None = None


class RemediationSummary(BaseModel):
    """
    Architecture debate Phase 5: the single deterministic backend
    representation of "what does this evaluation actually require, and
    why" — built once server-side (decision_service.build_remediation_summary)
    from the same MatchResult-equivalent data and the same
    decision_engine.compute_qualification()/compute_bid_readiness()
    functions that already drive `recommendation.recommendation_type`.
    Phase 6 wired this into the frontend/PDF as the authoritative
    presentation source, and then extended it once more (still Phase 6)
    to close a gap found during that work: `recommendation_type` can be
    REVIEW purely because of non-mandatory, optional capability items —
    see `optional_capability_gaps` below — and prior to this extension
    that state had zero structured representation anywhere in this
    schema, even though every other REVIEW-adjacent fact was covered.

    Five views, each explained in decision_engine.classify_remediation()'s
    docstring:
    - qualification / qualification_gaps: genuine capability requirements
      affecting whether the company qualifies at all.
    - bid_readiness / blocked_items / action_required_items: submission-
      gating, procedural, and future-contractual items the bid team must
      act on — never a qualification failure by themselves.
    - coverage_gaps: requirements BidOps cannot fully evaluate today
      (Phase 4) — never a capability failure, and never duplicated into
      any other bucket even though it may also be mandatory/unresolved.
    - human_review_items: CAPABILITY_CLAIM requirements whose evidence
      is genuinely ambiguous (REVIEW_REQUIRED/CONDITIONAL) — distinct
      from both a coverage gap (system can't evaluate) and a bid-
      readiness action (nothing to evaluate, just prepare/submit).
    - optional_capability_gaps (Phase 6): non-mandatory CAPABILITY_CLAIM
      requirements with a definitive NOT_MET verdict — not a qualification
      risk (qualification is computed from mandatory items only) and not
      ambiguous (NOT_MET is definitive, nothing for a human to
      adjudicate), but the one item shape that can push
      `recommendation_type` to REVIEW (via
      settings.max_optional_review_items) while contributing to no other
      bucket here. See decision_engine.classify_remediation()'s docstring,
      point 2, for the exhaustive proof that this is the only such shape.
    """

    qualification: QualificationStatus
    qualification_gaps: list[GapAnalysisEntry]

    bid_readiness: ReadinessStatus
    blocked_items: list[GapAnalysisEntry]
    action_required_items: list[GapAnalysisEntry]

    coverage_gaps: list[GapAnalysisEntry]

    human_review_items: list[GapAnalysisEntry]

    optional_capability_gaps: list[GapAnalysisEntry]


class EvaluationResponse(BaseModel):
    recommendation: RecommendationRead
    compliance_matrix: list[ComplianceMatrixEntryRead]
    gap_analysis: list[GapAnalysisEntry]
    remediation_summary: RemediationSummary
