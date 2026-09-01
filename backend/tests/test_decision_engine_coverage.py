"""
Regression coverage for EvaluationCoverage (architecture debate Phase 4 —
see BidOps_Architecture_Debate.md and decision_engine.get_evaluation_coverage()
/ get_unsupported_domains() / build_unsupported_coverage_result()'s
docstrings).

Fixes the confirmed conflation: a CAPABILITY_CLAIM requirement whose only
candidate domain has no extraction agent (Equipment, FinancialRecord)
used to fall into match_requirement()'s "zero candidates" branch and
come back MatchStatus.NOT_MET — indistinguishable from "the company
genuinely has no equipment." Phase 4 makes BidOps honest about the
difference: "we cannot currently evaluate this" is not the same
statement as "the company failed this requirement."

Tests 1-3, 5-8 are pure-function/unit tests against hand-built
MatchResult/requirement objects (same style as
test_decision_engine_nature.py/test_decision_engine_routing.py). Test 4
(mixed domains) and the "no additional LLM call" test go one level
deeper into match_requirement() itself, since the mixed-domain behavior
specifically depends on match_requirement()'s branching, not just the
pure domain-set helpers.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone

import pytest

from app.agents import decision_engine
from app.agents.decision_engine import (
    EvaluationCoverage,
    MatchResult,
    QualificationStatus,
    RecommendationType,
    build_unsupported_coverage_result,
    compute_qualification,
    compute_recommendation_type,
    get_evaluation_coverage,
    get_unsupported_domains,
    match_requirement,
)
from app.models.enums import CapabilityEntityType, MatchStatus, RequirementNature, RequirementType
from app.services import capability_service


# ---------------------------------------------------------------------------
# Confirm the real registry is what we think it is -- if this ever drifts
# (e.g. an Equipment agent ships), these Phase 4 tests should fail loudly
# rather than silently keep asserting stale assumptions.
# ---------------------------------------------------------------------------


def test_entity_models_is_the_real_source_of_truth():
    supported = set(capability_service.ENTITY_MODELS.keys())
    assert supported == {
        CapabilityEntityType.CERTIFICATION,
        CapabilityEntityType.EMPLOYEE,
        CapabilityEntityType.PROJECT,
    }
    assert CapabilityEntityType.EQUIPMENT not in supported
    assert CapabilityEntityType.FINANCIAL_RECORD not in supported


# ---------------------------------------------------------------------------
# Test 1 — supported Project
# ---------------------------------------------------------------------------


def test_supported_project_domain_is_supported():
    supported = set(capability_service.ENTITY_MODELS.keys())
    assert get_evaluation_coverage(CapabilityEntityType.PROJECT, supported) == EvaluationCoverage.SUPPORTED


# ---------------------------------------------------------------------------
# Test 2 — unsupported Equipment
# ---------------------------------------------------------------------------


def test_unsupported_equipment_domain_is_unsupported():
    supported = set(capability_service.ENTITY_MODELS.keys())
    assert get_evaluation_coverage(CapabilityEntityType.EQUIPMENT, supported) == EvaluationCoverage.UNSUPPORTED


class _FakeRequirement:
    def __init__(self, requirement_type, description, mandatory=True, requirement_nature=None):
        self.id = uuid.uuid4()
        self.requirement_type = requirement_type
        self.description = description
        self.mandatory = mandatory
        self.requirement_nature = requirement_nature


@pytest.mark.asyncio
async def test_equipment_only_requirement_is_review_required_not_not_met():
    """The core Phase 4 fix: a requirement whose only resolved domain is
    Equipment must not become NOT_MET just because zero Equipment rows
    can ever exist."""
    req = _FakeRequirement(RequirementType.TECHNICAL, "Bidder shall provide machinery details.")
    # TECHNICAL's base domains are [EQUIPMENT, EMPLOYEE, PROJECT] -- to
    # isolate the "fully unsupported" case we need every resolved domain
    # unsupported, so use a supported_domains set with none of the three.
    result = await match_requirement(req, candidates=[], supported_domains=set())
    assert result.status == MatchStatus.REVIEW_REQUIRED
    assert result.status != MatchStatus.NOT_MET
    assert CapabilityEntityType.EQUIPMENT in result.unsupported_domains


# ---------------------------------------------------------------------------
# Test 3 — unsupported FinancialRecord (same principle)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_financial_record_only_domain_is_review_required_not_not_met():
    req = _FakeRequirement(
        RequirementType.ELIGIBILITY, "Bidder shall meet the minimum average annual turnover.",
    )
    # Isolate FinancialRecord as the only "domain" via an explicit
    # supported_domains set that excludes it but not the others is not
    # possible for ELIGIBILITY (base domains include Certification/
    # FinancialRecord/Project) -- test the domain-level function directly
    # for FinancialRecord specifically, matching Test 2's structure.
    supported = set(capability_service.ENTITY_MODELS.keys())
    assert get_evaluation_coverage(CapabilityEntityType.FINANCIAL_RECORD, supported) == EvaluationCoverage.UNSUPPORTED

    # And confirm the full requirement-level behavior when ALL of
    # ELIGIBILITY's domains are treated as unsupported (isolates the
    # "fully unsupported" branch exactly as test 2 did for TECHNICAL).
    result = await match_requirement(req, candidates=[], supported_domains=set())
    assert result.status == MatchStatus.REVIEW_REQUIRED
    assert result.status != MatchStatus.NOT_MET
    assert CapabilityEntityType.FINANCIAL_RECORD in result.unsupported_domains


# ---------------------------------------------------------------------------
# Test 4 — mixed supported + unsupported domains
# ---------------------------------------------------------------------------


class _AlwaysMetLLMClient:
    async def complete(self, system_prompt, user_prompt, purpose="unspecified"):
        return json.dumps({"status": "met", "matched_entity_index": 0, "reasoning": "test"})


@pytest.mark.asyncio
async def test_mixed_domain_requirement_matches_on_supported_subset_and_flags_the_gap(monkeypatch):
    """
    Decision made after inspecting match_requirement()/decision_service's
    candidate-building: a mixed-domain requirement (e.g. TECHNICAL ->
    Equipment+Employee+Project) is NOT forced to a single binary
    UNSUPPORTED verdict just because Equipment is one of its domains.
    Equipment never contributes real candidates today anyway (no
    extraction path exists -- confirmed via capability_service.py /
    app/api/v1/capabilities.py's 422 gate), so genuinely-available
    Employee/Project evidence is used for real matching exactly as
    before, while unsupported_domains still names Equipment so the
    report layer (Phase 5) can surface the gap without discarding the
    real verdict. This is why no third PARTIALLY_SUPPORTED state is
    needed: coverage is tracked per-domain (a set), not forced into one
    requirement-level enum value.
    """
    monkeypatch.setattr(decision_engine, "get_llm_client", lambda *_: _AlwaysMetLLMClient())

    req = _FakeRequirement(RequirementType.TECHNICAL, "Bidder shall provide qualified personnel.")
    supported = {CapabilityEntityType.EMPLOYEE, CapabilityEntityType.PROJECT}  # Equipment excluded

    class _FakeEmployee:
        id = uuid.uuid4()
        name = "Ramesh Kumar"
        position = "Site Engineer"
        qualification = "B.Tech Civil"
        skills = ["civil construction"]
        confidence_score = 0.9
        last_verified_at = datetime.now(timezone.utc)
        created_at = datetime.now(timezone.utc)

    candidates = [(CapabilityEntityType.EMPLOYEE, _FakeEmployee())]

    result = await match_requirement(req, candidates, supported_domains=supported)

    # Real matching happened on the supported subset -- status reflects
    # genuine evidence, not a forced coverage-gap placeholder.
    assert result.status == MatchStatus.MET
    assert result.matched_entity_type == CapabilityEntityType.EMPLOYEE

    # But the gap is still visible: Equipment was never actually checked.
    assert CapabilityEntityType.EQUIPMENT in result.unsupported_domains
    assert CapabilityEntityType.EMPLOYEE not in result.unsupported_domains
    assert CapabilityEntityType.PROJECT not in result.unsupported_domains


# ---------------------------------------------------------------------------
# Test 5 — unsupported capability does not cause Qualification FAIL
# ---------------------------------------------------------------------------


def test_unsupported_mandatory_capability_does_not_cause_qualification_fail():
    unsupported_result = build_unsupported_coverage_result(
        _FakeRequirement(RequirementType.TECHNICAL, "machinery details", mandatory=True),
        RequirementNature.CAPABILITY_CLAIM,
        frozenset({CapabilityEntityType.EQUIPMENT}),
    )
    assert compute_qualification([unsupported_result]) != QualificationStatus.FAIL
    assert compute_qualification([unsupported_result]) == QualificationStatus.CONDITIONAL


# ---------------------------------------------------------------------------
# Test 6 — unsupported coverage prevents a clean GO
# ---------------------------------------------------------------------------


def test_unsupported_mandatory_capability_prevents_clean_go():
    met_result = MatchResult(
        requirement_id=uuid.uuid4(), requirement_type=RequirementType.CERTIFICATION,
        requirement_nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True, status=MatchStatus.MET,
        matched_entity_type=None, matched_entity_id=None, matching_confidence=0.9,
        supporting_evidence="test", notes="test",
    )
    unsupported_result = build_unsupported_coverage_result(
        _FakeRequirement(RequirementType.TECHNICAL, "machinery details", mandatory=True),
        RequirementNature.CAPABILITY_CLAIM,
        frozenset({CapabilityEntityType.EQUIPMENT}),
    )
    recommendation = compute_recommendation_type([met_result, unsupported_result])
    assert recommendation != RecommendationType.GO
    assert recommendation == RecommendationType.CONDITIONAL_GO


# ---------------------------------------------------------------------------
# Test 7 — existing supported matching remains unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fully_supported_requirement_matching_is_unchanged(monkeypatch):
    monkeypatch.setattr(decision_engine, "get_llm_client", lambda *_: _AlwaysMetLLMClient())

    req = _FakeRequirement(RequirementType.CERTIFICATION, "ISO 9001 certification required.")
    supported = set(capability_service.ENTITY_MODELS.keys())

    class _FakeCertification:
        id = uuid.uuid4()
        certification_name = "ISO 9001"
        issuing_authority = "BIS"
        expiry_date = None
        confidence_score = 0.9
        last_verified_at = datetime.now(timezone.utc)
        created_at = datetime.now(timezone.utc)

    candidates = [(CapabilityEntityType.CERTIFICATION, _FakeCertification())]
    result = await match_requirement(req, candidates, supported_domains=supported)

    assert result.status == MatchStatus.MET
    assert result.unsupported_domains == frozenset()


def test_get_unsupported_domains_empty_when_all_supported():
    supported = set(capability_service.ENTITY_MODELS.keys())
    domains = [CapabilityEntityType.CERTIFICATION, CapabilityEntityType.PROJECT]
    assert get_unsupported_domains(domains, supported) == frozenset()


def test_get_unsupported_domains_none_supplied_means_nothing_unsupported():
    """Backward compatibility: a caller that doesn't pass supported_domains
    (None) must not have any behavior change -- everything resolves as
    supported, exactly as before Phase 4 existed."""
    domains = [CapabilityEntityType.EQUIPMENT, CapabilityEntityType.FINANCIAL_RECORD]
    assert get_unsupported_domains(domains, None) == frozenset()


# ---------------------------------------------------------------------------
# Test 8 — no additional LLM call for coverage detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_coverage_detection_makes_no_llm_call():
    class _ExplodingLLMClient:
        async def complete(self, *args, **kwargs):
            raise AssertionError("Coverage detection must not call the LLM.")

    import app.agents.decision_engine as de_module
    original = de_module.get_llm_client
    de_module.get_llm_client = lambda *_: _ExplodingLLMClient()
    try:
        req = _FakeRequirement(RequirementType.TECHNICAL, "machinery details")
        result = await match_requirement(req, candidates=[], supported_domains=set())
        assert result.status == MatchStatus.REVIEW_REQUIRED
    finally:
        de_module.get_llm_client = original


# ---------------------------------------------------------------------------
# Backward compatibility: NULL nature / no supported_domains argument at all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_requirement_without_supported_domains_argument_is_unchanged():
    """A caller that never passes supported_domains (the pre-Phase-4
    signature) must behave exactly as before -- no forced coverage gap
    appears out of nowhere."""
    req = _FakeRequirement(RequirementType.CERTIFICATION, "ISO 9001 certification required.")
    result = await match_requirement(req, candidates=[])  # no supported_domains kwarg at all
    assert result.status == MatchStatus.NOT_MET  # zero candidates, ordinary "no evidence" path
    assert result.unsupported_domains == frozenset()
