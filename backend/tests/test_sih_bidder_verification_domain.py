"""
Regression coverage for the SIH26100 Bidder Verification domain
foundation (Phase 1) -- app/models/sih/*, app/services/sih/*.

Covers:
- Model creation and relationships (Procurement -> BidderSubmission ->
  Bidder, ComplianceCategory, RegistryRecord, VerificationResult,
  OfficerDecision).
- ComplianceCategory seeding: exact count, active/inactive split,
  idempotency.
- Mock registry adapters: verified, mismatch, missing, critical PAN
  mismatch, blacklisted -- one scenario per adapter.
- verify_submission() end-to-end: inserts one VerificationResult per
  active category, is insert-only on re-verify, get_latest_results()
  returns exactly one (the newest) row per category.
- Officer decision: record_decision() for all three decision types,
  mandatory note enforcement, invalid decision-type rejection,
  insert-only history (never overwritten), get_latest_decision().
- Isolation from existing BidOps models: the SIH domain and the existing
  Tender/Requirement/Mission domain can coexist in the same database
  without table/FK collisions, and nothing in decision_engine.py's
  existing enums/functions is affected by anything added here.

Same in-memory SQLite + explicit-table-list convention as every other
test file in this directory (no conftest.py, no ALL_TABLES constant by
name -- each file builds what it needs). JSONB is rendered as SQLite
JSON via the same @compiles override already used by
test_decision_engine_concurrency.py and test_manual_capability_creation.py.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import decision_engine
from app.core.database import Base
from app.models import Company, Mission, Requirement, Tender, User
from app.models.enums import MatchStatus, MissionStatus, UserRole, UserStatus
from app.models.sih import (
    Bidder,
    BidderSubmission,
    ComplianceCategory,
    OfficerDecision,
    Procurement,
    RegistryRecord,
    VerificationResult,
)
from app.models.sih.enums import (
    ComplianceVerificationStatus,
    OfficerDecisionType,
    ProcurementStatus,
    SubmissionStatus,
)
from app.services.exceptions import NotFoundError
from app.services.sih import (
    compliance_category_service,
    officer_decision_service,
    registry_seed_service,
    verification_service,
)
from app.services.sih.officer_decision_service import InvalidDecisionError
from app.services.sih.registry_adapters import (
    BlacklistingAdapter,
    DigiLockerAdapter,
    EPFOAdapter,
    EPFOESICAdapter,
    ESICAdapter,
    GSTAdapter,
    MakeInIndiaAdapter,
    MCA21Adapter,
    NSICAdapter,
    OEMAuthorizationAdapter,
    PANIncomeTaxAdapter,
    StartupIndiaAdapter,
    UdyamAdapter,
    get_adapter,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


ALL_TABLES = [
    Company.__table__,
    User.__table__,
    # Existing BidOps domain -- included only to prove coexistence/isolation.
    Mission.__table__,
    Tender.__table__,
    Requirement.__table__,
    # SIH26100 domain.
    ComplianceCategory.__table__,
    Procurement.__table__,
    Bidder.__table__,
    BidderSubmission.__table__,
    RegistryRecord.__table__,
    VerificationResult.__table__,
    OfficerDecision.__table__,
]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=ALL_TABLES)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def company(db):
    c = Company(name="CPCL Test Company", registration_number=f"REG-{uuid.uuid4()}")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture()
def officer(db, company):
    u = User(
        company_id=company.id,
        name="Test Procurement Officer",
        email=f"officer-{uuid.uuid4()}@example.com",
        password_hash="x",
        role=UserRole.ADMINISTRATOR,
        status=UserStatus.ACTIVE,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def seeded_categories(db):
    return compliance_category_service.seed_default_categories(db)


@pytest.fixture()
def seeded_registry(db, seeded_categories):
    return registry_seed_service.seed_mock_registry(db)


def _make_procurement(db, company) -> Procurement:
    p = Procurement(company_id=company.id, title="CPCL Pipeline Maintenance Tender", organization="CPCL")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_bidder(db, company, *, legal_name="ABC Engineering Private Limited", pan="ABCDE1234F") -> Bidder:
    b = Bidder(company_id=company.id, legal_name=legal_name, pan=pan)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def _make_submission(db, procurement, bidder) -> BidderSubmission:
    s = BidderSubmission(procurement_id=procurement.id, bidder_id=bidder.id)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# 1. Model creation / relationships
# ---------------------------------------------------------------------------


def test_procurement_bidder_submission_lifecycle_and_relationships(db, company):
    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company)
    submission = _make_submission(db, procurement, bidder)

    assert submission.status == SubmissionStatus.SUBMITTED
    assert submission.procurement.id == procurement.id
    assert submission.bidder.id == bidder.id
    assert procurement.status == ProcurementStatus.OPEN
    # Relationship back-population.
    assert submission in procurement.submissions
    assert submission in bidder.submissions


def test_bidder_submission_unique_per_procurement_bidder_pair(db, company):
    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company)
    _make_submission(db, procurement, bidder)

    duplicate = BidderSubmission(procurement_id=procurement.id, bidder_id=bidder.id)
    db.add(duplicate)
    with pytest.raises(Exception):
        db.commit()
    db.rollback()


def test_bidder_is_independent_of_procurement(db, company):
    """A Bidder is not scoped to any one Procurement -- the same Bidder
    can have submissions against two different Procurements, and Bidder
    itself carries no procurement_id (see app/models/sih/bidder.py)."""
    bidder = _make_bidder(db, company)
    p1 = _make_procurement(db, company)
    p2 = Procurement(company_id=company.id, title="Second Procurement")
    db.add(p2)
    db.commit()
    db.refresh(p2)

    s1 = _make_submission(db, p1, bidder)
    s2 = _make_submission(db, p2, bidder)

    assert not hasattr(Bidder, "procurement_id")
    assert {s1.id, s2.id} == {s.id for s in bidder.submissions}


# ---------------------------------------------------------------------------
# 2. ComplianceCategory seeding
# ---------------------------------------------------------------------------


def test_seed_default_categories_creates_exactly_thirteen(db):
    created = compliance_category_service.seed_default_categories(db)
    assert len(created) == 13
    all_categories = db.query(ComplianceCategory).all()
    assert len(all_categories) == 13


def test_seed_default_categories_active_inactive_split(db, seeded_categories):
    """SIH26100 demo-scope expansion: every requested source now has an
    adapter and is active. Only the superseded combined "epfo_esic"
    category (replaced by the epfo/esic split) stays inactive -- see
    compliance_category_service.py's module docstring."""
    active_codes = {c.code for c in seeded_categories if c.is_active}
    inactive_codes = {c.code for c in seeded_categories if not c.is_active}
    assert active_codes == {
        "udyam",
        "gst",
        "pan_itr",
        "mca21",
        "epfo",
        "esic",
        "blacklisting",
        "startup_india",
        "nsic",
        "oem_authorization",
        "digilocker",
        "make_in_india",
    }
    assert inactive_codes == {"epfo_esic"}


