"""
Regression coverage for the recommendation_type staleness bug.

Root cause (see the fix in app/api/v1/evaluation.py::_build_response):
remediation_summary was already recomputed live on every GET (via
decision_engine.classify_remediation()), correctly reflecting
confirmations. But the top-level `recommendation.recommendation_type`
field was a raw copy of the PERSISTED Recommendation row from the last
POST /evaluation/run -- frozen at run time, before any confirmation
existed, and confirm/unconfirm deliberately never re-runs evaluation
(expensive, LLM-driven matching must not fire on a cheap confirm click).

These tests prove, at the HTTP layer, purely via GET /evaluation/{mission_id}
after a confirm/unconfirm (no new POST /evaluation/run):
1. Confirming the one mandatory SUBMISSION_GATING blocker resolves
   recommendation_type from CONDITIONAL_GO (persisted, BLOCKED-driven) to
   GO (live, READY-driven) -- qualification stays PASS throughout, only
   the readiness axis moves.
2. Unconfirming reverses it back to CONDITIONAL_GO.
3. The persisted `recommendations` table row's recommendation_type is
   NEVER mutated by confirm/unconfirm -- queried directly from the DB,
   it stays CONDITIONAL_GO throughout, proving the live value is an
   API-response-only override, not a write-back.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app.models import (
    BidReadinessConfirmation,
    Company,
    ComplianceMatrix,
    Mission,
    QualificationOverride,
    Recommendation,
    Requirement,
    Tender,
    User,
)
from app.models.enums import (
    MatchStatus,
    MissionStatus,
    RecommendationType,
    RequirementNature,
    RequirementType,
    RiskLevel,
    UserRole,
    UserStatus,
)

ALL_TABLES = [
    Company.__table__, User.__table__, Mission.__table__, Tender.__table__,
    Requirement.__table__, Recommendation.__table__, ComplianceMatrix.__table__,
    BidReadinessConfirmation.__table__, QualificationOverride.__table__,
]


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=ALL_TABLES)
    TestSession = sessionmaker(bind=engine)

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    monkeypatch.setattr(main_module.settings, "migration_guard_enabled", False)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.pop(get_db, None)


def _seeded_session(engine_client):
    override = engine_client.app.dependency_overrides[get_db]
    gen = override()
    return next(gen)


def _auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _seed_scenario(db_session):
    """
    One mandatory SUBMISSION_GATING requirement, unresolved
    (REVIEW_REQUIRED) -- the only unresolved item in the mission, and no
    CAPABILITY_CLAIM issues at all, so qualification == PASS throughout.
    Readiness == BLOCKED before confirmation (mandatory gating item
    unresolved) -> READY after (the only blocker is confirmed).

    Persisted Recommendation.recommendation_type is seeded as
    CONDITIONAL_GO -- exactly what compute_recommendation_type() would
    have produced at the moment evaluation last actually ran (qualification
    PASS, readiness BLOCKED -> CONDITIONAL_GO, per decision_engine.
    compute_recommendation_type()'s docstring).
    """
    company = Company(id=uuid.uuid4(), name="Acme", registration_number=str(uuid.uuid4()))
    db_session.add(company)
    db_session.flush()
    user = User(
        id=uuid.uuid4(), company_id=company.id, name="Admin", email=f"{uuid.uuid4()}@example.com",
        password_hash="x", role=UserRole.ADMINISTRATOR, status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    db_session.flush()
    mission = Mission(
        id=uuid.uuid4(), company_id=company.id, user_id=user.id,
        mission_type="tender_evaluation", status=MissionStatus.AWAITING_APPROVAL,
    )
    db_session.add(mission)
    db_session.flush()
    tender = Tender(id=uuid.uuid4(), mission_id=mission.id, tender_name="T")
    db_session.add(tender)
    db_session.flush()

    requirement = Requirement(
        id=uuid.uuid4(), tender_id=tender.id, requirement_type=RequirementType.ELIGIBILITY,
        requirement_nature=RequirementNature.SUBMISSION_GATING, mandatory=True,
        description="EMD deposit must be submitted with the bid.",
    )
    db_session.add(requirement)
    db_session.flush()

    recommendation = Recommendation(
        id=uuid.uuid4(), mission_id=mission.id,
        recommendation_type=RecommendationType.CONDITIONAL_GO,
        executive_summary="Persisted at last run.", risk_level=RiskLevel.HIGH,
        document_confidence=0.9, entity_confidence=0.9, matching_confidence=0.9,
        recommendation_confidence=0.9, overall_confidence=0.9,
    )
    db_session.add(recommendation)
    db_session.flush()
    mission.recommendation_id = recommendation.id

    compliance_row = ComplianceMatrix(
        id=uuid.uuid4(), recommendation_id=recommendation.id, requirement_id=requirement.id,
        status=MatchStatus.REVIEW_REQUIRED, supporting_evidence="", notes="",
        matching_confidence=0.9,
    )
    db_session.add(compliance_row)
    db_session.commit()
    return company, user, mission, requirement, recommendation


def test_confirm_then_get_live_recomputes_recommendation_type_without_new_run(client):
    db_session = _seeded_session(client)
    _company, admin, mission, requirement, recommendation = _seed_scenario(db_session)

    # Before confirmation: GET reflects the persisted, BLOCKED-driven
    # CONDITIONAL_GO -- live computation agrees with the persisted value
    # because nothing has changed yet.
    res_before = client.get(f"/api/v1/evaluation/{mission.id}", headers=_auth_headers(admin))
    assert res_before.status_code == 200, res_before.text
    assert res_before.json()["recommendation"]["recommendation_type"] == "conditional_go"
    assert res_before.json()["remediation_summary"]["bid_readiness"] == "blocked"

    # Confirm the one mandatory gating blocker -- no POST /evaluation/run.
    confirm_res = client.post(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/confirm",
        json={"note": "EMD deposited"},
        headers=_auth_headers(admin),
    )
    assert confirm_res.status_code == 201, confirm_res.text

    # GET again, still no new evaluation run: recommendation_type must now
    # be live-recomputed to GO (qualification PASS, readiness now READY).
    res_after = client.get(f"/api/v1/evaluation/{mission.id}", headers=_auth_headers(admin))
    assert res_after.status_code == 200, res_after.text
    assert res_after.json()["recommendation"]["recommendation_type"] == "go"
    assert res_after.json()["remediation_summary"]["bid_readiness"] == "ready"

    # The persisted `recommendations` row itself must NOT have been
    # mutated -- queried directly, independent of the API response.
    db_session.refresh(recommendation)
    assert recommendation.recommendation_type == RecommendationType.CONDITIONAL_GO

    # Same result via GET /recommendations/{mission_id} and via the
    # response of a subsequent confirm-triggered refetch -- all three
    # read endpoints funnel through the same _build_response(), so the
    # recommendations-router alias must agree.
    res_alias = client.get(f"/api/v1/recommendations/{mission.id}", headers=_auth_headers(admin))
    assert res_alias.status_code == 200
    assert res_alias.json()["recommendation"]["recommendation_type"] == "go"

    # Unconfirm reverses it back to CONDITIONAL_GO, still purely from GET.
    unconfirm_res = client.delete(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/confirm",
        headers=_auth_headers(admin),
    )
    assert unconfirm_res.status_code == 204

    res_reverted = client.get(f"/api/v1/evaluation/{mission.id}", headers=_auth_headers(admin))
    assert res_reverted.status_code == 200
    assert res_reverted.json()["recommendation"]["recommendation_type"] == "conditional_go"
    assert res_reverted.json()["remediation_summary"]["bid_readiness"] == "blocked"

    # Persisted row is still untouched after the unconfirm round-trip too.
    db_session.refresh(recommendation)
    assert recommendation.recommendation_type == RecommendationType.CONDITIONAL_GO
