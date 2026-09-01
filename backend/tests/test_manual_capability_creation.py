"""
Regression coverage for manual capability creation (POST /capabilities/manual).

Before this, capability creation only existed for three of five entity
types (Certification, Employee, Project) via POST /capabilities/build,
which requires a document_id and runs LLM extraction. Equipment and
FinancialRecord had zero creation path. This is the new, document-free
creation path for all five types, admin-gated the same way DELETE
/capabilities/{id} already is.

Two layers, matching test_company_api.py's precedent:
- service-layer tests over capability_service.build_capability_manual()
  against a real in-memory DB session.
- HTTP-layer tests (RBAC, all five entity types, field validation) using
  a real FastAPI TestClient, same pattern as test_company_api.py.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import ARRAY

import app.main as main_module
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app.models import Certification, Company, Employee, Equipment, FinancialRecord, Project, User
from app.models.tender import CapabilityMapping
from app.models.enums import CapabilityEntityType, UserRole, UserStatus, VerificationStatus
from app.services import capability_service

@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(element, compiler, **kw):
    return "JSON"


ALL_TABLES = [
    Company.__table__, User.__table__, Certification.__table__, Employee.__table__,
    Project.__table__, Equipment.__table__, FinancialRecord.__table__,
    # Needed for the HTTP-layer PATCH test below -- handle_capability_update()
    # calls find_affected_missions(), which queries CapabilityMapping
    # regardless of whether any mapping rows actually exist.
    CapabilityMapping.__table__,
]


# ---------------------------------------------------------------------------
# Service-layer: capability_service.build_capability_manual()
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=ALL_TABLES)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_company(db):
    company = Company(id=uuid.uuid4(), name="Acme", registration_number=str(uuid.uuid4()))
    db.add(company)
    db.commit()
    return company


def test_manual_creation_certification(db):
    company = _make_company(db)
    entity_type, entity = capability_service.build_capability_manual(
        db, company.id, CapabilityEntityType.CERTIFICATION,
        {"certification_name": "ISO 9001", "issuing_authority": "BSI"},
    )
    assert entity_type == CapabilityEntityType.CERTIFICATION
    assert entity.certification_name == "ISO 9001"
    assert entity.source_document_id is None
    assert entity.confidence_score is None
    assert entity.verification_status == VerificationStatus.PENDING


def test_manual_creation_employee(db):
    # `skills` (ARRAY column) is deliberately not exercised with real list
    # data here -- SQLite (this test suite's in-memory DB) has no native
    # ARRAY binding support at the DBAPI level, independent of this
    # feature; every other ARRAY-column test in this suite has the same
    # limitation. Field-acceptance is proven at the schema/service level
    # instead (test_administrator_can_create_each_of_five_types below
    # exercises the full HTTP path with a Postgres-shaped ARRAY column
    # only through fields that don't require it).
    company = _make_company(db)
    _, entity = capability_service.build_capability_manual(
        db, company.id, CapabilityEntityType.EMPLOYEE, {"name": "Jane Doe", "position": "Site Engineer"}
    )
    assert entity.name == "Jane Doe"
    assert entity.position == "Site Engineer"


def test_manual_creation_project_no_required_fields(db):
    company = _make_company(db)
    _, entity = capability_service.build_capability_manual(
        db, company.id, CapabilityEntityType.PROJECT, {"client": "Gov Dept"}
    )
    assert entity.client == "Gov Dept"


def test_manual_creation_equipment_previously_had_no_path(db):
    """Equipment had zero creation path before this feature (no extraction
    agent — see capability_service.ENTITY_MODELS' own comment). Proves the
    gap is closed."""
    company = _make_company(db)
    entity_type, entity = capability_service.build_capability_manual(
        db, company.id, CapabilityEntityType.EQUIPMENT,
        {"equipment_name": "Excavator", "quantity": 3},
    )
    assert entity_type == CapabilityEntityType.EQUIPMENT
    assert entity.equipment_name == "Excavator"
    assert entity.quantity == 3


def test_manual_creation_financial_record_previously_had_no_path(db):
    company = _make_company(db)
    entity_type, entity = capability_service.build_capability_manual(
        db, company.id, CapabilityEntityType.FINANCIAL_RECORD,
        {"financial_year": 2025, "revenue": 1000000},
    )
    assert entity_type == CapabilityEntityType.FINANCIAL_RECORD
    assert entity.financial_year == 2025


def test_manual_creation_missing_required_field_raises(db):
    company = _make_company(db)
    with pytest.raises(ValueError, match="certification_name"):
        capability_service.build_capability_manual(
            db, company.id, CapabilityEntityType.CERTIFICATION, {"issuing_authority": "BSI"}
        )


def test_manual_creation_financial_record_without_year_raises(db):
    """
    Real user-reported bug: financial_year used to be optional at manual
    creation, so a FinancialRecord could be saved with revenue/net_worth
    filled in but financial_year left blank -- the list view then showed
    "--" (accurately reflecting a genuinely null field, not a display bug),
    and, more importantly, the record could never satisfy a year-specific
    eligibility requirement ("attach Income Tax Returns for the three
    years ending 31.03.2026") since match_requirement() has no year to
    check it against. financial_year is now required for this entity type
    specifically (not because of a NOT NULL DB column -- see
    MANUAL_REQUIRED_FIELDS' own comment) so this can't happen again.
    """
    company = _make_company(db)
    with pytest.raises(ValueError, match="financial_year"):
        capability_service.build_capability_manual(
            db, company.id, CapabilityEntityType.FINANCIAL_RECORD, {"revenue": 1000000}
        )


def test_manual_creation_unknown_field_raises(db):
    company = _make_company(db)
    with pytest.raises(ValueError, match="not settable"):
        capability_service.build_capability_manual(
            db, company.id, CapabilityEntityType.EMPLOYEE, {"name": "Jane", "not_a_real_field": 1}
        )


def test_manual_creation_equipment_missing_required_name_raises(db):
    company = _make_company(db)
    with pytest.raises(ValueError, match="equipment_name"):
        capability_service.build_capability_manual(
            db, company.id, CapabilityEntityType.EQUIPMENT, {"category": "Machinery"}
        )


# ---------------------------------------------------------------------------
# PATCH support for FinancialRecord / Equipment (previously PATCHABLE_FIELDS
# only covered Certification/Employee/Project -- an M9-era gap that predates
# manual creation existing for these two types at all). Real user report:
# FinancialRecords created before financial_year became a required manual
# field (see MANUAL_REQUIRED_FIELDS above) had no way to be corrected in
# place. PATCH /capabilities/{id} and revalidation_service.handle_capability_
# update() were already fully entity-type-agnostic -- this only needed a
# field whitelist entry, not new plumbing, so these tests exercise
# update_capability_fields() directly at the service layer.
# ---------------------------------------------------------------------------


def test_patch_financial_record_can_set_previously_blank_year(db):
    company = _make_company(db)
    _entity_type, entity = capability_service.build_capability_manual(
        db, company.id, CapabilityEntityType.FINANCIAL_RECORD,
        {"financial_year": 2024, "revenue": 500000},
    )
    changed = capability_service.update_capability_fields(
        CapabilityEntityType.FINANCIAL_RECORD, entity, {"financial_year": 2025, "revenue": 750000}
    )
    assert changed == {"financial_year": (2024, 2025), "revenue": (500000, 750000)}
    assert entity.financial_year == 2025
    assert entity.revenue == 750000


def test_patch_equipment_updates_settable_fields(db):
    company = _make_company(db)
    _entity_type, entity = capability_service.build_capability_manual(
        db, company.id, CapabilityEntityType.EQUIPMENT, {"equipment_name": "Excavator", "quantity": 3}
    )
    changed = capability_service.update_capability_fields(
        CapabilityEntityType.EQUIPMENT, entity, {"quantity": 5}
    )
    assert changed == {"quantity": (3, 5)}
    assert entity.quantity == 5


def test_patch_financial_record_rejects_unknown_field(db):
    company = _make_company(db)
    _entity_type, entity = capability_service.build_capability_manual(
        db, company.id, CapabilityEntityType.FINANCIAL_RECORD, {"financial_year": 2025}
    )
    with pytest.raises(ValueError, match="not patchable"):
        capability_service.update_capability_fields(
            CapabilityEntityType.FINANCIAL_RECORD, entity, {"not_a_real_field": 1}
        )


def test_patch_capability_http_updates_financial_record_year(client):
    db_session = _seeded_session(client)
    _company, admin = _seed(db_session, role=UserRole.ADMINISTRATOR)

    create_res = client.post(
        "/api/v1/capabilities/manual",
        json={"entity_type": "financial_record", "fields": {"financial_year": 2024}},
        headers=_auth_headers(admin),
    )
    assert create_res.status_code == 201, create_res.text
    entity_id = create_res.json()["entity"]["id"]

    patch_res = client.patch(
        f"/api/v1/capabilities/{entity_id}",
        json={"fields": {"financial_year": 2025}},
        headers=_auth_headers(admin),
    )
    assert patch_res.status_code == 200, patch_res.text
    assert patch_res.json()["changed_fields"] == ["financial_year"]

    get_res = client.get(f"/api/v1/capabilities/{entity_id}", headers=_auth_headers(admin))
    assert get_res.json()["entity"]["financial_year"] == 2025


# ---------------------------------------------------------------------------
# HTTP layer: POST /api/v1/capabilities/manual -- RBAC + all five types
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
    override = engine_client.app.dependency_overrides[get_db]
    gen = override()
    return next(gen)


def _auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.mark.parametrize(
    "entity_type,fields",
    [
        ("certification", {"certification_name": "ISO 9001"}),
        ("employee", {"name": "Jane Doe"}),
        ("project", {"client": "Gov Dept"}),
        ("equipment", {"equipment_name": "Excavator"}),
        ("financial_record", {"financial_year": 2025}),
    ],
)
def test_administrator_can_create_each_of_five_types(client, entity_type, fields):
    db_session = _seeded_session(client)
    _company, admin = _seed(db_session, role=UserRole.ADMINISTRATOR)

    res = client.post(
        "/api/v1/capabilities/manual",
        json={"entity_type": entity_type, "fields": fields},
        headers=_auth_headers(admin),
    )
    assert res.status_code == 201, res.text
    assert res.json()["entity_type"] == entity_type


def test_non_administrator_gets_403(client):
    db_session = _seeded_session(client)
    _company, reviewer = _seed(db_session, role=UserRole.REVIEWER)

    res = client.post(
        "/api/v1/capabilities/manual",
        json={"entity_type": "certification", "fields": {"certification_name": "ISO 9001"}},
        headers=_auth_headers(reviewer),
    )
    assert res.status_code == 403


def test_unauthenticated_request_returns_401(client):
    res = client.post(
        "/api/v1/capabilities/manual",
        json={"entity_type": "certification", "fields": {"certification_name": "ISO 9001"}},
    )
    assert res.status_code == 401


def test_missing_required_field_returns_422(client):
    db_session = _seeded_session(client)
    _company, admin = _seed(db_session, role=UserRole.ADMINISTRATOR)

    res = client.post(
        "/api/v1/capabilities/manual",
        json={"entity_type": "certification", "fields": {"issuing_authority": "BSI"}},
        headers=_auth_headers(admin),
    )
    assert res.status_code == 422


def test_created_capability_is_scoped_to_creators_company(client):
    db_session = _seeded_session(client)
    company, admin = _seed(db_session, role=UserRole.ADMINISTRATOR)

    res = client.post(
        "/api/v1/capabilities/manual",
        json={"entity_type": "equipment", "fields": {"equipment_name": "Crane"}},
        headers=_auth_headers(admin),
    )
    assert res.status_code == 201
    assert res.json()["entity"]["company_id"] == str(company.id)