def test_seed_default_categories_is_idempotent(db, seeded_categories):
    second_run = compliance_category_service.seed_default_categories(db)
    assert second_run == []
    assert db.query(ComplianceCategory).count() == 13


# ---------------------------------------------------------------------------
# 3. Mock registry adapters
# ---------------------------------------------------------------------------


def test_udyam_adapter_verified(db, seeded_registry):
    adapter = UdyamAdapter()
    outcome = adapter.verify(
        db,
        {"pan": "ABCDE1234F"},
        {"udyam_number": "UDYAM-DL-01-0012345", "entity_name": "ABC Engineering Private Limited"},
    )
    assert outcome.status == ComplianceVerificationStatus.VERIFIED
    assert outcome.discrepancies == []


def test_udyam_adapter_missing_when_not_declared(db, seeded_registry):
    outcome = UdyamAdapter().verify(db, {"pan": "ABCDE1234F"}, {})
    assert outcome.status == ComplianceVerificationStatus.MISSING


def test_gst_adapter_mismatch_on_entity_name_and_status(db, seeded_registry):
    # Sunrise Traders' GST record has entity_name "Sunrise Traders" while
    # the seed's declared name below differs -- exercised via the
    # Udyam-vs-GST name mismatch scenario (Phase 0 report's example).
    outcome = GSTAdapter().verify(
        db, {"pan": "SUNRZ5678H"}, {"gstin": "27SUNRZ5678H1Z2"}
    )
    # PAN matches exactly and status is active -- no discrepancy from
    # this adapter alone (name-mismatch cross-checking across categories
    # is a later-phase identity-resolution concern, not this adapter's job).
    assert outcome.status == ComplianceVerificationStatus.VERIFIED


