"""
Regression coverage for the Decision Engine's Qualification / Bid
Readiness / Recommendation composition (architecture debate Phase 2 —
see BidOps_Architecture_Debate.md and decision_engine.py's
compute_qualification / compute_bid_readiness / compute_recommendation_type
docstrings).

Scenarios A-H are pure unit tests against hand-constructed MatchResult
objects — this is the right level for these tests: compute_qualification()
and compute_bid_readiness() are pure functions of
(requirement_nature, mandatory, status), and the user's own spec gave the
expected result for each combination directly, not as an end-to-end
extraction/matching scenario. Scenario I (NULL nature backward
compatibility) additionally exercises resolve_evaluation_nature() against
a real (unsaved) Requirement ORM row, since that function's whole job is
reading the ORM column, not something a bare MatchResult can represent.
"""

import uuid

from app.agents.decision_engine import (
    MatchResult,
    QualificationStatus,
    ReadinessStatus,
    compute_bid_readiness,
    compute_qualification,
    compute_recommendation_type,
    resolve_evaluation_nature,
)
from app.models.enums import MatchStatus, RecommendationType, RequirementNature, RequirementType


def _result(
    *,
    nature: RequirementNature,
    mandatory: bool,
    status: MatchStatus,
    requirement_type: RequirementType = RequirementType.ELIGIBILITY,
) -> MatchResult:
    return MatchResult(
        requirement_id=uuid.uuid4(),
        requirement_type=requirement_type,
        requirement_nature=nature,
        mandatory=mandatory,
        status=status,
        matched_entity_type=None,
        matched_entity_id=None,
        matching_confidence=0.9,
        supporting_evidence="test",
        notes="test",
    )


# ---------------------------------------------------------------------------
# A — real capability gap
# ---------------------------------------------------------------------------


def test_a_mandatory_capability_not_met_is_qualification_fail_and_no_go():
    results = [_result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.NOT_MET)]
    assert compute_qualification(results) == QualificationStatus.FAIL
    assert compute_recommendation_type(results) == RecommendationType.NO_GO


# ---------------------------------------------------------------------------
# B — capability uncertainty
# ---------------------------------------------------------------------------


def test_b_mandatory_capability_review_required_is_conditional_not_fail():
    results = [_result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.REVIEW_REQUIRED)]
    assert compute_qualification(results) == QualificationStatus.CONDITIONAL
    assert compute_recommendation_type(results) != RecommendationType.NO_GO


# ---------------------------------------------------------------------------
# Post-review correction: CONDITIONAL qualification must never reach GO,
# even when readiness is READY and nothing else needs attention.
# ---------------------------------------------------------------------------


def test_conditional_qualification_with_review_required_and_ready_readiness_is_conditional_go():
    results = [_result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.REVIEW_REQUIRED)]
    assert compute_qualification(results) == QualificationStatus.CONDITIONAL
    assert compute_bid_readiness(results) == ReadinessStatus.READY
    assert compute_recommendation_type(results) == RecommendationType.CONDITIONAL_GO


def test_conditional_qualification_with_conditional_status_and_ready_readiness_is_conditional_go():
    results = [_result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.CONDITIONAL)]
    assert compute_qualification(results) == QualificationStatus.CONDITIONAL
    assert compute_bid_readiness(results) == ReadinessStatus.READY
    assert compute_recommendation_type(results) == RecommendationType.CONDITIONAL_GO


# ---------------------------------------------------------------------------
# C — capability conditional
# ---------------------------------------------------------------------------


def test_c_mandatory_capability_conditional_is_qualification_conditional():
    results = [_result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.CONDITIONAL)]
    assert compute_qualification(results) == QualificationStatus.CONDITIONAL


# ---------------------------------------------------------------------------
# D — submission gating blocker (must NOT affect qualification)
# ---------------------------------------------------------------------------


def test_d_mandatory_submission_gating_unresolved_blocks_readiness_not_qualification():
    results = [_result(nature=RequirementNature.SUBMISSION_GATING, mandatory=True, status=MatchStatus.REVIEW_REQUIRED)]
    assert compute_bid_readiness(results) == ReadinessStatus.BLOCKED
    assert compute_qualification(results) == QualificationStatus.PASS  # no capability-claim results at all


# ---------------------------------------------------------------------------
# E — procedural requirement: action required, never blocked
# ---------------------------------------------------------------------------


def test_e_mandatory_procedural_review_required_is_action_required_not_blocked():
    results = [_result(nature=RequirementNature.PROCEDURAL, mandatory=True, status=MatchStatus.REVIEW_REQUIRED)]
    assert compute_bid_readiness(results) == ReadinessStatus.ACTION_REQUIRED


# ---------------------------------------------------------------------------
# F — future contractual obligation: action required, never a qualification failure
# ---------------------------------------------------------------------------


def test_f_mandatory_future_contractual_commitment_is_action_required_not_qualification_fail():
    results = [
        _result(nature=RequirementNature.FUTURE_CONTRACTUAL_COMMITMENT, mandatory=True, status=MatchStatus.REVIEW_REQUIRED)
    ]
    assert compute_bid_readiness(results) == ReadinessStatus.ACTION_REQUIRED
    assert compute_qualification(results) == QualificationStatus.PASS


