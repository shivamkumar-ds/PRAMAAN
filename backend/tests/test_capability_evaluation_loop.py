"""
End-to-end regression coverage for the "Verify capability loop end-to-end"
sub-task of the Action Center V-next work: add a capability (manually, no
document) -> it appears in the Capability Library (list_capabilities) ->
re-run evaluation (decision_service.run_evaluation, the same function
POST /evaluation/run calls) -> the resulting MatchStatus/ComplianceMatrix
for a real requirement changes -> delete (soft-remove) the capability ->
re-run evaluation again -> the change reverts.

Two domains are proven here: CERTIFICATION (always fully supported) and
EQUIPMENT. Equipment used to be a real, confirmed architecture limitation
-- decision_service.run_evaluation() derived its "supported_domains" set
from capability_service.ENTITY_MODELS, which only ever contained
{CERTIFICATION, EMPLOYEE, PROJECT} (the domains with a document-extraction
agent), so an Equipment-domain requirement was *always*
build_unsupported_coverage_result() -> REVIEW_REQUIRED / coverage_gaps,
regardless of whether an Equipment capability record existed. That's been
fixed: decision_service.py's supported_domains now derives from
capability_service.ALL_CAPABILITY_MODELS (all five domains) instead of
ENTITY_MODELS, since manual capability creation means every domain can now
have a real capability record even without a document-extraction agent --
"supported for matching" and "has an auto-extraction agent" are genuinely
different concepts, and only the latter is still true of just three
domains. Document-based building for Equipment/FinancialRecord still
doesn't exist (no agent); only manual entry does. Both loop tests below
prove the same CRUD -> match-result -> revert cycle now works identically
for both domains.
"""

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
from app.models.enums import CapabilityEntityType, MatchStatus, MissionStatus, RequirementType, UserRole, UserStatus
from app.services import capability_service, decision_service


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


@pytest.fixture()
def loop_db():
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
        return json.dumps({"status": "met", "matched_entity_index": 0, "reasoning": "Certification matches."})


def _matrix_status(db, recommendation_id, requirement_id) -> MatchStatus:
    row = (
        db.query(ComplianceMatrix)
        .filter(
            ComplianceMatrix.recommendation_id == recommendation_id,
            ComplianceMatrix.requirement_id == requirement_id,
        )
        .one()
    )
    return row.status


@pytest.mark.asyncio
async def test_manual_certification_capability_changes_match_result_and_deletion_reverts_it(loop_db, monkeypatch):
    db = loop_db
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
    tender = Tender(id=uuid.uuid4(), mission_id=mission.id, tender_name="Capability Loop Test Tender", processing_status="completed")
    db.add(tender)
    db.flush()

    requirement = Requirement(
        id=uuid.uuid4(), tender_id=tender.id, requirement_type=RequirementType.CERTIFICATION,
        description="Bidder must hold a valid ISO 9001 quality management certification.",
        mandatory=True, source_page=2, confidence=0.9,
    )
    db.add(requirement)
    db.commit()

    monkeypatch.setattr(decision_engine, "get_llm_client", lambda *_: _AlwaysMetLLMClient())

    # Step 1: no capability exists yet -- CERTIFICATION is a supported
    # domain (capability_service.ENTITY_MODELS) but zero candidate rows
    # exist, so match_requirement()'s deterministic zero-candidates branch
    # fires (no LLM call needed) -> NOT_MET.
    assert capability_service.list_capabilities(db, company.id) == []
    rec_1 = await decision_service.run_evaluation(db, mission.id, company.id)
    assert _matrix_status(db, rec_1.id, requirement.id) == MatchStatus.NOT_MET

    # Step 2: add the capability manually (POST /capabilities/manual's
    # service function -- no document, no LLM extraction) and confirm it
    # shows up in the Capability Library (list_capabilities).
    entity_type, entity = capability_service.build_capability_manual(
        db, company.id, CapabilityEntityType.CERTIFICATION,
        {"certification_name": "ISO 9001", "issuing_authority": "BSI"},
    )
    assert entity_type == CapabilityEntityType.CERTIFICATION
    graph = capability_service.list_capabilities(db, company.id)
    assert any(t == CapabilityEntityType.CERTIFICATION and e.id == entity.id for t, e in graph)

    # Step 3: re-run evaluation (POST /evaluation/run's service function)
    # -- the requirement now has a real candidate, the (mocked) LLM
    # confirms a match -> MatchStatus flips to MET.
    rec_2 = await decision_service.run_evaluation(db, mission.id, company.id)
    assert _matrix_status(db, rec_2.id, requirement.id) == MatchStatus.MET

    # Step 4: delete (soft-remove) the capability -- same effect DELETE
    # /capabilities/{id} produces via revalidation_service.handle_capability_removal
    # (capability_service.soft_remove_capability + commit), exercised
    # directly here to keep this test scoped to the capability ->
    # evaluation loop rather than the HTTP/router layer.
    capability_service.soft_remove_capability(entity)
    db.commit()
    assert capability_service.list_capabilities(db, company.id) == []

    # Step 5: re-run evaluation again -- the candidate is gone, so the
    # requirement reverts to NOT_MET, proving the loop is genuinely live
    # in both directions, not just additive.
    rec_3 = await decision_service.run_evaluation(db, mission.id, company.id)
    assert _matrix_status(db, rec_3.id, requirement.id) == MatchStatus.NOT_MET