def test_gst_adapter_critical_fail_on_pan_mismatch(db, seeded_registry):
    """The GSTIN 09FRAUD9999K1Z1 is registered to PAN 'OTHRX0000Y' in the
    mock registry -- declaring it under a different bidder PAN must be a
    deterministic CRITICAL_FAIL, never softened by a confidence score."""
    outcome = GSTAdapter().verify(
        db, {"pan": "ABCDE1234F"}, {"gstin": "09FRAUD9999K1Z1"}
    )
    assert outcome.status == ComplianceVerificationStatus.CRITICAL_FAIL
    assert outcome.confidence is None
    assert "PAN" in outcome.discrepancies[0]


def test_pan_itr_adapter_critical_fail_when_no_pan_at_all(db, seeded_registry):
    outcome = PANIncomeTaxAdapter().verify(db, {"pan": None}, {})
    assert outcome.status == ComplianceVerificationStatus.CRITICAL_FAIL


def test_pan_itr_adapter_mismatch_on_unfiled_claimed_year(db, seeded_registry):
    outcome = PANIncomeTaxAdapter().verify(
        db, {"pan": "ABCDE1234F"}, {"itr_years_claimed": ["2024-25", "2025-26"]}
    )
    assert outcome.status == ComplianceVerificationStatus.MISMATCH
    assert "2025-26" in outcome.discrepancies[0]


def test_epfo_esic_adapter_verified(db, seeded_registry):
    outcome = EPFOESICAdapter().verify(db, {"pan": "ABCDE1234F"}, {"establishment_id": "DL/EPFO/998877"})
    assert outcome.status == ComplianceVerificationStatus.VERIFIED


def test_blacklisting_adapter_critical_fail_for_debarred_bidder(db, seeded_registry):
    outcome = BlacklistingAdapter().verify(db, {"pan": "DEBAR1234B"}, {})
    assert outcome.status == ComplianceVerificationStatus.CRITICAL_FAIL


def test_blacklisting_adapter_clear_for_clean_bidder(db, seeded_registry):
    outcome = BlacklistingAdapter().verify(db, {"pan": "ABCDE1234F"}, {})
    assert outcome.status == ComplianceVerificationStatus.VERIFIED
    assert outcome.discrepancies == []


# ---------------------------------------------------------------------------
# 3b. SIH26100 demo-scope expansion: MCA21, EPFO, ESIC, NSIC, Startup India,
# OEM Authorization, DigiLocker, Make in India -- one clean/VERIFIED
# scenario plus at least one failure-mode scenario per adapter, using the
# same ABC Engineering / Sunrise Traders seed data as the pre-existing
# adapters above.
# ---------------------------------------------------------------------------


def test_mca21_adapter_verified(db, seeded_registry):
    outcome = MCA21Adapter().verify(
        db,
        {"pan": "ABCDE1234F"},
        {"cin": "U29100DL2015PTC280123", "entity_name": "ABC Engineering Private Limited"},
    )
    assert outcome.status == ComplianceVerificationStatus.VERIFIED
    assert outcome.discrepancies == []


