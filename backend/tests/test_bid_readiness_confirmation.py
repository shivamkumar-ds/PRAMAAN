"""
Regression coverage for the bid-readiness confirmation feature
(BidReadinessConfirmation, app/models/bid_readiness.py).

Covers, per the frozen design's own required test list:
- compute_bid_readiness() with confirmed_requirement_ids resolving a
  mandatory SUBMISSION_GATING gating item (BLOCKED -> not BLOCKED).
- compute_qualification() remaining completely unaffected by
  confirmations -- the frozen boundary rule: capability_claim gaps can
  only be resolved by real evidence, never a confirmation checkbox. A
  confirmed CAPABILITY_CLAIM-style item (mistakenly passed) must NOT
  resolve qualification.
- POST/DELETE /missions/{mission_id}/requirements/{requirement_id}/confirm
  HTTP-layer: admin gating, ownership checks (wrong mission, wrong
  company), and double-confirm/double-unconfirm conflict handling.
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
    compute_bid_readiness,
    compute_qualification,
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
    matched_entity_type: CapabilityEntityType | None = None,
) -> MatchResult:
    return MatchResult(
        requirement_id=requirement_id or uuid.uuid4(),
        requirement_type=RequirementType.ELIGIBILITY,
        requirement_nature=nature,
        mandatory=mandatory,
        status=status,
        matched_entity_type=matched_entity_type,
        matched_entity_id=None,
        matching_confidence=0.9,
        supporting_evidence="",
        notes="",
    )


# ---------------------------------------------------------------------------
# Pure decision_engine unit tests
# ---------------------------------------------------------------------------


def test_confirmed_mandatory_gating_item_resolves_blocked_to_ready():
    req_id = uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.SUBMISSION_GATING, mandatory=True,
            status=MatchStatus.REVIEW_REQUIRED, requirement_id=req_id,
        )
    ]
    assert compute_bid_readiness(results) == ReadinessStatus.BLOCKED
    assert compute_bid_readiness(results, frozenset({req_id})) == ReadinessStatus.READY


def test_confirmed_future_contractual_commitment_item_resolves_action_required():
    req_id = uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.FUTURE_CONTRACTUAL_COMMITMENT, mandatory=True,
            status=MatchStatus.REVIEW_REQUIRED, requirement_id=req_id,
        )
    ]
    assert compute_bid_readiness(results) == ReadinessStatus.ACTION_REQUIRED
    assert compute_bid_readiness(results, frozenset({req_id})) == ReadinessStatus.READY


def test_confirming_one_of_two_mandatory_gating_items_still_blocked():
    """A confirmation only resolves the specific requirement_id it names --
    a second, unconfirmed mandatory gating item still blocks readiness."""
    confirmed_id, other_id = uuid.uuid4(), uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.SUBMISSION_GATING, mandatory=True,
            status=MatchStatus.REVIEW_REQUIRED, requirement_id=confirmed_id,
        ),
        _result(
            nature=RequirementNature.SUBMISSION_GATING, mandatory=True,
            status=MatchStatus.REVIEW_REQUIRED, requirement_id=other_id,
        ),
    ]
    assert compute_bid_readiness(results, frozenset({confirmed_id})) == ReadinessStatus.BLOCKED


def test_confirmation_never_resolves_procedural_items():
    """PROCEDURAL is deliberately excluded from the confirmation escape
    hatch -- deadlines/evaluation-criteria/submission-format items always
    need a fresh bid-team look regardless of a prior confirmation."""
    req_id = uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.PROCEDURAL, mandatory=True,
            status=MatchStatus.REVIEW_REQUIRED, requirement_id=req_id,
        )
    ]
    assert compute_bid_readiness(results, frozenset({req_id})) == ReadinessStatus.ACTION_REQUIRED


def test_qualification_boundary_confirmation_never_resolves_capability_claim():
    """The frozen boundary rule: compute_qualification() is NEVER touched
    by bid-readiness CONFIRMATIONS specifically. Even if a CAPABILITY_CLAIM
    item's requirement_id is (mistakenly) passed as 'confirmed',
    compute_qualification() has no confirmed_requirement_ids parameter at
    all -- there is no code path by which a confirmation (as opposed to an
    explicit qualification OVERRIDE -- a deliberately separate, later
    feature, see test_qualification_override.py) can resolve a
    qualification gap. Proven two ways: (1) calling with
    confirmed_requirement_ids by keyword is a TypeError, since no such
    parameter exists on this function's signature, (2) FAIL persists when
    called with no override either.

    Note: compute_qualification() DOES now accept a second positional
    parameter, overridden_requirement_ids -- that is the qualification
    override feature's own, intentional escape hatch (a real, audited
    administrator decision, distinct from a plain confirmation checkbox),
    not a regression of this boundary. This test proves the boundary that
    still holds: confirmed_requirement_ids (bid-readiness confirmation)
    specifically has no path into this function, by name or by concept.
    """
    req_id = uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True,
            status=MatchStatus.NOT_MET, requirement_id=req_id,
        )
    ]
    # compute_qualification() has no confirmed_requirement_ids parameter --
    # calling it with one BY KEYWORD is a TypeError, proving no such
    # escape hatch exists in its signature at all (positionally, that slot
    # is now overridden_requirement_ids -- a different, intentional param).
    with pytest.raises(TypeError):
        compute_qualification(results, confirmed_requirement_ids=frozenset({req_id}))  # type: ignore[call-arg]

    assert compute_qualification(results) == QualificationStatus.FAIL
    # And passing the same id as an override (not a confirmation) DOES
    # resolve it -- proving the two are genuinely different mechanisms,
    # not the same escape hatch under a new name.
    assert compute_qualification(results, frozenset({req_id})) == QualificationStatus.PASS


def test_qualification_still_fail_regardless_of_bid_readiness_confirmations():
    """A mission with both a confirmed gating item AND a genuine mandatory
    capability failure: readiness improves, qualification does not."""
    gating_id, capability_id = uuid.uuid4(), uuid.uuid4()
    results = [
        _result(
            nature=RequirementNature.SUBMISSION_GATING, mandatory=True,
            status=MatchStatus.REVIEW_REQUIRED, requirement_id=gating_id,
        ),
        _result(
            nature=RequirementNature.CAPABILITY_CLAIM, mandatory=True,
            status=MatchStatus.NOT_MET, requirement_id=capability_id,
        ),
    ]
    confirmed = frozenset({gating_id})
    assert compute_bid_readiness(results, confirmed) == ReadinessStatus.READY
    assert compute_qualification(results) == QualificationStatus.FAIL


# ---------------------------------------------------------------------------
# HTTP layer: POST/DELETE /missions/{mission_id}/requirements/{requirement_id}/confirm
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
        requirement_nature=RequirementNature.SUBMISSION_GATING, mandatory=True,
    )
    db_session.add(requirement)
    db_session.commit()
    return company, user, mission, requirement


def test_administrator_can_confirm_and_unconfirm(client):
    db_session = _seeded_session(client)
    _company, admin, mission, requirement = _seed_mission_with_requirement(db_session)

    res = client.post(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/confirm",
        json={"note": "EMD deposited"},
        headers=_auth_headers(admin),
    )
    assert res.status_code == 201, res.text
    assert res.json()["requirement_id"] == str(requirement.id)
    assert res.json()["note"] == "EMD deposited"

    res2 = client.delete(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/confirm",
        headers=_auth_headers(admin),
    )
    assert res2.status_code == 204


def test_non_administrator_cannot_confirm(client):
    db_session = _seeded_session(client)
    _company, reviewer, mission, requirement = _seed_mission_with_requirement(db_session, role=UserRole.REVIEWER)

    res = client.post(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/confirm",
        headers=_auth_headers(reviewer),
    )
    assert res.status_code == 403


def test_double_confirm_is_conflict(client):
    db_session = _seeded_session(client)
    _company, admin, mission, requirement = _seed_mission_with_requirement(db_session)

    res1 = client.post(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/confirm",
        headers=_auth_headers(admin),
    )
    assert res1.status_code == 201
    res2 = client.post(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/confirm",
        headers=_auth_headers(admin),
    )
    assert res2.status_code == 409


def test_unconfirm_without_existing_confirmation_is_not_found(client):
    db_session = _seeded_session(client)
    _company, admin, mission, requirement = _seed_mission_with_requirement(db_session)

    res = client.delete(
        f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/confirm",
        headers=_auth_headers(admin),
    )
    assert res.status_code == 404


def test_cannot_confirm_requirement_belonging_to_another_mission(client):
    """Ownership check: requirement_id is real and belongs to this
    company, but not to the mission_id in the path."""
    db_session = _seeded_session(client)
    _company, admin, _mission_a, requirement_a = _seed_mission_with_requirement(db_session)

    # A second mission for the same company/admin.
    mission_b = Mission(
        id=uuid.uuid4(), company_id=_company.id, user_id=admin.id,
        mission_type="tender_evaluation", status=MissionStatus.AWAITING_APPROVAL,
    )
    db_session.add(mission_b)
    db_session.commit()

    res = client.post(
        f"/api/v1/missions/{mission_b.id}/requirements/{requirement_a.id}/confirm",
        headers=_auth_headers(admin),
    )
    assert res.status_code == 404


def test_cannot_confirm_requirement_via_another_companys_mission(client):
    """Ownership check: the mission_id belongs to a different company
    than the authenticated admin's own -- mission_service.get_mission()
    itself raises NotFoundError for cross-tenant access."""
    db_session = _seeded_session(client)
    _company_a, _admin_a, _mission_a, requirement_a = _seed_mission_with_requirement(db_session)
    _company_b, admin_b, mission_b, _requirement_b = _seed_mission_with_requirement(db_session)

    res = client.post(
        f"/api/v1/missions/{mission_b.id}/requirements/{requirement_a.id}/confirm",
        headers=_auth_headers(admin_b),
    )
    assert res.status_code == 404


def test_unauthenticated_confirm_returns_401(client):
    db_session = _seeded_session(client)
    _company, _admin, mission, requirement = _seed_mission_with_requirement(db_session)

    res = client.post(f"/api/v1/missions/{mission.id}/requirements/{requirement.id}/confirm")
    assert res.status_code == 401