@pytest.mark.asyncio
async def test_manual_equipment_capability_changes_match_result_and_deletion_reverts_it(loop_db, monkeypatch):
    """
    Equipment used to be permanently coverage-gapped regardless of any
    capability record (see this module's docstring). Now that
    decision_service.py derives supported_domains from
    ALL_CAPABILITY_MODELS, this proves the exact same CRUD -> match-result
    -> revert loop the CERTIFICATION test above proves, but for the
    domain that was previously broken -- this is the machinery/equipment
    scenario that motivated the fix.
    """
    db = loop_db
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
    tender = Tender(id=uuid.uuid4(), mission_id=mission.id, tender_name="Equipment Loop Test Tender", processing_status="completed")
    db.add(tender)
    db.flush()

    # TECHNICAL requirement_type routes to [Equipment, Employee, Project]
    # per CATEGORY_DOMAINS -- with no Employee/Project candidates either,
    # this requirement is entirely dependent on the Equipment domain.
    requirement = Requirement(
        id=uuid.uuid4(), tender_id=tender.id, requirement_type=RequirementType.TECHNICAL,
        description="Bidder must have an excavator available for site work.",
        mandatory=True, source_page=4, confidence=0.9,
    )
    db.add(requirement)
    db.commit()

    monkeypatch.setattr(decision_engine, "get_llm_client", lambda *_: _AlwaysMetLLMClient())

    # Step 1: no capability exists yet. Equipment is now a supported
    # domain, but zero candidates exist -> NOT_MET, not a coverage gap --
    # this is the key behavior change from the old REVIEW_REQUIRED result.
    assert capability_service.list_capabilities(db, company.id) == []
    rec_1 = await decision_service.run_evaluation(db, mission.id, company.id)
    assert _matrix_status(db, rec_1.id, requirement.id) == MatchStatus.NOT_MET

    # Step 2: add the Equipment capability manually -- this previously had
    # no creation path at all (see test_manual_capability_creation.py).
    entity_type, entity = capability_service.build_capability_manual(
        db, company.id, CapabilityEntityType.EQUIPMENT, {"equipment_name": "Excavator", "quantity": 2},
    )
    assert entity_type == CapabilityEntityType.EQUIPMENT
    graph = capability_service.list_capabilities(db, company.id)
    assert any(t == CapabilityEntityType.EQUIPMENT and e.id == entity.id for t, e in graph)

    # Step 3: re-run evaluation -- Equipment is now supported_domains, the
    # requirement has a real candidate, the (mocked) LLM confirms a match.
    rec_2 = await decision_service.run_evaluation(db, mission.id, company.id)
    assert _matrix_status(db, rec_2.id, requirement.id) == MatchStatus.MET

    # Step 4: delete the capability.
    capability_service.soft_remove_capability(entity)
    db.commit()
    assert capability_service.list_capabilities(db, company.id) == []

    # Step 5: re-run -- reverts to NOT_MET (not back to a coverage gap),
    # proving the loop is genuinely live in both directions for Equipment
    # exactly as it already was for Certification.
    rec_3 = await decision_service.run_evaluation(db, mission.id, company.id)
    assert _matrix_status(db, rec_3.id, requirement.id) == MatchStatus.NOT_MET