# ---------------------------------------------------------------------------
# G — fully qualified and ready
# ---------------------------------------------------------------------------


def test_g_all_met_is_pass_ready_go():
    results = [
        _result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.MET),
        _result(nature=RequirementNature.SUBMISSION_GATING, mandatory=True, status=MatchStatus.MET),
        _result(nature=RequirementNature.PROCEDURAL, mandatory=True, status=MatchStatus.MET),
    ]
    assert compute_qualification(results) == QualificationStatus.PASS
    assert compute_bid_readiness(results) == ReadinessStatus.READY
    assert compute_recommendation_type(results) == RecommendationType.GO


# ---------------------------------------------------------------------------
# H — qualified but EMD outstanding
# ---------------------------------------------------------------------------


def test_h_qualified_but_emd_outstanding_is_conditional_go():
    results = [
        _result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.MET),
        _result(nature=RequirementNature.SUBMISSION_GATING, mandatory=True, status=MatchStatus.REVIEW_REQUIRED),
    ]
    assert compute_qualification(results) == QualificationStatus.PASS
    assert compute_bid_readiness(results) == ReadinessStatus.BLOCKED
    assert compute_recommendation_type(results) == RecommendationType.CONDITIONAL_GO


# ---------------------------------------------------------------------------
# I — historical NULL nature backward compatibility
# ---------------------------------------------------------------------------


class _FakeRequirement:
    """Minimal stand-in for the ORM Requirement row -- resolve_evaluation_nature()
    only ever reads .requirement_nature and .requirement_type."""

    def __init__(self, requirement_type: RequirementType, requirement_nature=None):
        self.requirement_type = requirement_type
        self.requirement_nature = requirement_nature


def test_i_null_nature_procedural_types_resolve_to_procedural():
    for rt in (RequirementType.DEADLINE, RequirementType.SUBMISSION, RequirementType.EVALUATION_CRITERIA):
        req = _FakeRequirement(requirement_type=rt, requirement_nature=None)
        assert resolve_evaluation_nature(req) == RequirementNature.PROCEDURAL


def test_i_null_nature_other_types_resolve_to_capability_claim():
    for rt in (RequirementType.ELIGIBILITY, RequirementType.TECHNICAL, RequirementType.CERTIFICATION, RequirementType.EXPERIENCE):
        req = _FakeRequirement(requirement_type=rt, requirement_nature=None)
        assert resolve_evaluation_nature(req) == RequirementNature.CAPABILITY_CLAIM


def test_i_non_null_nature_is_used_as_is_regardless_of_requirement_type():
    """A populated column always wins -- resolve_evaluation_nature() never
    second-guesses an already-resolved value, even for a combination that
    wouldn't normally occur (e.g. a deadline-typed row somehow carrying
    SUBMISSION_GATING)."""
    req = _FakeRequirement(requirement_type=RequirementType.DEADLINE, requirement_nature=RequirementNature.SUBMISSION_GATING)
    assert resolve_evaluation_nature(req) == RequirementNature.SUBMISSION_GATING


def test_i_historical_fixture_recommendation_matches_old_interpretation():
    """A historical tender (requirement_nature NULL everywhere) must
    evaluate identically to the pre-Phase-2 architecture's own implicit
    interpretation: a mandatory NOT_MET on a non-procedural type still
    means NO_GO, exactly as before this migration existed."""
    eligibility_req = _FakeRequirement(requirement_type=RequirementType.ELIGIBILITY, requirement_nature=None)
    deadline_req = _FakeRequirement(requirement_type=RequirementType.DEADLINE, requirement_nature=None)

    results = [
        MatchResult(
            requirement_id=uuid.uuid4(),
            requirement_type=eligibility_req.requirement_type,
            requirement_nature=resolve_evaluation_nature(eligibility_req),
            mandatory=True,
            status=MatchStatus.NOT_MET,
            matched_entity_type=None,
            matched_entity_id=None,
            matching_confidence=0.9,
            supporting_evidence="test",
            notes="test",
        ),
        MatchResult(
            requirement_id=uuid.uuid4(),
            requirement_type=deadline_req.requirement_type,
            requirement_nature=resolve_evaluation_nature(deadline_req),
            mandatory=True,
            status=MatchStatus.REVIEW_REQUIRED,
            matched_entity_type=None,
            matched_entity_id=None,
            matching_confidence=1.0,
            supporting_evidence="test",
            notes="test",
        ),
    ]
    assert compute_recommendation_type(results) == RecommendationType.NO_GO


# ---------------------------------------------------------------------------
# Preserved behavior: optional-issue REVIEW overload path unchanged
# ---------------------------------------------------------------------------


def test_optional_issue_overload_still_triggers_review_when_otherwise_go():
    """Unchanged from pre-Phase-2: enough non-mandatory issues still
    produce REVIEW even when qualification/readiness would otherwise
    both be clean (PASS/READY)."""
    from app.core.config import get_settings

    threshold = get_settings().max_optional_review_items
    results = [
        _result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=False, status=MatchStatus.NOT_MET)
        for _ in range(threshold + 1)
    ]
    assert compute_qualification(results) == QualificationStatus.PASS
    assert compute_bid_readiness(results) == ReadinessStatus.READY
    assert compute_recommendation_type(results) == RecommendationType.REVIEW
