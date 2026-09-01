"""
Regression coverage for deterministic additive candidate-domain routing
(architecture debate Phase 3 — see BidOps_Architecture_Debate.md and
decision_engine.resolve_candidate_domains()/additional_domains()'s
docstrings).

Fixes the confirmed gap: RequirementType.EXPERIENCE routes only to
[PROJECT] in CATEGORY_DOMAINS, so a requirement about "expert labour" or
"skilled personnel" never considered Employee candidates even though
Employee.skills is the relevant evidence. The router widens (never
narrows) the base CATEGORY_DOMAINS set using a small, deterministic
keyword vocabulary — no LLM call, no new extraction field.

Tests 1-9 exercise resolve_candidate_domains()/additional_domains()
directly against hand-built stand-in requirement objects (mirrors the
_FakeRequirement pattern already used in test_decision_engine_nature.py)
since these are pure functions of (requirement_type, description).
"""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import ARRAY

from app.agents import decision_engine
from app.agents.decision_engine import CATEGORY_DOMAINS, additional_domains, resolve_candidate_domains
from app.core.database import Base
from app.models import (
    CapabilityMapping,
    CapabilitySnapshot,
    Certification,
    Company,
    ComplianceMatrix,
    Document,
    Employee,
    Equipment,
    FinancialRecord,
    Mission,
    Project,
    Recommendation,
    Requirement,
    Tender,
    User,
)
from app.models.enums import CapabilityEntityType, MissionStatus, RequirementType, UserRole, UserStatus
from app.services import decision_service


# sqlite has no native ARRAY/JSONB support -- same compatibility shim as
# test_decision_engine_concurrency.py (test-only; production always runs
# against real Postgres).
@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


class _FakeRequirement:
    """Minimal stand-in -- resolve_candidate_domains() only ever reads
    .requirement_type and .description."""

    def __init__(self, requirement_type: RequirementType, description: str):
        self.requirement_type = requirement_type
        self.description = description


# ---------------------------------------------------------------------------
# 1. Existing Project routing remains intact
# ---------------------------------------------------------------------------


def test_experience_requirement_about_completed_projects_still_includes_project():
    req = _FakeRequirement(
        RequirementType.EXPERIENCE,
        "Bidder shall have completed three similar works of civil construction in the last 5 years.",
    )
    domains = resolve_candidate_domains(req)
    assert CapabilityEntityType.PROJECT in domains


# ---------------------------------------------------------------------------
# 2. Personnel terms add Employee
# ---------------------------------------------------------------------------


def test_experience_requirement_about_expert_labour_adds_employee():
    req = _FakeRequirement(RequirementType.EXPERIENCE, "Bidder shall engage expert labour for the project.")
    domains = resolve_candidate_domains(req)
    assert CapabilityEntityType.EMPLOYEE in domains


# ---------------------------------------------------------------------------
# 3. Equipment terms add Equipment
# ---------------------------------------------------------------------------


def test_experience_requirement_about_machinery_adds_equipment():
    req = _FakeRequirement(RequirementType.EXPERIENCE, "Bidder shall deploy adequate machinery for excavation.")
    domains = resolve_candidate_domains(req)
    assert CapabilityEntityType.EQUIPMENT in domains


# ---------------------------------------------------------------------------
# 4. Project terms add Project (on a type that doesn't already include it)
# ---------------------------------------------------------------------------


def test_certification_requirement_mentioning_similar_work_adds_project():
    # CERTIFICATION's base domain is [CERTIFICATION] only -- no Project.
    req = _FakeRequirement(
        RequirementType.CERTIFICATION,
        "Certificate confirming experience of work on similar completed contracts.",
    )
    domains = resolve_candidate_domains(req)
    assert CapabilityEntityType.PROJECT in domains
    assert CapabilityEntityType.CERTIFICATION in domains  # base domain still present


# ---------------------------------------------------------------------------
# 5. Mixed signals produce the union
# ---------------------------------------------------------------------------


def test_mixed_requirement_with_project_and_personnel_signals_yields_union():
    req = _FakeRequirement(
        RequirementType.EXPERIENCE,
        "Bidder shall have completed similar work using qualified personnel and skilled labour.",
    )
    domains = resolve_candidate_domains(req)
    assert CapabilityEntityType.PROJECT in domains
    assert CapabilityEntityType.EMPLOYEE in domains