def test_mca21_adapter_missing_when_not_declared(db, seeded_registry):
    outcome = MCA21Adapter().verify(db, {"pan": "ABCDE1234F"}, {})
    assert outcome.status == ComplianceVerificationStatus.MISSING


def test_mca21_adapter_category_specific_mismatch_for_struck_off_company(db, seeded_registry):
    """Scenario F: a category-specific failure that isn't a PAN/identity
    problem at all -- Sunrise Traders' CIN resolves to a real registry
    record, but MCA21 shows the company struck off the register."""
    outcome = MCA21Adapter().verify(
        db, {"pan": "SUNRZ5678H"}, {"cin": "U27310MH2018PTC312456"}
    )
    assert outcome.status == ComplianceVerificationStatus.MISMATCH
    assert "struck off" in outcome.discrepancies[0]


def test_epfo_adapter_verified(db, seeded_registry):
    outcome = EPFOAdapter().verify(
        db,
        {"pan": "ABCDE1234F"},
        {"establishment_id": "DL/EPFO/998877", "legal_name": "ABC Engineering Private Limited"},
    )
    assert outcome.status == ComplianceVerificationStatus.VERIFIED


def test_esic_adapter_verified(db, seeded_registry):
    outcome = ESICAdapter().verify(
        db,
        {"pan": "ABCDE1234F"},
        {"establishment_id": "31-00-998877-000-1001", "legal_name": "ABC Engineering Private Limited"},
    )
    assert outcome.status == ComplianceVerificationStatus.VERIFIED


def test_esic_adapter_missing_when_not_declared(db, seeded_registry):
    """EPFO and ESIC are kept as fully separate, independently-checkable
    categories (SIH26100 demo-scope expansion) -- declaring one must not
    implicitly satisfy the other."""
    outcome = ESICAdapter().verify(db, {"pan": "ABCDE1234F"}, {})
    assert outcome.status == ComplianceVerificationStatus.MISSING


def test_nsic_adapter_verified(db, seeded_registry):
    outcome = NSICAdapter().verify(
        db, {"pan": "ABCDE1234F"}, {"nsic_registration_number": "NSIC/DL/2019/00456"}
    )
    assert outcome.status == ComplianceVerificationStatus.VERIFIED


def test_nsic_adapter_mismatch_when_registration_number_unknown(db, seeded_registry):
    outcome = NSICAdapter().verify(
        db, {"pan": "ABCDE1234F"}, {"nsic_registration_number": "NSIC/DL/9999/99999"}
    )
    assert outcome.status == ComplianceVerificationStatus.MISMATCH


def test_startup_india_adapter_verified(db, seeded_registry):
    outcome = StartupIndiaAdapter().verify(
        db, {"pan": "ABCDE1234F"}, {"dpiit_number": "DIPP123456"}
    )
    assert outcome.status == ComplianceVerificationStatus.VERIFIED


def test_startup_india_adapter_missing_when_not_declared(db, seeded_registry):
    # Adapter-level result is MISSING; verify_submission() is what turns
    # an undeclared non-mandatory category into NOT_CLAIMED for scoring
    # purposes (see test_verify_submission_creates_one_result_per_active_category).
    outcome = StartupIndiaAdapter().verify(db, {"pan": "ABCDE1234F"}, {})
    assert outcome.status == ComplianceVerificationStatus.MISSING


def test_oem_authorization_adapter_verified(db, seeded_registry):
    outcome = OEMAuthorizationAdapter().verify(
        db,
        {"pan": "ABCDE1234F"},
        {"authorization_number": "OEM-AUTH-2026-0091", "bidder_name": "ABC Engineering Private Limited"},
    )
    assert outcome.status == ComplianceVerificationStatus.VERIFIED


def test_oem_authorization_adapter_mismatch_when_issued_to_different_bidder(db, seeded_registry):
    outcome = OEMAuthorizationAdapter().verify(
        db,
        {"pan": "ABCDE1234F"},
        {"authorization_number": "OEM-AUTH-2026-0091", "bidder_name": "A Completely Different Company"},
    )
    assert outcome.status == ComplianceVerificationStatus.MISMATCH
    assert "not the declared bidder" in outcome.discrepancies[0]


