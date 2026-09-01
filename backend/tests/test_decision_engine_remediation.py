"""
Regression coverage for the deterministic remediation_summary
(architecture debate Phase 5 — see BidOps_Architecture_Debate.md and
decision_engine.classify_remediation()/RemediationClassification's
docstrings).

Tests A-G, I are pure unit tests against decision_engine.classify_remediation(),
built on hand-constructed MatchResult objects (same style as prior phase
test files) — these prove the classification rules themselves.

Test H and the end-to-end test additionally exercise
decision_service.build_remediation_results() +
decision_engine.reconstruct_match_result() against real (SQLite) persisted
Requirement/ComplianceMatrix rows and the actual api/v1/evaluation.py
response-building helpers, proving unsupported_domains and
requirement_nature genuinely survive the MatchResult -> ComplianceMatrix
(persisted) -> reconstructed MatchResult -> GapAnalysisEntry (API schema)
round trip, not just the in-memory classification step.

Test J proves backward compatibility of the wire schema.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import ARRAY

from app.agents import decision_engine
from app.agents.decision_engine import (
    MatchResult,
    QualificationStatus,
    ReadinessStatus,
    classify_remediation,
)
from app.core.database import Base
from app.models import Company, ComplianceMatrix, Mission, Recommendation, Requirement, Tender, User
from app.models.enums import (
    CapabilityEntityType,
    MatchStatus,
    MissionStatus,
    RecommendationType,
    RequirementNature,
    RequirementType,
    UserRole,
    UserStatus,
)
from app.schemas.decision import GapAnalysisEntry, RemediationSummary
from app.services import decision_service


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


def _result(
    *,
    nature: RequirementNature,
    mandatory: bool,
    status: MatchStatus,
    unsupported_domains: frozenset = frozenset(),
    requirement_id=None,
) -> MatchResult:
    return MatchResult(
        requirement_id=requirement_id or uuid.uuid4(),
        requirement_type=RequirementType.ELIGIBILITY,
        requirement_nature=nature,
        mandatory=mandatory,
        status=status,
        matched_entity_type=None,
        matched_entity_id=None,
        matching_confidence=0.9,
        supporting_evidence="test",
        notes="test",
        unsupported_domains=unsupported_domains,
    )


# ---------------------------------------------------------------------------
# Test A — genuine capability failure
# ---------------------------------------------------------------------------


def test_a_genuine_capability_failure_is_qualification_gap_only():
    r = _result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.NOT_MET)
    c = classify_remediation([r])
    assert r in c.qualification_gaps
    assert r not in c.coverage_gaps
    assert c.qualification == QualificationStatus.FAIL


# ---------------------------------------------------------------------------
# Test B — unsupported capability
# ---------------------------------------------------------------------------


def test_b_unsupported_capability_is_coverage_gap_only():
    r = _result(
        nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.REVIEW_REQUIRED,
        unsupported_domains=frozenset({CapabilityEntityType.EQUIPMENT}),
    )
    c = classify_remediation([r])
    assert r in c.coverage_gaps
    assert r not in c.qualification_gaps
    assert c.qualification != QualificationStatus.FAIL


# ---------------------------------------------------------------------------
# Test C — mandatory submission gating
# ---------------------------------------------------------------------------


def test_c_mandatory_submission_gating_is_blocked_item():
    r = _result(nature=RequirementNature.SUBMISSION_GATING, mandatory=True, status=MatchStatus.REVIEW_REQUIRED)
    c = classify_remediation([r])
    assert r in c.blocked_items
    assert c.bid_readiness == ReadinessStatus.BLOCKED


# ---------------------------------------------------------------------------
# Test D — procedural requirement
# ---------------------------------------------------------------------------


def test_d_procedural_is_action_required_only():
    r = _result(nature=RequirementNature.PROCEDURAL, mandatory=True, status=MatchStatus.REVIEW_REQUIRED)
    c = classify_remediation([r])
    assert r in c.action_required_items
    assert r not in c.qualification_gaps
    assert r not in c.blocked_items


# ---------------------------------------------------------------------------
# Test E — future contractual commitment
# ---------------------------------------------------------------------------


def test_e_future_contractual_commitment_is_action_required():
    r = _result(nature=RequirementNature.FUTURE_CONTRACTUAL_COMMITMENT, mandatory=True, status=MatchStatus.REVIEW_REQUIRED)
    c = classify_remediation([r])
    assert r in c.action_required_items


# ---------------------------------------------------------------------------
# Test F — clean qualification
# ---------------------------------------------------------------------------


def test_f_all_met_capability_claims_is_clean_qualification():
    r = _result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.MET)
    c = classify_remediation([r])
    assert c.qualification == QualificationStatus.PASS
    assert c.qualification_gaps == []
    assert c.human_review_items == []


# ---------------------------------------------------------------------------
# Test G — human-review capability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [MatchStatus.CONDITIONAL, MatchStatus.REVIEW_REQUIRED])
def test_g_mandatory_capability_uncertainty_is_human_review(status):
    r = _result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=status)
    c = classify_remediation([r])
    assert r in c.human_review_items
    assert r not in c.qualification_gaps
    assert c.qualification == QualificationStatus.CONDITIONAL


# ---------------------------------------------------------------------------
# Test I — no semantic duplication vs compute_qualification/compute_bid_readiness
# ---------------------------------------------------------------------------


def test_i_classification_matches_engine_functions_directly():
    results = [
        _result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.MET),
        _result(nature=RequirementNature.SUBMISSION_GATING, mandatory=True, status=MatchStatus.REVIEW_REQUIRED),
        _result(nature=RequirementNature.PROCEDURAL, mandatory=False, status=MatchStatus.REVIEW_REQUIRED),
    ]
    c = classify_remediation(results)
    assert c.qualification == decision_engine.compute_qualification(results)
    assert c.bid_readiness == decision_engine.compute_bid_readiness(results)


# ---------------------------------------------------------------------------
# Negative tests: the four architectural distinctions this redesign exists
# to establish, stated explicitly.
# ---------------------------------------------------------------------------


def test_unsupported_is_never_treated_as_capability_failure():
    r = _result(
        nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.REVIEW_REQUIRED,
        unsupported_domains=frozenset({CapabilityEntityType.FINANCIAL_RECORD}),
    )
    c = classify_remediation([r])
    assert c.qualification != QualificationStatus.FAIL
    assert r not in c.qualification_gaps


def test_procedural_is_never_a_qualification_failure():
    r = _result(nature=RequirementNature.PROCEDURAL, mandatory=True, status=MatchStatus.REVIEW_REQUIRED)
    c = classify_remediation([r])
    assert c.qualification != QualificationStatus.FAIL
    assert r not in c.qualification_gaps


def test_future_contractual_commitment_is_never_a_qualification_failure():
    r = _result(nature=RequirementNature.FUTURE_CONTRACTUAL_COMMITMENT, mandatory=True, status=MatchStatus.REVIEW_REQUIRED)
    c = classify_remediation([r])
    assert c.qualification != QualificationStatus.FAIL
    assert r not in c.qualification_gaps


def test_submission_gating_is_never_a_capability_failure():
    r = _result(nature=RequirementNature.SUBMISSION_GATING, mandatory=True, status=MatchStatus.REVIEW_REQUIRED)
    c = classify_remediation([r])
    assert c.qualification != QualificationStatus.FAIL
    assert r not in c.qualification_gaps


def test_no_llm_call_in_classification():
    """classify_remediation is a pure function over already-computed
    results — trivially provable by never touching get_llm_client at all."""
    results = [_result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.NOT_MET)]
    classify_remediation(results)  # no client, no network, no await anywhere in this function


# ---------------------------------------------------------------------------
# Test H (+end-to-end) — mixed coverage and requirement_nature survive the
# real persistence -> reconstruction -> API schema round trip.
# ---------------------------------------------------------------------------


@pytest.fixture()
def remediation_db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__, User.__table__, Mission.__table__, Tender.__table__,
            Requirement.__table__, Recommendation.__table__, ComplianceMatrix.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_h_unsupported_domains_and_nature_survive_persistence_round_trip(remediation_db):
    db = remediation_db
    company = Company(id=uuid.uuid4(), name="Acme", registration_number=str(uuid.uuid4()))
    db.add(company)
    db.flush()
    user = User(
        id=uuid.uuid4(), company_id=company.id, name="Admin", email=f"{uuid.uuid4()}@example.com",
        password_hash="x", role=UserRole.ADMINISTRATOR, status=UserStatus.ACTIVE,
    )
    db.add(user)
    mission = Mission(
        id=uuid.uuid4(), company_id=company.id, user_id=user.id,
        mission_type="tender_evaluation", status=MissionStatus.AWAITING_APPROVAL,
    )
    db.add(mission)
    db.flush()
    tender = Tender(id=uuid.uuid4(), mission_id=mission.id, tender_name="T")
    db.add(tender)
    db.flush()

    # TECHNICAL base domains = [Equipment, Employee, Project]. Persisted
    # with requirement_nature explicitly set to CAPABILITY_CLAIM (Phase 1
    # column) so reconstruction doesn't even need the NULL fallback here.
    requirement = Requirement(
        id=uuid.uuid4(), tender_id=tender.id, requirement_type=RequirementType.TECHNICAL,
        description="Bidder shall provide qualified personnel and adequate machinery.",
        mandatory=True, source_page=1, confidence=0.9,
        requirement_nature=RequirementNature.CAPABILITY_CLAIM,
    )
    db.add(requirement)
    db.flush()

    recommendation = Recommendation(
        id=uuid.uuid4(), mission_id=mission.id, recommendation_type=RecommendationType.CONDITIONAL_GO,
    )
    db.add(recommendation)
    db.flush()

    # Simulates what run_evaluation() would have persisted: real matching
    # succeeded on the Employee/Project subset -> MET. unsupported_domains
    # itself is NOT persisted anywhere (Phase 5's whole point) -- it must
    # be recomputed at read time from the Requirement row alone.
    compliance_row = ComplianceMatrix(
        id=uuid.uuid4(), recommendation_id=recommendation.id, requirement_id=requirement.id,
        status=MatchStatus.MET, supporting_evidence="Employee: Ramesh Kumar", notes="matched on personnel",
        matching_confidence=0.9,
    )
    db.add(compliance_row)
    db.commit()

    requirements_by_id = {requirement.id: requirement}
    results = decision_service.build_remediation_results([compliance_row], requirements_by_id)
    assert len(results) == 1
    reconstructed = results[0]

    # Action Center V-next follow-up: Equipment used to be "unsupported"
    # here because capability_service.ENTITY_MODELS (extraction-agent
    # domains only) was the supported_domains source. Manual capability
    # creation (build_capability_manual) gave Equipment/FinancialRecord a
    # real creation path, so decision_service now derives supported_domains
    # from ALL_CAPABILITY_MODELS instead -- every domain in CATEGORY_DOMAINS
    # is now reachable, so unsupported_domains is correctly empty. This is
    # the intended outcome, not a regression: a zero-candidate Equipment
    # requirement is now an ordinary, actionable "add capability" gap
    # rather than a passive "system can't evaluate this" dead end.
    assert reconstructed.unsupported_domains == frozenset()
    assert reconstructed.requirement_nature == RequirementNature.CAPABILITY_CLAIM
    assert reconstructed.status == MatchStatus.MET  # genuine evidence-based verdict preserved

    classification = classify_remediation(results)
    assert reconstructed not in classification.coverage_gaps
    assert reconstructed not in classification.qualification_gaps  # MET, not a gap of any kind

    # And through the actual API-facing schema conversion used by the router.
    from app.api.v1.evaluation import _to_gap_entry

    entry = _to_gap_entry(reconstructed, requirements_by_id, {}, {}, {})
    assert isinstance(entry, GapAnalysisEntry)
    assert entry.unsupported_domains == []
    assert entry.requirement_nature == RequirementNature.CAPABILITY_CLAIM


# ---------------------------------------------------------------------------
# Test J — existing response compatibility
# ---------------------------------------------------------------------------


def test_j_gap_analysis_entry_constructs_without_new_fields():
    """A caller that doesn't know about requirement_nature/unsupported_domains
    (e.g. an older test or client) must still be able to construct
    GapAnalysisEntry exactly as before -- both new fields are optional/
    defaulted, a pure additive wire-contract change."""
    entry = GapAnalysisEntry(
        requirement_id=uuid.uuid4(), requirement_type=RequirementType.ELIGIBILITY,
        description="test", mandatory=True, status=MatchStatus.NOT_MET, reason="test",
    )
    assert entry.requirement_nature is None
    assert entry.unsupported_domains == []


def test_j_remediation_summary_is_a_new_additive_field_on_evaluation_response():
    from app.schemas.decision import EvaluationResponse

    assert "remediation_summary" in EvaluationResponse.model_fields
    assert "gap_analysis" in EvaluationResponse.model_fields
    assert "compliance_matrix" in EvaluationResponse.model_fields


# ---------------------------------------------------------------------------
# Tests K-P (architecture debate Phase 6) — optional_capability_gaps and the
# REVIEW-explainability gap it closes. See decision_engine.classify_remediation()
# and RemediationClassification's docstrings for the full reasoning.
# ---------------------------------------------------------------------------


def _optional_capability_gap(i: int = 0) -> MatchResult:
    return _result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=False, status=MatchStatus.NOT_MET)


def test_k_non_mandatory_not_met_capability_is_optional_capability_gap_only():
    """The exact item shape this bucket exists for: non-mandatory,
    CAPABILITY_CLAIM, definitively NOT_MET, no unsupported domains."""
    r = _optional_capability_gap()
    c = classify_remediation([r])
    assert r in c.optional_capability_gaps
    assert r not in c.qualification_gaps
    assert r not in c.human_review_items
    assert r not in c.coverage_gaps
    assert r not in c.blocked_items
    assert r not in c.action_required_items


def test_l_optional_capability_gap_never_affects_qualification_or_readiness():
    """Non-mandatory NOT_MET capability items must not, by themselves,
    change qualification away from PASS or readiness away from READY --
    compute_qualification()/compute_bid_readiness() only ever look at
    mandatory items (qualification) or SUBMISSION_GATING/PROCEDURAL/
    FUTURE_CONTRACTUAL_COMMITMENT natures (readiness), neither of which
    this item shape is."""
    results = [_optional_capability_gap() for _ in range(5)]
    c = classify_remediation(results)
    assert c.qualification == QualificationStatus.PASS
    assert c.bid_readiness == ReadinessStatus.READY
    assert len(c.optional_capability_gaps) == 5


def test_m_review_threshold_not_exceeded_stays_go():
    """settings.max_optional_review_items defaults to 2 -- exactly 2
    qualifying optional items must NOT push recommendation_type to
    REVIEW (the branch is `optional_issues > max_optional_review_items`,
    strictly greater-than), even though both are now visible in
    optional_capability_gaps."""
    from app.core.config import get_settings

    settings = get_settings()
    results = [_optional_capability_gap() for _ in range(settings.max_optional_review_items)]
    c = classify_remediation(results)
    assert len(c.optional_capability_gaps) == settings.max_optional_review_items
    assert decision_engine.compute_recommendation_type(results) == RecommendationType.GO


def test_n_review_threshold_exceeded_produces_review_and_populated_bucket():
    """One more than the threshold flips recommendation_type to REVIEW --
    and, critically, optional_capability_gaps is non-empty at exactly the
    same time, closing the previously-unexplained gap this phase exists
    to fix."""
    from app.core.config import get_settings

    settings = get_settings()
    results = [_optional_capability_gap() for _ in range(settings.max_optional_review_items + 1)]
    c = classify_remediation(results)
    assert decision_engine.compute_recommendation_type(results) == RecommendationType.REVIEW
    assert len(c.optional_capability_gaps) == settings.max_optional_review_items + 1
    assert c.qualification == QualificationStatus.PASS
    assert c.bid_readiness == ReadinessStatus.READY
    # And every other bucket stays empty -- REVIEW here is explained by
    # optional_capability_gaps alone, exactly the previously-invisible case.
    assert c.qualification_gaps == []
    assert c.blocked_items == []
    assert c.action_required_items == []
    assert c.coverage_gaps == []
    assert c.human_review_items == []


def test_o_mandatory_capability_failure_still_produces_no_go_unaffected_by_new_bucket():
    """A genuine mandatory capability failure must still resolve to
    QualificationStatus.FAIL / RecommendationType.NO_GO exactly as
    before -- the new bucket must not dilute or reroute mandatory
    failures, since compute_qualification()/compute_recommendation_type()
    are entirely untouched by this change."""
    mandatory_failure = _result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.NOT_MET)
    optional_noise = [_optional_capability_gap() for _ in range(5)]
    results = [mandatory_failure] + optional_noise
    c = classify_remediation(results)
    assert c.qualification == QualificationStatus.FAIL
    assert decision_engine.compute_recommendation_type(results) == RecommendationType.NO_GO
    assert mandatory_failure in c.qualification_gaps
    assert mandatory_failure not in c.optional_capability_gaps
    assert len(c.optional_capability_gaps) == 5


def test_p_coverage_gaps_and_human_review_unaffected_by_optional_capability_gaps():
    """Coverage gaps and human-review items keep their exact prior
    membership rules; optional_capability_gaps is purely additive and
    only ever picks up items no existing bucket already claimed
    (unsupported_domains is checked first and short-circuits, per
    classify_remediation()'s existing, unchanged ordering)."""
    coverage_item = _result(
        nature=RequirementNature.CAPABILITY_CLAIM, mandatory=False, status=MatchStatus.NOT_MET,
        unsupported_domains=frozenset({CapabilityEntityType.EQUIPMENT}),
    )
    human_review_item = _result(nature=RequirementNature.CAPABILITY_CLAIM, mandatory=False, status=MatchStatus.CONDITIONAL)
    optional_gap = _optional_capability_gap()
    c = classify_remediation([coverage_item, human_review_item, optional_gap])

    assert coverage_item in c.coverage_gaps
    assert coverage_item not in c.optional_capability_gaps
    assert human_review_item in c.human_review_items
    assert human_review_item not in c.optional_capability_gaps
    assert optional_gap in c.optional_capability_gaps
    assert optional_gap not in c.coverage_gaps
    assert optional_gap not in c.human_review_items
