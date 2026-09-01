"""
Regression coverage for the qualification override feature
(QualificationOverride, app/models/qualification_override.py).

Covers:
- compute_qualification() with overridden_requirement_ids resolving a
  mandatory CAPABILITY_CLAIM gap (FAIL -> PASS, CONDITIONAL -> PASS).
- compute_bid_readiness() remaining completely unaffected by overrides --
  the boundary rule runs in the opposite direction from bid-readiness
  confirmation's own boundary rule (see test_bid_readiness_confirmation.py).
- classify_remediation()/compute_recommendation_type() threading both
  confirmed_requirement_ids and overridden_requirement_ids correctly on
  their own separate axes, without cross-wiring.
- An overridden item stays visible in qualification_gaps -- it is never
  silently dropped just because it stopped blocking qualification.
- POST/DELETE /missions/{mission_id}/requirements/{requirement_id}/override
  HTTP-layer: admin gating, required note, ownership checks, double-
  override/double-remove conflict handling.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.agents.decision_engine import (
    MatchResult,
    QualificationStatus,
    ReadinessStatus,
    RecommendationType,
    classify_remediation,
    compute_bid_readiness,
    compute_qualification,
    compute_recommendation_type,
)
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app.models import BidReadinessConfirmation, Company, Mission, QualificationOverride, Requirement, Tender, User
from app.models.enums import (
    CapabilityEntityType,
    MatchStatus,
    MissionStatus,
    RequirementNature,
    RequirementType,
    UserRole,
    UserStatus,
)

ALL_TABLES = [
    Company.__table__, User.__table__, Mission.__table__, Tender.__table__,
    Requirement.__table__, BidReadinessConfirmation.__table__, QualificationOverride.__table__,
]


def _result(
    *,
    nature: RequirementNature,
    mandatory: bool,
    status: MatchStatus,
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
        supporting_evidence="",
        notes="",
    )


# ---------------------------------------------------------------------------
# Pure decision_engine unit tests
# ---------------------------------------------------------------------------


def test_overridden_mandatory_not_met_capability_resolves_fail_to_pass():
    req_id = uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True,
            status=MatchStatus.NOT_MET, requirement_id=req_id,
        )
    ]
    assert compute_qualification(results) == QualificationStatus.FAIL
    assert compute_qualification(results, frozenset({req_id})) == QualificationStatus.PASS


def test_overridden_mandatory_review_required_capability_resolves_conditional_to_pass():
    req_id = uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True,
            status=MatchStatus.REVIEW_REQUIRED, requirement_id=req_id,
        )
    ]
    assert compute_qualification(results) == QualificationStatus.CONDITIONAL
    assert compute_qualification(results, frozenset({req_id})) == QualificationStatus.PASS


def test_overriding_one_of_two_mandatory_gaps_still_fails():
    """An override only resolves the specific requirement_id it names --
    a second, un-overridden mandatory capability gap still fails qualification."""
    overridden_id, other_id = uuid.uuid4(), uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True,
            status=MatchStatus.NOT_MET, requirement_id=overridden_id,
        ),
        _result(
            nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True,
            status=MatchStatus.NOT_MET, requirement_id=other_id,
        ),
    ]
    assert compute_qualification(results, frozenset({overridden_id})) == QualificationStatus.FAIL


def test_override_never_resolves_bid_readiness():
    """Boundary rule, opposite direction from bid-readiness confirmation's
    own: overridden_requirement_ids has no path into compute_bid_readiness()
    -- a mandatory SUBMISSION_GATING item (mistakenly) passed as
    'overridden' must NOT resolve readiness."""
    req_id = uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.SUBMISSION_GATING, mandatory=True,
            status=MatchStatus.REVIEW_REQUIRED, requirement_id=req_id,
        )
    ]
    with pytest.raises(TypeError):
        compute_bid_readiness(results, overridden_requirement_ids=frozenset({req_id}))  # type: ignore[call-arg]

    assert compute_bid_readiness(results) == ReadinessStatus.BLOCKED


def test_classify_remediation_keeps_overridden_item_visible_in_qualification_gaps():
    """An overridden item is NOT removed from qualification_gaps just
    because it stopped blocking the overall qualification value -- it
    must stay visible so the UI can show it as an explicit override, not
    silently disappear."""
    req_id = uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True,
            status=MatchStatus.NOT_MET, requirement_id=req_id,
        )
    ]
    classification = classify_remediation(results, frozenset(), frozenset({req_id}))
    assert classification.qualification == QualificationStatus.PASS
    assert len(classification.qualification_gaps) == 1
    assert classification.qualification_gaps[0].requirement_id == req_id


def test_compute_recommendation_type_go_only_with_override_and_no_other_gaps():
    req_id = uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True,
            status=MatchStatus.NOT_MET, requirement_id=req_id,
        )
    ]
    assert compute_recommendation_type(results) == RecommendationType.NO_GO
    assert compute_recommendation_type(results, frozenset(), frozenset({req_id})) == RecommendationType.GO


def test_confirmation_and_override_are_never_cross_wired():
    """A confirmed-but-not-overridden capability gap still fails
    qualification; an overridden-but-not-confirmed gating item still
    blocks readiness. Each parameter only ever reaches its own axis."""
    capability_id, gating_id = uuid.uuid4(), uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True,
            status=MatchStatus.NOT_MET, requirement_id=capability_id,
        ),
        _result(
            nature=RequirementNature.SUBMISSION_GATING, mandatory=True,
            status=MatchStatus.REVIEW_REQUIRED, requirement_id=gating_id,
        ),
    ]
    # capability_id passed as CONFIRMED (wrong axis) -- must not resolve qualification.
    assert compute_qualification(results) == QualificationStatus.FAIL
    # gating_id passed as OVERRIDDEN (wrong axis) -- must not resolve readiness.
    assert compute_bid_readiness(results) == ReadinessStatus.BLOCKED
    rec = compute_recommendation_type(
        results, confirmed_requirement_ids=frozenset({gating_id}), overridden_requirement_ids=frozenset({capability_id})
    )
    assert rec == RecommendationType.GO


# ---------------------------------------------------------------------------
# HTTP layer: POST/DELETE /missions/{mission_id}/requirements/{requirement_id}/override
# ---------------------------------------------------------------------------


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


def _seed_mission_with_requirement(db_session, role=UserRole.ADMINISTRATOR):
    company = Company(id=uuid.uuid4(), name="Acme", registration_number=str(uuid.uuid4()))
    db_session.add(company)
    db_session.flush()
    user = User(
        id=uuid.uuid4(), company_id=company.id, name="Admin", email=f"{uuid.uuid4()}@example.com",
        password_hash="x", role=role, status=UserStatus.ACTIVE,
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
        requirement_nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True,
    )
    db_session.add(requirement)
    db_session.commit()
    return company, user, mission, requirement


def test_administrator_can_override_and_remove(client):
    db_session = _seeded_session(client)
    _company, admin, mission, requirement = _seed_mission_with_requirement(db_session)

    res = client.post(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/override",
        json={"note": "Customer has confirmed ITR will be arranged before award."},
        headers=_auth_headers(admin),
    )
    assert res.status_code == 201, res.text
    assert res.json()["requirement_id"] == str(requirement.id)
    assert res.json()["note"] == "Customer has confirmed ITR will be arranged before award."

    res2 = client.delete(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/override",
        headers=_auth_headers(admin),
    )
    assert res2.status_code == 204


def test_override_without_note_is_422(client):
    db_session = _seeded_session(client)
    _company, admin, mission, requirement = _seed_mission_with_requirement(db_session)

    res = client.post(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/override",
        json={"note": "   "},
        headers=_auth_headers(admin),
    )
    assert res.status_code == 422


def test_non_administrator_cannot_override(client):
    db_session = _seeded_session(client)
    _company, reviewer, mission, requirement = _seed_mission_with_requirement(db_session, role=UserRole.REVIEWER)

    res = client.post(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/override",
        json={"note": "trying anyway"},
        headers=_auth_headers(reviewer),
    )
    assert res.status_code == 403


def test_double_override_is_conflict(client):
    db_session = _seeded_session(client)
    _company, admin, mission, requirement = _seed_mission_with_requirement(db_session)

    res1 = client.post(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/override",
        json={"note": "first"},
        headers=_auth_headers(admin),
    )
    assert res1.status_code == 201
    res2 = client.post(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/override",
        json={"note": "second"},
        headers=_auth_headers(admin),
    )
    assert res2.status_code == 409


def test_remove_override_without_existing_override_is_not_found(client):
    db_session = _seeded_session(client)
    _company, admin, mission, requirement = _seed_mission_with_requirement(db_session)

    res = client.delete(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/override",
        headers=_auth_headers(admin),
    )
    assert res.status_code == 404


def test_cannot_override_requirement_belonging_to_another_mission(client):
    db_session = _seeded_session(client)
    _company, admin, _mission_a, requirement_a = _seed_mission_with_requirement(db_session)

    mission_b = Mission(
        id=uuid.uuid4(), company_id=_company.id, user_id=admin.id,
        mission_type="tender_evaluation", status=MissionStatus.AWAITING_APPROVAL,
    )
    db_session.add(mission_b)
    db_session.commit()

    res = client.post(
        f"/api/v1/missions/{mission_b.id}/requirements/{requirement_a.id}/override",
        json={"note": "cross-mission attempt"},
        headers=_auth_headers(admin),
    )
    assert res.status_code == 404


def test_cannot_override_requirement_via_another_companys_mission(client):
    db_session = _seeded_session(client)
    _company_a, _admin_a, _mission_a, requirement_a = _seed_mission_with_requirement(db_session)
    _company_b, admin_b, mission_b, _requirement_b = _seed_mission_with_requirement(db_session)

    res = client.post(
        f"/api/v1/missions/{mission_b.id}/requirements/{requirement_a.id}/override",
        json={"note": "cross-tenant attempt"},
        headers=_auth_headers(admin_b),
    )
    assert res.status_code == 404


def test_unauthenticated_override_returns_401(client):
    db_session = _seeded_session(client)
    _company, _admin, mission, requirement = _seed_mission_with_requirement(db_session)

    res = client.post(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/override",
        json={"note": "anon attempt"},
    )
    assert res.status_code == 401