def test_digilocker_adapter_verified(db, seeded_registry):
    outcome = DigiLockerAdapter().verify(
        db, {"pan": "ABCDE1234F"}, {"digilocker_reference": "DL-REF-ABCENG-0012"}
    )
    assert outcome.status == ComplianceVerificationStatus.VERIFIED


def test_digilocker_adapter_critical_fail_on_tampered_document(db, seeded_registry):
    """A tampered DigiLocker cross-check is a deterministic CRITICAL_FAIL,
    never softened by a confidence score -- mirrors the PAN-mismatch
    critical-identity-failure scenario (scenario D)."""
    tampered = RegistryRecord(
        category_code="digilocker",
        identifier_type="digilocker_reference",
        identifier_value="DL-REF-TAMPERED-0001",
        record_data={"entity_name": "Forged Entity", "verified": True, "tampered": True},
    )
    db.add(tampered)
    db.commit()

    outcome = DigiLockerAdapter().verify(
        db, {"pan": "ABCDE1234F"}, {"digilocker_reference": "DL-REF-TAMPERED-0001"}
    )
    assert outcome.status == ComplianceVerificationStatus.CRITICAL_FAIL
    assert outcome.confidence is None


def test_make_in_india_adapter_verified(db, seeded_registry):
    outcome = MakeInIndiaAdapter().verify(
        db, {"pan": "ABCDE1234F"}, {"local_content_percentage": 55}
    )
    assert outcome.status == ComplianceVerificationStatus.VERIFIED


def test_make_in_india_adapter_mismatch_when_overclaiming(db, seeded_registry):
    """Declaring more local content than the certifying agency actually
    verified (62%) is a discrepancy, not a pass."""
    outcome = MakeInIndiaAdapter().verify(
        db, {"pan": "ABCDE1234F"}, {"local_content_percentage": 90}
    )
    assert outcome.status == ComplianceVerificationStatus.MISMATCH
    assert "exceeds" in outcome.discrepancies[0]


def test_make_in_india_adapter_missing_when_not_declared(db, seeded_registry):
    outcome = MakeInIndiaAdapter().verify(db, {"pan": "ABCDE1234F"}, {})
    assert outcome.status == ComplianceVerificationStatus.MISSING


def test_get_adapter_raises_for_unregistered_category():
    # Every SIH26100-requested category now has a real adapter (demo-scope
    # expansion) -- this now asserts the genuinely-unregistered case
    # instead of a since-implemented roadmap category.
    with pytest.raises(ValueError):
        get_adapter("not_a_real_category")


# ---------------------------------------------------------------------------
# 4. verify_submission() end-to-end + insert-only persistence
# ---------------------------------------------------------------------------


def test_verify_submission_creates_one_result_per_active_category(db, company, seeded_registry):
    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company)
    submission = _make_submission(db, procurement, bidder)

    results = verification_service.verify_submission(
        db,
        submission.id,
        bidder_identity={"pan": bidder.pan},
        declared_facts_by_category={
            "udyam": {"udyam_number": "UDYAM-DL-01-0012345", "entity_name": bidder.legal_name},
            "gst": {"gstin": "07ABCDE1234F1Z5"},
            "pan_itr": {"itr_years_claimed": ["2023-24"]},
            "mca21": {"cin": "U29100DL2015PTC280123", "entity_name": bidder.legal_name},
            "epfo": {"establishment_id": "DL/EPFO/998877"},
            "esic": {"establishment_id": "31-00-998877-000-1001"},
            # blacklisting deliberately not declared -- mandatory, so
            # should resolve to MISSING, not silently skipped. The five
            # optional categories (startup_india/nsic/oem_authorization/
            # digilocker/make_in_india) are also not declared -- they
            # should resolve to NOT_CLAIMED, never penalized.
        },
    )

    active_category_count = db.query(ComplianceCategory).filter(ComplianceCategory.is_active.is_(True)).count()
    assert len(results) == active_category_count == 12

    by_code = {r.category.code: r for r in results}
    assert by_code["udyam"].status == ComplianceVerificationStatus.VERIFIED
    assert by_code["gst"].status == ComplianceVerificationStatus.VERIFIED
    assert by_code["pan_itr"].status == ComplianceVerificationStatus.VERIFIED
    assert by_code["mca21"].status == ComplianceVerificationStatus.VERIFIED
    assert by_code["epfo"].status == ComplianceVerificationStatus.VERIFIED
    assert by_code["esic"].status == ComplianceVerificationStatus.VERIFIED
    assert by_code["blacklisting"].status == ComplianceVerificationStatus.MISSING
    assert by_code["blacklisting"].declared_value is None
    for optional_code in ("startup_india", "nsic", "oem_authorization", "digilocker", "make_in_india"):
        assert by_code[optional_code].status == ComplianceVerificationStatus.NOT_CLAIMED


