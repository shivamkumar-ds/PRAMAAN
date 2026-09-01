"""
Regression coverage for Company profile editing (PATCH /company/{id}) --
the gap Settings.tsx's OrganizationSection had documented since it was
first built: organization name/industry/country were readable everywhere
but editable nowhere, for any role, since RC-1 audit finding A1 removed
the old unauthenticated POST /company entirely.

Two layers, matching the project's existing split:
- test_company_service.py-style unit tests below (`update_company`
  itself) cover partial-update semantics against a real in-memory DB
  session.
- HTTP-layer tests (RBAC + tenant isolation) use a real FastAPI
  TestClient against the actual app, same pattern as
  test_contact_api.py -- these concerns (403 for a non-Administrator,
  404 for another tenant's company) only exist at the router level and
  can't be exercised by calling company_service directly.
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
from app.models import Company, User
from app.models.enums import UserRole, UserStatus
from app.services import company_service
from app.services.exceptions import NotFoundError


# ---------------------------------------------------------------------------
# Service-layer: company_service.update_company()
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[Company.__table__, User.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_company(db, **overrides):
    defaults = dict(id=uuid.uuid4(), name="Acme", industry="Construction", registration_number=str(uuid.uuid4()), country="India")
    defaults.update(overrides)
    company = Company(**defaults)
    db.add(company)
    db.commit()
    return company


def test_partial_update_only_touches_provided_fields(db):
    company = _make_company(db)
    updated = company_service.update_company(db, company.id, {"industry": "Manufacturing"})
    assert updated.industry == "Manufacturing"
    assert updated.name == "Acme"  # untouched
    assert updated.country == "India"  # untouched


def test_explicit_null_clears_a_genuinely_nullable_field(db):
    company = _make_company(db)
    updated = company_service.update_company(db, company.id, {"industry": None})
    assert updated.industry is None


def test_explicit_null_name_is_ignored_not_applied(db):
    """`name` is non-nullable on the model -- a defensive no-op, not an
    IntegrityError, per company_service.update_company()'s docstring."""
    company = _make_company(db, name="Acme")
    updated = company_service.update_company(db, company.id, {"name": None})
    assert updated.name == "Acme"


def test_registration_number_is_not_a_settable_field():
    """CompanyUpdate has no registration_number field at all -- proven at
    the schema level, not the service level, since the service just
    applies whatever dict it's given; a client attempting to send it
    would have it silently dropped by Pydantic before it ever reaches
    the service."""
    from app.schemas.company import CompanyUpdate

    assert "registration_number" not in CompanyUpdate.model_fields


def test_update_nonexistent_company_raises_not_found(db):
    with pytest.raises(NotFoundError):
        company_service.update_company(db, uuid.uuid4(), {"name": "Whatever"})


# ---------------------------------------------------------------------------
# HTTP layer: PATCH /api/v1/company/{id} -- RBAC + tenant isolation
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[Company.__table__, User.__table__])
    TestSession = sessionmaker(bind=engine)

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    # Same reasoning as test_contact_api.py's client fixture -- the real
    # startup lifespan's migration guard targets real Postgres, which
    # doesn't exist in this test environment.
    monkeypatch.setattr(main_module.settings, "migration_guard_enabled", False)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.pop(get_db, None)


def _seed(db_session, role=UserRole.ADMINISTRATOR):
    company = Company(id=uuid.uuid4(), name="Acme", registration_number=str(uuid.uuid4()))
    db_session.add(company)
    db_session.flush()
    user = User(
        id=uuid.uuid4(), company_id=company.id, name="Test User", email=f"{uuid.uuid4()}@example.com",
        password_hash="irrelevant", role=role, status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    db_session.commit()
    return company, user


def _seeded_session(engine_client):
    """Pulls a session bound to the same in-memory engine the client's
    dependency override uses, so seeded rows are visible to the app."""
    override = engine_client.app.dependency_overrides[get_db]
    gen = override()
    return next(gen)


def _auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_administrator_can_update_own_company(client):
    db_session = _seeded_session(client)
    company, admin = _seed(db_session, role=UserRole.ADMINISTRATOR)

    res = client.patch(f"/api/v1/company/{company.id}", json={"industry": "Infrastructure"}, headers=_auth_headers(admin))
    assert res.status_code == 200
    assert res.json()["industry"] == "Infrastructure"


def test_non_administrator_gets_403(client):
    db_session = _seeded_session(client)
    company, reviewer = _seed(db_session, role=UserRole.REVIEWER)

    res = client.patch(f"/api/v1/company/{company.id}", json={"industry": "Infrastructure"}, headers=_auth_headers(reviewer))
    assert res.status_code == 403


def test_administrator_cannot_update_another_tenants_company(client):
    db_session = _seeded_session(client)
    _own_company, admin = _seed(db_session, role=UserRole.ADMINISTRATOR)
    other_company, _other_admin = _seed(db_session, role=UserRole.ADMINISTRATOR)

    res = client.patch(f"/api/v1/company/{other_company.id}", json={"industry": "Infrastructure"}, headers=_auth_headers(admin))
    assert res.status_code == 404


def test_registration_number_in_payload_is_silently_ignored(client):
    db_session = _seeded_session(client)
    company, admin = _seed(db_session, role=UserRole.ADMINISTRATOR)
    original_reg_number = company.registration_number

    res = client.patch(
        f"/api/v1/company/{company.id}",
        json={"registration_number": "SHOULD-NOT-APPLY", "name": "Acme Renamed"},
        headers=_auth_headers(admin),
    )
    assert res.status_code == 200
    assert res.json()["registration_number"] == original_reg_number
    assert res.json()["name"] == "Acme Renamed"


def test_unauthenticated_request_returns_401(client):
    db_session = _seeded_session(client)
    company, _admin = _seed(db_session)
    res = client.patch(f"/api/v1/company/{company.id}", json={"industry": "Infrastructure"})
    assert res.status_code == 401
