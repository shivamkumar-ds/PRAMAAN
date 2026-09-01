"""
Regression coverage for RequirementNature classification (architecture
debate Phase 1 — see BidOps_Architecture_Debate.md and RequirementNature's
docstring in app/models/enums.py).

Tests 1-5 exercise tender_analyzer._resolve_nature() directly against
hand-constructed ExtractedRequirement objects — this is deliberate, not
a shortcut: mock_extraction.py's regex-based mock (sandbox verification
only, see its module docstring) does not simulate nature classification
and never populates requirement_nature, so the EMD/PPE/similar-works
worked examples the user specified can only be exercised as direct unit
tests of the resolver, not through a full LLM-mocked pipeline. Tests 6-7
exercise the real persistence path (tender_service.run_analysis, exactly
the pattern established in test_tender_multi_document.py) end-to-end
with provider="mock", which is what actually proves the procedural
override and missing-value fallback survive a real extraction ->
persistence round-trip.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.tender_analyzer import _resolve_nature
from app.core import storage
from app.core.database import Base
from app.models import Company, Document, Mission, Requirement, Tender, User
from app.models.enums import (
    DocumentProcessingStatus,
    MissionStatus,
    RequirementNature,
    UserRole,
    UserStatus,
)
from app.schemas.extraction import ExtractedRequirement
from app.services import tender_service


# ---------------------------------------------------------------------------
# Shared fixtures (same pattern as test_tender_multi_document.py)
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__, User.__table__, Mission.__table__, Tender.__table__,
            Requirement.__table__, Document.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_company_and_user(db):
    company = Company(id=uuid.uuid4(), name="Acme", registration_number=str(uuid.uuid4()))
    db.add(company)
    db.flush()
    user = User(
        id=uuid.uuid4(), company_id=company.id, name="Admin", email=f"{uuid.uuid4()}@example.com",
        password_hash="x", role=UserRole.ADMINISTRATOR, status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.flush()
    return company, user


# ---------------------------------------------------------------------------
# Test 1 — procedural override wins regardless of what the LLM returned
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("requirement_type", ["deadline", "submission", "evaluation_criteria"])
@pytest.mark.parametrize(
    "llm_returned_nature", [None, "capability_claim", "submission_gating", "garbage_value"]
)
def test_procedural_types_always_resolve_to_procedural(requirement_type, llm_returned_nature):
    req = ExtractedRequirement(
        requirement_type=requirement_type,
        description="irrelevant for this test",
        mandatory=True,
        source_page=1,
        requirement_nature=llm_returned_nature,
    )
    assert _resolve_nature(req) == RequirementNature.PROCEDURAL.value


# ---------------------------------------------------------------------------
# Test 2 — valid CAPABILITY_CLAIM classification on eligible types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("requirement_type", ["eligibility", "technical", "certification", "experience"])
def test_valid_capability_claim_passthrough(requirement_type):
    req = ExtractedRequirement(
        requirement_type=requirement_type,
        description="Bidder shall have completed three similar works during the last 5 years.",
        mandatory=True,
        source_page=1,
        requirement_nature="capability_claim",
    )
    assert _resolve_nature(req) == RequirementNature.CAPABILITY_CLAIM.value


# ---------------------------------------------------------------------------
# Test 3 — valid SUBMISSION_GATING classification on eligible types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("requirement_type", ["eligibility", "technical", "certification", "experience"])
def test_valid_submission_gating_passthrough(requirement_type):
    req = ExtractedRequirement(
        requirement_type=requirement_type,
        description="Bidder shall submit EMD along with the bid.",
        mandatory=True,
        source_page=1,
        requirement_nature="submission_gating",
    )
    assert _resolve_nature(req) == RequirementNature.SUBMISSION_GATING.value


# ---------------------------------------------------------------------------
# Test 4 — valid FUTURE_CONTRACTUAL_COMMITMENT classification on eligible types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("requirement_type", ["eligibility", "technical", "certification", "experience"])
def test_valid_future_contractual_commitment_passthrough(requirement_type):
    req = ExtractedRequirement(
        requirement_type=requirement_type,
        description="Contractor shall maintain PPE and safety compliance during execution.",
        mandatory=True,
        source_page=1,
        requirement_nature="future_contractual_commitment",
    )
    assert _resolve_nature(req) == RequirementNature.FUTURE_CONTRACTUAL_COMMITMENT.value


# ---------------------------------------------------------------------------
# Test 5 — invalid/missing LLM output falls back to CAPABILITY_CLAIM
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("requirement_type", ["eligibility", "technical", "certification", "experience"])
@pytest.mark.parametrize(
    "llm_returned_nature", [None, "", "garbage_value", "unknown", "procedural"]
)
def test_invalid_or_missing_nature_falls_back_to_capability_claim(requirement_type, llm_returned_nature):
    req = ExtractedRequirement(
        requirement_type=requirement_type,
        description="irrelevant for this test",
        mandatory=True,
        source_page=1,
        requirement_nature=llm_returned_nature,
    )
    assert _resolve_nature(req) == RequirementNature.CAPABILITY_CLAIM.value


def test_fallback_is_logged_for_observability(caplog):
    """The user's instruction: 'make fallback occurrences observable so we
    can identify extraction-quality problems later' -- without a new DB
    column. Confirmed here via the standard logging module rather than a
    persisted flag."""
    req = ExtractedRequirement(
        requirement_type="eligibility",
        description="irrelevant for this test",
        mandatory=True,
        source_page=1,
        requirement_nature=None,
    )
    with caplog.at_level("WARNING"):
        _resolve_nature(req)
    assert any("fallback to CAPABILITY_CLAIM" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Test 6 — persistence: resolved nature actually reaches the Requirement row
# ---------------------------------------------------------------------------


def test_persisted_requirement_carries_resolved_nature(tmp_path, monkeypatch, db):
    """End-to-end through the real persistence path (tender_service.
    run_analysis -> tender_analyzer.analyze_tender, provider='mock'),
    exactly the pattern test_tender_multi_document.py already
    established. The mock never populates requirement_nature, so every
    resulting row here exercises the fallback/override paths, not a
    trusted LLM value -- proving Tests 1-5's logic survives the real
    write path, not just the pure function in isolation."""
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    from reportlab.pdfgen import canvas
    import io

    company, user = _make_company_and_user(db)
    mission = Mission(
        id=uuid.uuid4(), company_id=company.id, user_id=user.id,
        mission_type="tender_evaluation", status=MissionStatus.CREATED,
    )
    db.add(mission)
    db.flush()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    c.drawString(50, 750, "Eligibility: Bidder must have completed similar works during the last 5 years.")
    c.drawString(50, 730, "Deadline: Bids must be submitted by the closing date.")
    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()

    doc_dir = tmp_path / str(company.id) / "documents"
    doc_dir.mkdir(parents=True)
    doc_path = doc_dir / f"{uuid.uuid4()}.pdf"
    doc_path.write_bytes(pdf_bytes)

    document = Document(
        id=uuid.uuid4(), company_id=company.id, uploaded_by=user.id, document_type="tender",
        file_name="tender.pdf", storage_path=str(doc_path.relative_to(tmp_path)),
    )
    db.add(document)
    db.flush()

    tender = Tender(
        id=uuid.uuid4(), mission_id=mission.id, tender_name="Nature Test Tender",
        organization="Test Org", uploaded_document=document.id,
        processing_status=DocumentProcessingStatus.PENDING.value,
    )
    db.add(tender)
    db.flush()
    document.tender_id = tender.id
    document.document_role = "main"
    db.commit()

    result_tender, requirements = asyncio.run(
        tender_service.run_analysis(db, tender.id, company.id, provider="mock")
    )

    assert result_tender.processing_status == DocumentProcessingStatus.COMPLETED.value
    assert len(requirements) == 2
    by_type = {r.requirement_type.value: r for r in requirements}

    # Eligibility row: mock never sets requirement_nature -> fallback fires.
    assert by_type["eligibility"].requirement_nature == RequirementNature.CAPABILITY_CLAIM

    # Deadline row: deterministic PROCEDURAL override, unconditionally.
    assert by_type["deadline"].requirement_nature == RequirementNature.PROCEDURAL

    # Confirm it's actually the persisted DB row, not just the in-memory object.
    persisted = db.query(Requirement).filter_by(tender_id=tender.id).all()
    persisted_natures = {r.requirement_type.value: r.requirement_nature for r in persisted}
    assert persisted_natures["eligibility"] == RequirementNature.CAPABILITY_CLAIM
    assert persisted_natures["deadline"] == RequirementNature.PROCEDURAL


# ---------------------------------------------------------------------------
# Test 7 — backward compatibility: NULL requirement_nature on old rows
# ---------------------------------------------------------------------------


def test_existing_requirement_row_with_null_nature_loads_correctly(db):
    """A Requirement row persisted before this migration (or by any other
    code path that doesn't set requirement_nature) must remain valid and
    loadable — Phase 1's nullable-column, no-backfill design. This also
    documents Phase 1's own scope boundary: nothing about how this
    historical row would be evaluated changes, because decision_engine.py
    doesn't read this column yet."""
    company, user = _make_company_and_user(db)
    mission = Mission(
        id=uuid.uuid4(), company_id=company.id, user_id=user.id,
        mission_type="tender_evaluation", status=MissionStatus.CREATED,
    )
    db.add(mission)
    db.flush()
    tender = Tender(
        id=uuid.uuid4(), mission_id=mission.id, tender_name="Pre-existing Tender",
        organization="Test Org", processing_status=DocumentProcessingStatus.COMPLETED.value,
    )
    db.add(tender)
    db.flush()

    from app.models.enums import RequirementType

    requirement = Requirement(
        tender_id=tender.id,
        requirement_type=RequirementType.ELIGIBILITY,
        description="A historical requirement predating requirement_nature.",
        mandatory=True,
        source_page=1,
        # requirement_nature deliberately omitted -- simulates a pre-Phase-1 row.
    )
    db.add(requirement)
    db.commit()

    db.expire_all()
    reloaded = db.query(Requirement).filter_by(id=requirement.id).one()
    assert reloaded.requirement_nature is None