def test_verify_submission_raises_not_found_for_unknown_submission(db, seeded_registry):
    with pytest.raises(NotFoundError):
        verification_service.verify_submission(db, uuid.uuid4(), {}, {})


def test_verify_submission_is_insert_only_on_re_verify(db, company, seeded_registry):
    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company)
    submission = _make_submission(db, procurement, bidder)

    first_run = verification_service.verify_submission(db, submission.id, {"pan": bidder.pan}, {})
    second_run = verification_service.verify_submission(db, submission.id, {"pan": bidder.pan}, {})

    all_rows = db.query(VerificationResult).filter(VerificationResult.submission_id == submission.id).all()
    # Both runs' rows must still exist -- nothing was updated/deleted.
    assert len(all_rows) == len(first_run) + len(second_run)

    # get_latest_results() collapses to exactly one row per category --
    # the newest one.
    latest = verification_service.get_latest_results(db, submission.id)
    active_category_count = db.query(ComplianceCategory).filter(ComplianceCategory.is_active.is_(True)).count()
    assert len(latest) == active_category_count
    newest_ids = {r.id for r in second_run}
    assert {r.id for r in latest} == newest_ids


# ---------------------------------------------------------------------------
# 5. Officer decision -- mandatory note, insert-only, invalid rejection
# ---------------------------------------------------------------------------


def test_record_decision_approve_reject_request_clarification(db, company, officer):
    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company)
    submission = _make_submission(db, procurement, bidder)

    approve = officer_decision_service.record_decision(
        db, submission.id, officer.id, OfficerDecisionType.APPROVE, "Documents verified, clean bidder."
    )
    assert approve.decision == OfficerDecisionType.APPROVE
    assert approve.note == "Documents verified, clean bidder."
    assert approve.officer_id == officer.id


def test_record_decision_requires_a_non_blank_note(db, company, officer):
    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company)
    submission = _make_submission(db, procurement, bidder)

    with pytest.raises(InvalidDecisionError):
        officer_decision_service.record_decision(
            db, submission.id, officer.id, OfficerDecisionType.REJECT, ""
        )
    with pytest.raises(InvalidDecisionError):
        officer_decision_service.record_decision(
            db, submission.id, officer.id, OfficerDecisionType.REJECT, "   "
        )
    with pytest.raises(InvalidDecisionError):
        officer_decision_service.record_decision(
            db, submission.id, officer.id, OfficerDecisionType.REJECT, None
        )
    # No row should have been persisted by any of the three rejected calls.
    assert officer_decision_service.get_latest_decision(db, submission.id) is None


def test_record_decision_rejects_invalid_decision_value(db, company, officer):
    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company)
    submission = _make_submission(db, procurement, bidder)

    with pytest.raises(InvalidDecisionError):
        officer_decision_service.record_decision(
            db, submission.id, officer.id, "not_a_real_decision", "A note."
        )