# ---------------------------------------------------------------------------
# 6. Existing base domains are never removed
# ---------------------------------------------------------------------------


def test_base_domains_are_never_removed_regardless_of_description_text():
    for requirement_type, base_domains in CATEGORY_DOMAINS.items():
        req = _FakeRequirement(requirement_type, "completely unrelated text with no keyword hints at all xyz123")
        domains = resolve_candidate_domains(req)
        for base_domain in base_domains:
            assert base_domain in domains, f"{base_domain} was dropped for {requirement_type}"


def test_hint_keywords_never_remove_a_base_domain_even_when_present():
    """Even when hint keywords fire, every base domain from CATEGORY_DOMAINS
    must still be present in the final set -- additive-only guarantee."""
    req = _FakeRequirement(
        RequirementType.TECHNICAL,  # base: [EQUIPMENT, EMPLOYEE, PROJECT] -- already all three
        "Bidder shall provide skilled labour, machinery, and completed similar work references.",
    )
    domains = resolve_candidate_domains(req)
    for base_domain in CATEGORY_DOMAINS[RequirementType.TECHNICAL]:
        assert base_domain in domains


# ---------------------------------------------------------------------------
# 7. No matching behavior changes for requirements without routing hints
# ---------------------------------------------------------------------------


def test_requirement_with_no_hint_keywords_yields_exactly_base_domains():
    req = _FakeRequirement(RequirementType.ELIGIBILITY, "Bidder must be a registered legal entity.")
    domains = resolve_candidate_domains(req)
    assert domains == list(CATEGORY_DOMAINS[RequirementType.ELIGIBILITY])


def test_additional_domains_empty_for_hint_free_text():
    assert additional_domains("Bidder must be a registered legal entity.") == set()


# ---------------------------------------------------------------------------
# 8. The concrete "expert labour" case now includes Employee candidates
# ---------------------------------------------------------------------------


def test_expert_labour_experience_requirement_full_domain_set():
    req = _FakeRequirement(RequirementType.EXPERIENCE, "Bidder shall have expert labour and skilled workers available.")
    domains = resolve_candidate_domains(req)
    assert CapabilityEntityType.PROJECT in domains  # base, preserved
    assert CapabilityEntityType.EMPLOYEE in domains  # new, via routing


# ---------------------------------------------------------------------------
# 9. Routing is deterministic
# ---------------------------------------------------------------------------


def test_routing_is_deterministic_across_repeated_calls():
    req = _FakeRequirement(RequirementType.EXPERIENCE, "Bidder shall engage expert labour and use modern machinery.")
    first = resolve_candidate_domains(req)
    second = resolve_candidate_domains(req)
    third = resolve_candidate_domains(_FakeRequirement(RequirementType.EXPERIENCE, req.description))
    assert first == second == third


# ---------------------------------------------------------------------------
# Extra: description=None doesn't crash (Requirement.description is nullable)
# ---------------------------------------------------------------------------


def test_none_description_does_not_crash_and_yields_no_hints():
    req = _FakeRequirement(RequirementType.EXPERIENCE, None)
    domains = resolve_candidate_domains(req)
    assert domains == list(CATEGORY_DOMAINS[RequirementType.EXPERIENCE])


# ---------------------------------------------------------------------------
# Critical negative test (end-to-end): additive routing must not break
# existing Project-only matching, and must genuinely widen the candidate
# set actually passed into decision_engine.match_requirement() for a real
# EXPERIENCE requirement -- not just the pure resolve_candidate_domains()
# function tested above. Records which entity_types were actually
# considered per requirement via a wrapped match_requirement, the same
# "observe real behavior, don't just assert on the pure function" spirit
# as test_decision_engine_concurrency.py's tracking client.
# ---------------------------------------------------------------------------


@pytest.fixture()
def routing_db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__, User.__table__, Mission.__table__, Tender.__table__,
            Requirement.__table__, Document.__table__, Certification.__table__,
            Employee.__table__, Project.__table__, Equipment.__table__, FinancialRecord.__table__,
            CapabilitySnapshot.__table__, Recommendation.__table__, CapabilityMapping.__table__,
            ComplianceMatrix.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class _AlwaysMetLLMClient:
    async def complete(self, system_prompt: str, user_prompt: str, purpose: str = "unspecified") -> str:
        return json.dumps({"status": "met", "matched_entity_index": 0, "reasoning": "test"})


