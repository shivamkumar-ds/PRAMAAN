"""
HTTP-layer regression coverage for the SIH26100 Bidder Verification API
(Phase 2) -- app/api/v1/sih.py.

Same TestClient + dependency-override convention as test_company_api.py /
test_contact_api.py: a real FastAPI app, an in-memory SQLite engine bound
via `get_db` override, migration_guard disabled (targets real Postgres,
not present here). RBAC/tenant-isolation concerns only exist at this
layer, so they're exercised here rather than against the services
directly (those already have direct unit coverage in
test_sih_bidder_verification_domain.py from Phase 1).

Demo scenarios A-E (Phase 2 section on demo-readiness) are walked
end-to-end through the real HTTP endpoints, using Phase 1's existing
deterministic MOCK_REGISTRY_SEED data -- no new fixtures invented:

  A. Clean bidder (PAN ABCDE1234F)              -> all VERIFIED, risk "low"
  B. Mismatch bidder (PAN SUNRZ5678H)            -> entity-name/GST issues,
                                                     risk "medium"/"high"
  C. Nothing declared                            -> mandatory MISSING,
                                                     risk "high"
  D. Clean bidder but GSTIN belongs to a fraud   -> CRITICAL_FAIL (PAN
     registry entry (09FRAUD9999K1Z1)               mismatch), risk "critical"
  E. Blacklisted bidder (PAN DEBAR1234B)         -> CRITICAL_FAIL
                                                     (debarment), risk
                                                     "critical" even though
                                                     every other category
                                                     that *is* declared
                                                     verifies clean
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app.models import Company, User
from app.models.enums import UserRole, UserStatus
from app.models.sih import (
    Bidder,
    BidderDocument,
    BidderSubmission,
    ComplianceCategory,
    OfficerDecision,
    Procurement,
    RegistryRecord,
    VerificationResult,
)
from app.services.sih import compliance_category_service, registry_seed_service


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


ALL_TABLES = [
    Company.__table__,
    User.__table__,
    ComplianceCategory.__table__,
    Procurement.__table__,
    Bidder.__table__,
    BidderSubmission.__table__,
    RegistryRecord.__table__,
    VerificationResult.__table__,
    OfficerDecision.__table__,
    BidderDocument.__table__,
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


def _seed_company_and_user(db_session, role=UserRole.ADMINISTRATOR):
    company = Company(id=uuid.uuid4(), name="CPCL Test Co", registration_number=str(uuid.uuid4()))
    db_session.add(company)
    db_session.flush()
    user = User(
        id=uuid.uuid4(),
        company_id=company.id,
        name="Test Officer",
        email=f"{uuid.uuid4()}@example.com",
        password_hash="irrelevant",
        role=role,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    db_session.commit()
    return company, user


def _auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _seed_registry(db_session):
    compliance_category_service.seed_default_categories(db_session)
    registry_seed_service.seed_mock_registry(db_session)


# ---------------------------------------------------------------------------
# End-to-end happy path + demo Scenario A (clean bidder)
# ---------------------------------------------------------------------------


def test_full_workflow_clean_bidder_scenario_a(client):
    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    _seed_registry(db_session)
    headers = _auth_headers(admin)

    proc_res = client.post(
        "/api/v1/sih/procurements",
        json={"title": "CPCL Pipeline Maintenance Tender", "organization": "CPCL"},
        headers=headers,
    )
    assert proc_res.status_code == 200
    procurement_id = proc_res.json()["id"]

    bidder_res = client.post(
        "/api/v1/sih/bidders",
        json={"legal_name": "ABC Engineering Private Limited", "pan": "ABCDE1234F"},
        headers=headers,
    )
    assert bidder_res.status_code == 200
    bidder_id = bidder_res.json()["id"]

    sub_res = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    )
    assert sub_res.status_code == 200
    submission_id = sub_res.json()["id"]

    cat_res = client.get("/api/v1/sih/compliance-categories", headers=headers)
    assert cat_res.status_code == 200
    assert len(cat_res.json()) == 13
    assert sum(1 for c in cat_res.json() if c["is_active"]) == 12

    declared_facts = {
        "udyam": {"udyam_number": "UDYAM-DL-01-0012345", "entity_name": "ABC Engineering Private Limited"},
        "gst": {"gstin": "07ABCDE1234F1Z5"},
        "pan_itr": {"itr_years_claimed": ["2023-24"]},
        "mca21": {"cin": "U29100DL2015PTC280123", "entity_name": "ABC Engineering Private Limited"},
        "epfo": {"establishment_id": "DL/EPFO/998877"},
        "esic": {"establishment_id": "31-00-998877-000-1001"},
        # blacklisting's adapter only runs a check purely off bidder PAN
        # (no identifier to declare), but verify_submission() still
        # requires an entry in declared_facts to reach the adapter at all
        # -- an omitted key means MISSING, per Phase 1's own
        # test_officer_decision... / verify_submission tests. An empty
        # dict is enough to trigger the (PAN-only) check.
        "blacklisting": {},
        # The 5 optional/claimed-benefit categories (startup_india, nsic,
        # oem_authorization, digilocker, make_in_india) are deliberately
        # left undeclared -- they should resolve to NOT_CLAIMED and never
        # affect this clean bidder's score.
    }
    verify_res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/verify",
        data={"declared_facts": json.dumps(declared_facts)},
        headers=headers,
    )
    assert verify_res.status_code == 200
    results = verify_res.json()
    assert len(results) == 12
    statuses = {r["category_code"]: r["status"] for r in results}
    assert statuses["udyam"] == "verified"
    assert statuses["gst"] == "verified"
    assert statuses["pan_itr"] == "verified"
    assert statuses["mca21"] == "verified"
    assert statuses["epfo"] == "verified"
    assert statuses["esic"] == "verified"
    assert statuses["blacklisting"] == "verified"
    for optional_code in ("startup_india", "nsic", "oem_authorization", "digilocker", "make_in_india"):
        assert statuses[optional_code] == "not_claimed"

    fetched = client.get(f"/api/v1/sih/submissions/{submission_id}/verification", headers=headers)
    assert fetched.status_code == 200
    assert len(fetched.json()) == 12

    summary_res = client.get(f"/api/v1/sih/submissions/{submission_id}/summary", headers=headers)
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["risk_level"] == "low"
    assert summary["compliance_score"] == 100.0
    assert summary["critical_count"] == 0

    decision_res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/decision",
        json={"decision": "approve", "note": "All categories verified clean against registry."},
        headers=headers,
    )
    assert decision_res.status_code == 200
    assert decision_res.json()["decision"] == "approve"

    latest = client.get(f"/api/v1/sih/submissions/{submission_id}/decision", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["decision"] == "approve"

    history = client.get(f"/api/v1/sih/submissions/{submission_id}/decision/history", headers=headers)
    assert history.status_code == 200
    assert len(history.json()) == 1


# ---------------------------------------------------------------------------
# Scenario B: mismatch bidder
# ---------------------------------------------------------------------------


def test_scenario_b_mismatch_bidder_flags_medium_or_high_risk(client):
    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    _seed_registry(db_session)
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders",
        json={"legal_name": "Sunrise Traders Private Limited", "pan": "SUNRZ5678H"},
        headers=headers,
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    ).json()["id"]

    declared_facts = {
        # Udyam registry entity_name is "Sunrise Traders Private Limited";
        # GST registry entity_name is "Sunrise Traders" -- Udyam declared
        # name matches registry exactly, so udyam itself verifies; the
        # discrepancy this scenario is built to surface is GST's declared
        # name vs registry name is NOT compared by GSTAdapter (only PAN /
        # status are), so what actually flags MISMATCH here is EPFO/ESIC
        # never being declared at all (MISSING, mandatory).
        "udyam": {"udyam_number": "UDYAM-MH-02-0054321", "entity_name": "Sunrise Traders Private Limited"},
        "gst": {"gstin": "27SUNRZ5678H1Z2"},
        "pan_itr": {"itr_years_claimed": ["2023-24", "2022-23"]},
        "blacklisting": {},
        # mca21/epfo/esic intentionally omitted -> each MISSING
        # (mandatory_by_default) -- Sunrise Traders has no seed data for
        # any of the three anyway.
    }
    verify_res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/verify",
        data={"declared_facts": json.dumps(declared_facts)},
        headers=headers,
    )
    assert verify_res.status_code == 200
    statuses = {r["category_code"]: r["status"] for r in verify_res.json()}
    assert statuses["udyam"] == "verified"
    assert statuses["gst"] == "verified"
    # PAN registry only has itr_filed_years ["2023-24"] -- claiming
    # "2022-23" too produces a MISMATCH.
    assert statuses["pan_itr"] == "mismatch"
    assert statuses["mca21"] == "missing"
    assert statuses["epfo"] == "missing"
    assert statuses["esic"] == "missing"

    summary = client.get(f"/api/v1/sih/submissions/{submission_id}/summary", headers=headers).json()
    # mca21/epfo/esic are mandatory_by_default and MISSING -> "high" per
    # the veto hierarchy (mandatory unresolved outranks a plain mismatch).
    assert summary["risk_level"] == "high"
    assert summary["missing_count"] == 3
    assert summary["failed_count"] == 1
    # The officer-facing mandatory-issues list names exactly the four
    # unresolved mandatory categories: mca21/epfo/esic (MISSING) plus
    # pan_itr (MISMATCH) -- pan_itr is mandatory_by_default in this seed
    # too (see Scenario C's "every mandatory category (7: ...pan_itr...)"
    # note below), so its mismatch belongs in this list as well.
    mandatory_by_status = {i["category_code"]: i["status"] for i in summary["mandatory_issues"]}
    assert mandatory_by_status == {
        "mca21": "missing",
        "epfo": "missing",
        "esic": "missing",
        "pan_itr": "mismatch",
    }


# ---------------------------------------------------------------------------
# Scenario C: nothing declared at all
# ---------------------------------------------------------------------------


def test_scenario_c_nothing_declared_is_all_missing_and_high_risk(client):
    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    _seed_registry(db_session)
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Nobody Pvt Ltd"}, headers=headers
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    ).json()["id"]

    verify_res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/verify",
        data={"declared_facts": json.dumps({})},
        headers=headers,
    )
    assert verify_res.status_code == 200
    results = verify_res.json()
    assert len(results) == 12
    # An empty declared_facts dict means every mandatory category (7:
    # udyam/gst/pan_itr/mca21/epfo/esic/blacklisting) is MISSING --
    # verify_submission() never calls an adapter for a category with no
    # key in declared_facts at all. The 5 optional categories resolve to
    # NOT_CLAIMED instead, never MISSING.
    missing = [r for r in results if r["status"] == "missing"]
    not_claimed = [r for r in results if r["status"] == "not_claimed"]
    assert len(missing) == 7
    assert len(not_claimed) == 5

    summary = client.get(f"/api/v1/sih/submissions/{submission_id}/summary", headers=headers).json()
    assert summary["risk_level"] == "high"
    assert summary["missing_count"] == 7
    # All 7 MISSING categories here are mandatory_by_default -> all 7
    # show up in mandatory_issues, each with a null source_document
    # (nothing was ever declared or uploaded to link).
    assert len(summary["mandatory_issues"]) == 7
    assert {i["category_code"] for i in summary["mandatory_issues"]} == {
        "udyam", "gst", "pan_itr", "mca21", "epfo", "esic", "blacklisting",
    }
    assert all(i["status"] == "missing" for i in summary["mandatory_issues"])
    assert all(i["source_document_id"] is None for i in summary["mandatory_issues"])


# ---------------------------------------------------------------------------
# Scenario D: PAN mismatch via a fraudulent GSTIN -> CRITICAL_FAIL
# ---------------------------------------------------------------------------


def test_scenario_d_fraud_gstin_produces_critical_pan_mismatch(client):
    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    _seed_registry(db_session)
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    # Bidder declares PAN ABCDE1234F but supplies a GSTIN registered to a
    # different PAN (OTHRX0000Y) in the mock registry.
    bidder_id = client.post(
        "/api/v1/sih/bidders",
        json={"legal_name": "ABC Engineering Private Limited", "pan": "ABCDE1234F"},
        headers=headers,
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    ).json()["id"]

    verify_res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/verify",
        data={"declared_facts": json.dumps({"gst": {"gstin": "09FRAUD9999K1Z1"}})},
        headers=headers,
    )
    assert verify_res.status_code == 200
    statuses = {r["category_code"]: r for r in verify_res.json()}
    assert statuses["gst"]["status"] == "critical_fail"
    assert statuses["gst"]["critical"] is True

    summary = client.get(f"/api/v1/sih/submissions/{submission_id}/summary", headers=headers).json()
    assert summary["risk_level"] == "critical"
    assert summary["critical_count"] == 1
    assert "GST" in summary["critical_categories"][0] or "GSTN" in summary["critical_categories"][0]


# ---------------------------------------------------------------------------
# Scenario E: blacklisted bidder -> CRITICAL_FAIL never softened by score
# ---------------------------------------------------------------------------


def test_scenario_e_blacklisted_bidder_stays_critical_even_with_other_categories_clean(client):
    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    _seed_registry(db_session)
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders",
        json={"legal_name": "Debarred Contractor Pvt Ltd", "pan": "DEBAR1234B"},
        headers=headers,
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    ).json()["id"]

    verify_res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/verify",
        # blacklisting needs an entry (even empty) to reach the adapter --
        # see the note in test_scenario_c above.
        data={"declared_facts": json.dumps({"blacklisting": {}})},
        headers=headers,
    )
    assert verify_res.status_code == 200
    statuses = {r["category_code"]: r["status"] for r in verify_res.json()}
    assert statuses["blacklisting"] == "critical_fail"

    summary = client.get(f"/api/v1/sih/submissions/{submission_id}/summary", headers=headers).json()
    # A high numeric score must never soften a debarment -- this is the
    # exact "95/100 blacklisted bidder must never read as safe" guarantee
    # documented in compliance_summary_service.py.
    assert summary["risk_level"] == "critical"
    assert summary["critical_count"] == 1


# ---------------------------------------------------------------------------
# Officer decision: all 3 types, mandatory note, insert-only history
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("decision_value", ["approve", "reject", "request_clarification"])
def test_all_three_decision_types_are_recordable(client, decision_value):
    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    _seed_registry(db_session)
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Some Bidder"}, headers=headers
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    ).json()["id"]

    res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/decision",
        json={"decision": decision_value, "note": "Officer review note."},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["decision"] == decision_value


def test_blank_note_is_rejected_with_422(client):
    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Some Bidder"}, headers=headers
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    ).json()["id"]

    res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/decision",
        json={"decision": "approve", "note": "   "},
        headers=headers,
    )
    # Pydantic's field_validator rejects this before it ever reaches the
    # service -- FastAPI's own 422, not InvalidDecisionError's mapped one.
    assert res.status_code == 422


def test_decision_history_is_insert_only_and_ordered(client):
    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Some Bidder"}, headers=headers
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    ).json()["id"]

    client.post(
        f"/api/v1/sih/submissions/{submission_id}/decision",
        json={"decision": "request_clarification", "note": "Need more documents."},
        headers=headers,
    )
    client.post(
        f"/api/v1/sih/submissions/{submission_id}/decision",
        json={"decision": "approve", "note": "Clarification received, approved."},
        headers=headers,
    )

    history = client.get(f"/api/v1/sih/submissions/{submission_id}/decision/history", headers=headers).json()
    assert len(history) == 2
    assert history[0]["decision"] == "request_clarification"
    assert history[1]["decision"] == "approve"

    latest = client.get(f"/api/v1/sih/submissions/{submission_id}/decision", headers=headers).json()
    assert latest["decision"] == "approve"


# ---------------------------------------------------------------------------
# RBAC + tenant isolation + auth
# ---------------------------------------------------------------------------


def test_reviewer_can_create_procurement(client):
    """
    Full 5-role RBAC pass (Task 4): REVIEWER/BID_MANAGER are the day-to-day
    evidence-gathering roles and are deliberately allowed to write here --
    only AUDITOR is excluded (require_sih_write_role). This replaces the
    old Phase-2 behavior where every SIH write required Administrator.
    """
    db_session = _seeded_session(client)
    _company, reviewer = _seed_company_and_user(db_session, role=UserRole.REVIEWER)

    res = client.post(
        "/api/v1/sih/procurements", json={"title": "Should Succeed"}, headers=_auth_headers(reviewer)
    )
    assert res.status_code == 200


def test_auditor_cannot_create_procurement(client):
    db_session = _seeded_session(client)
    _company, auditor = _seed_company_and_user(db_session, role=UserRole.AUDITOR)

    res = client.post(
        "/api/v1/sih/procurements", json={"title": "Should Fail"}, headers=_auth_headers(auditor)
    )
    assert res.status_code == 403


def test_non_administrator_can_still_read(client):
    db_session = _seeded_session(client)
    company, admin = _seed_company_and_user(db_session)
    reviewer = User(
        id=uuid.uuid4(),
        company_id=company.id,
        name="Reviewer",
        email=f"{uuid.uuid4()}@example.com",
        password_hash="irrelevant",
        role=UserRole.REVIEWER,
        status=UserStatus.ACTIVE,
    )
    db_session.add(reviewer)
    db_session.commit()

    client.post("/api/v1/sih/procurements", json={"title": "Visible"}, headers=_auth_headers(admin))
    res = client.get("/api/v1/sih/procurements", headers=_auth_headers(reviewer))
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_unauthenticated_request_returns_401(client):
    res = client.get("/api/v1/sih/procurements")
    assert res.status_code == 401


def test_cannot_read_another_tenants_procurement(client):
    db_session = _seeded_session(client)
    _company_a, admin_a = _seed_company_and_user(db_session)
    _company_b, admin_b = _seed_company_and_user(db_session)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Company A's Procurement"}, headers=_auth_headers(admin_a)
    ).json()["id"]

    res = client.get(f"/api/v1/sih/procurements/{procurement_id}", headers=_auth_headers(admin_b))
    assert res.status_code == 404


def test_cannot_create_submission_against_another_tenants_procurement(client):
    db_session = _seeded_session(client)
    _company_a, admin_a = _seed_company_and_user(db_session)
    _company_b, admin_b = _seed_company_and_user(db_session)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Company A's Procurement"}, headers=_auth_headers(admin_a)
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Company B's Bidder"}, headers=_auth_headers(admin_b)
    ).json()["id"]

    res = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=_auth_headers(admin_b),
    )
    assert res.status_code == 404


def test_duplicate_submission_for_same_bidder_and_procurement_returns_409(client):
    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Some Bidder"}, headers=headers
    ).json()["id"]

    first = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions", json={"bidder_id": bidder_id}, headers=headers
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions", json={"bidder_id": bidder_id}, headers=headers
    )
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# Manual evidence attachment (Task 1) -- HTTP layer
# ---------------------------------------------------------------------------


def test_verify_with_attachment_populates_source_document_id(client, monkeypatch, tmp_path):
    from app.core import storage

    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    _seed_registry(db_session)
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders",
        json={"legal_name": "ABC Engineering Private Limited", "pan": "ABCDE1234F"},
        headers=headers,
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    ).json()["id"]

    declared_facts = {"gst": {"gstin": "07ABCDE1234F1Z5"}, "blacklisting": {}}
    res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/verify",
        data={"declared_facts": json.dumps(declared_facts), "attachment_category_code": "gst"},
        files={"attachment": ("gst_certificate.pdf", b"fake pdf bytes", "application/pdf")},
        headers=headers,
    )
    assert res.status_code == 200
    results = {r["category_code"]: r for r in res.json()}
    assert results["gst"]["source_document_id"] is not None
    # blacklisting had no attachment -- must stay a manual declaration,
    # untouched by the gst attachment.
    assert results["blacklisting"]["source_document_id"] is None

    grounding = client.get(f"/api/v1/sih/submissions/{submission_id}/grounding", headers=headers).json()
    gst_grounding = next(c for c in grounding["categories"] if c["category_code"] == "gst")
    assert gst_grounding["origin"] == "document_evidence"


def test_verify_without_attachment_still_works_backward_compatibly(client):
    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    _seed_registry(db_session)
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Some Bidder"}, headers=headers
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    ).json()["id"]

    res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/verify",
        data={"declared_facts": json.dumps({"blacklisting": {}})},
        headers=headers,
    )
    assert res.status_code == 200
    results = {r["category_code"]: r for r in res.json()}
    assert results["blacklisting"]["source_document_id"] is None


def test_verify_attachment_requires_matching_category_code(client, monkeypatch, tmp_path):
    from app.core import storage

    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    _seed_registry(db_session)
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Some Bidder"}, headers=headers
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    ).json()["id"]

    res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/verify",
        data={"declared_facts": json.dumps({"gst": {"gstin": "07ABCDE1234F1Z5"}}), "attachment_category_code": "udyam"},
        files={"attachment": ("cert.pdf", b"fake pdf bytes", "application/pdf")},
        headers=headers,
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Task 3: Procurement award (Collusion Radar repeat-winner support)
# ---------------------------------------------------------------------------


def test_set_awarded_bidder_requires_administrator_or_executive(client):
    db_session = _seeded_session(client)
    company, admin = _seed_company_and_user(db_session)
    reviewer = User(
        id=uuid.uuid4(), company_id=company.id, name="Reviewer",
        email=f"{uuid.uuid4()}@example.com", password_hash="x",
        role=UserRole.REVIEWER, status=UserStatus.ACTIVE,
    )
    db_session.add(reviewer)
    db_session.commit()
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Winner Co"}, headers=headers
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    ).json()["id"]
    client.post(
        f"/api/v1/sih/submissions/{submission_id}/decision",
        json={"decision": "approve", "note": "Reviewed."},
        headers=headers,
    )

    res = client.patch(
        f"/api/v1/sih/procurements/{procurement_id}/award",
        json={"bidder_id": bidder_id},
        headers=_auth_headers(reviewer),
    )
    assert res.status_code == 403

    res = client.patch(
        f"/api/v1/sih/procurements/{procurement_id}/award", json={"bidder_id": bidder_id}, headers=headers
    )
    assert res.status_code == 200
    assert res.json()["awarded_bidder_id"] == bidder_id


def test_set_awarded_bidder_before_any_decision_returns_409(client):
    db_session = _seeded_session(client)
    _company, admin = _seed_company_and_user(db_session)
    headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Winner Co"}, headers=headers
    ).json()["id"]
    client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=headers,
    )

    res = client.patch(
        f"/api/v1/sih/procurements/{procurement_id}/award", json={"bidder_id": bidder_id}, headers=headers
    )
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# Task 4: AUDITOR is read-only across every SIH write endpoint
# ---------------------------------------------------------------------------


def _seed_admin_and_auditor(db_session):
    company, admin = _seed_company_and_user(db_session, role=UserRole.ADMINISTRATOR)
    auditor = User(
        id=uuid.uuid4(), company_id=company.id, name="Auditor",
        email=f"{uuid.uuid4()}@example.com", password_hash="x",
        role=UserRole.AUDITOR, status=UserStatus.ACTIVE,
    )
    db_session.add(auditor)
    db_session.commit()
    return company, admin, auditor


def test_auditor_cannot_upload_document(client, monkeypatch, tmp_path):
    from app.core import storage

    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    db_session = _seeded_session(client)
    _company, admin, auditor = _seed_admin_and_auditor(db_session)
    admin_headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=admin_headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Some Bidder"}, headers=admin_headers
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=admin_headers,
    ).json()["id"]

    res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/documents",
        files={"file": ("cert.pdf", b"fake pdf bytes", "application/pdf")},
        headers=_auth_headers(auditor),
    )
    assert res.status_code == 403

    # Same request as an Administrator succeeds -- proves the 403 above is
    # role-specific, not a broken request shape.
    res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/documents",
        files={"file": ("cert.pdf", b"fake pdf bytes", "application/pdf")},
        headers=admin_headers,
    )
    assert res.status_code == 200


def test_auditor_cannot_record_decision(client):
    db_session = _seeded_session(client)
    _company, admin, auditor = _seed_admin_and_auditor(db_session)
    admin_headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=admin_headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Some Bidder"}, headers=admin_headers
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=admin_headers,
    ).json()["id"]

    res = client.post(
        f"/api/v1/sih/submissions/{submission_id}/decision",
        json={"decision": "approve", "note": "Should fail."},
        headers=_auth_headers(auditor),
    )
    assert res.status_code == 403


def test_auditor_cannot_set_awarded_bidder(client):
    db_session = _seeded_session(client)
    _company, admin, auditor = _seed_admin_and_auditor(db_session)
    admin_headers = _auth_headers(admin)

    procurement_id = client.post(
        "/api/v1/sih/procurements", json={"title": "Sample Procurement"}, headers=admin_headers
    ).json()["id"]
    bidder_id = client.post(
        "/api/v1/sih/bidders", json={"legal_name": "Some Bidder"}, headers=admin_headers
    ).json()["id"]
    submission_id = client.post(
        f"/api/v1/sih/procurements/{procurement_id}/submissions",
        json={"bidder_id": bidder_id},
        headers=admin_headers,
    ).json()["id"]
    client.post(
        f"/api/v1/sih/submissions/{submission_id}/decision",
        json={"decision": "approve", "note": "Reviewed."},
        headers=admin_headers,
    )

    res = client.patch(
        f"/api/v1/sih/procurements/{procurement_id}/award",
        json={"bidder_id": bidder_id},
        headers=_auth_headers(auditor),
    )
    assert res.status_code == 403


def test_auditor_can_still_read(client):
    db_session = _seeded_session(client)
    company, admin, auditor = _seed_admin_and_auditor(db_session)
    client.post("/api/v1/sih/procurements", json={"title": "Visible"}, headers=_auth_headers(admin))

    res = client.get("/api/v1/sih/procurements", headers=_auth_headers(auditor))
    assert res.status_code == 200
    assert len(res.json()) == 1