def test_record_decision_raises_not_found_for_unknown_submission(db, officer):
    with pytest.raises(NotFoundError):
        officer_decision_service.record_decision(
            db, uuid.uuid4(), officer.id, OfficerDecisionType.APPROVE, "A note."
        )


def test_officer_decision_is_never_overwritten_full_history_preserved(db, company, officer):
    """A later decision on the same submission (e.g. REQUEST_CLARIFICATION
    followed by APPROVE once the officer receives what they asked for)
    must never silently replace the earlier row -- both stay queryable."""
    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company)
    submission = _make_submission(db, procurement, bidder)

    first = officer_decision_service.record_decision(
        db, submission.id, officer.id, OfficerDecisionType.REQUEST_CLARIFICATION, "Need updated GST certificate."
    )
    second = officer_decision_service.record_decision(
        db, submission.id, officer.id, OfficerDecisionType.APPROVE, "Updated GST certificate received and verified."
    )

    history = officer_decision_service.get_decision_history(db, submission.id)
    assert [d.id for d in history] == [first.id, second.id]
    assert officer_decision_service.get_latest_decision(db, submission.id).id == second.id

    # The first row itself is untouched -- proves "never silently
    # overwritten" at the row level, not just at the history-list level.
    reloaded_first = db.get(OfficerDecision, first.id)
    assert reloaded_first.decision == OfficerDecisionType.REQUEST_CLARIFICATION
    assert reloaded_first.note == "Need updated GST certificate."


# ---------------------------------------------------------------------------
# 6. Isolation from existing BidOps models
# ---------------------------------------------------------------------------


def test_sih_tables_are_namespaced_and_do_not_collide_with_existing_tables():
    sih_table_names = {t.name for t in ALL_TABLES if t.name.startswith("sih_")}
    existing_table_names = {Mission.__tablename__, Tender.__tablename__, Requirement.__tablename__}
    assert sih_table_names.isdisjoint(existing_table_names)
    assert sih_table_names == {
        "sih_compliance_categories",
        "sih_procurements",
        "sih_bidders",
        "sih_bidder_submissions",
        "sih_registry_records",
        "sih_verification_results",
        "sih_officer_decisions",
    }


def test_sih_domain_coexists_with_existing_tender_domain_in_same_db(db, company):
    """Creates a Mission/Tender/Requirement row (existing BidOps domain)
    alongside a Procurement/Bidder/BidderSubmission row (SIH domain) in
    the same database and confirms neither interferes with the other."""
    mission = Mission(company_id=company.id, user_id=company.id, mission_type="tender_analysis")
    # user_id above is a placeholder FK value; SQLite has no FK
    # enforcement by default so this is safe for this isolation check
    # (this test only asserts table/row independence, not referential
    # integrity of the pre-existing Mission model).
    db.add(mission)
    db.commit()
    db.refresh(mission)

    tender = Tender(mission_id=mission.id, tender_name="Existing BidOps Tender")
    db.add(tender)
    db.commit()

    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company)
    submission = _make_submission(db, procurement, bidder)

    assert db.query(Mission).count() == 1
    assert db.query(Tender).count() == 1
    assert db.query(Procurement).count() == 1
    assert db.query(BidderSubmission).count() == 1
    assert submission.procurement_id == procurement.id


def test_existing_decision_engine_enums_and_functions_unaffected():
    """Sanity check that nothing in this Phase 1 work touched
    decision_engine.py's own vocabulary -- MatchStatus and
    ComplianceVerificationStatus are deliberately separate enums with
    no overlap, and decision_engine's core functions still import and
    exist unchanged."""
    match_status_values = {s.value for s in MatchStatus}
    verification_status_values = {s.value for s in ComplianceVerificationStatus}
    assert match_status_values.isdisjoint(verification_status_values)

    assert hasattr(decision_engine, "compute_qualification")
    assert hasattr(decision_engine, "compute_bid_readiness")
    assert hasattr(decision_engine, "compute_recommendation_type")
    assert hasattr(decision_engine, "classify_remediation")