@pytest.mark.asyncio
async def test_experience_requirements_route_to_the_expected_domains_end_to_end(routing_db, monkeypatch):
    db = routing_db
    company = Company(id=uuid.uuid4(), name="Acme Co", registration_number=str(uuid.uuid4()))
    db.add(company)
    db.flush()
    user = User(
        id=uuid.uuid4(), company_id=company.id, name="Admin", email=f"{uuid.uuid4()}@example.com",
        password_hash="x", role=UserRole.ADMINISTRATOR, status=UserStatus.ACTIVE,
    )
    db.add(user)
    mission = Mission(
        id=uuid.uuid4(), company_id=company.id, user_id=user.id,
        mission_type="tender_evaluation", status=MissionStatus.RUNNING,
    )
    db.add(mission)
    db.flush()
    tender = Tender(id=uuid.uuid4(), mission_id=mission.id, tender_name="Routing Test Tender", processing_status="completed")
    db.add(tender)
    db.flush()

    # Test 1: EXPERIENCE requirement about completed similar projects --
    # must still consider Project (unchanged base routing).
    req_project = Requirement(
        id=uuid.uuid4(), tender_id=tender.id, requirement_type=RequirementType.EXPERIENCE,
        description="Bidder shall have completed three similar works of civil construction.",
        mandatory=True, source_page=1, confidence=0.9,
    )
    # Test 2: EXPERIENCE requirement about skilled personnel / expert labour
    # -- must now also consider Employee (the fix).
    req_personnel = Requirement(
        id=uuid.uuid4(), tender_id=tender.id, requirement_type=RequirementType.EXPERIENCE,
        description="Bidder shall engage expert labour and skilled personnel for the works.",
        mandatory=True, source_page=1, confidence=0.9,
    )
    # Test 3: mixed requirement -- both domains must be available.
    req_mixed = Requirement(
        id=uuid.uuid4(), tender_id=tender.id, requirement_type=RequirementType.EXPERIENCE,
        description="Bidder shall have completed similar work using qualified personnel.",
        mandatory=True, source_page=1, confidence=0.9,
    )
    db.add_all([req_project, req_personnel, req_mixed])

    project_entity = Project(id=uuid.uuid4(), company_id=company.id, client="ACME Client", confidence_score=0.9)
    employee_entity = Employee(id=uuid.uuid4(), company_id=company.id, name="Ramesh Kumar", confidence_score=0.9)
    db.add_all([project_entity, employee_entity])
    db.commit()

    # Wrap the real match_requirement to record which entity_types were
    # actually offered as candidates per requirement, without changing
    # its behavior -- a real LLM call still can't happen in this sandbox,
    # so an always-"met" fake client stands in (same shape as
    # test_decision_engine_concurrency.py's _TrackingLLMClient).
    monkeypatch.setattr(decision_engine, "get_llm_client", lambda *_: _AlwaysMetLLMClient())

    observed_domains: dict[uuid.UUID, set[CapabilityEntityType]] = {}
    real_match_requirement = decision_engine.match_requirement

    async def _recording_match_requirement(requirement, candidates, provider=None, supported_domains=None):
        observed_domains[requirement.id] = {entity_type for entity_type, _entity in candidates}
        return await real_match_requirement(
            requirement, candidates, provider=provider, supported_domains=supported_domains
        )

    monkeypatch.setattr(decision_engine, "match_requirement", _recording_match_requirement)

    await decision_service.run_evaluation(db, mission.id, company.id)

    assert CapabilityEntityType.PROJECT in observed_domains[req_project.id]

    assert CapabilityEntityType.EMPLOYEE in observed_domains[req_personnel.id]
    assert CapabilityEntityType.PROJECT in observed_domains[req_personnel.id]  # base domain preserved

    assert CapabilityEntityType.PROJECT in observed_domains[req_mixed.id]
    assert CapabilityEntityType.EMPLOYEE in observed_domains[req_mixed.id]
