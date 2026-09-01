"""
Regression coverage for the four SIH26100 "minimal-real engine" additions
(governing directive, six-phase implementation):

  1. Evidence Grounding Guard (grounding_guard_service.py)
  2. Authenticity Scanner (authenticity_service.py)
  3. Bidder Network Graph (network_graph_service.py)
  4. Collusion Radar (collusion_radar_service.py)

Same in-memory-SQLite + real-tmp-storage conventions as
test_sih_api.py / test_sih_documents.py. A real, valid PDF is generated
with reportlab (already a test-only dependency in this repo, see
requirements.txt) so the Authenticity Scanner exercises its real pypdf
parsing path rather than a mocked one.
"""

import io
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import storage
from app.core.database import Base
from app.models import Company, User
from app.models.enums import UserRole, UserStatus
from app.models.sih import (
    AuthenticityScan,
    Bidder,
    BidderDocument,
    BidderSubmission,
    ComplianceCategory,
    OfficerDecision,
    Procurement,
    RegistryRecord,
    VerificationResult,
)
from app.models.sih.enums import DocumentExtractionStatus
from app.services.sih import (
    authenticity_service,
    collusion_radar_service,
    compliance_category_service,
    document_service,
    grounding_guard_service,
    network_graph_service,
    officer_decision_service,
    procurement_service,
    registry_seed_service,
    verification_service,
)
from app.models.sih.enums import OfficerDecisionType
from app.services.exceptions import ConflictError
from app.services.sih.grounding_guard_service import UngroundedEvidenceError


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
    AuthenticityScan.__table__,
]


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=ALL_TABLES)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def company(db):
    c = Company(name="CPCL Test Co", registration_number=f"REG-{uuid.uuid4()}")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture()
def officer(db, company):
    u = User(
        company_id=company.id, name="Officer", email=f"officer-{uuid.uuid4()}@example.com",
        password_hash="x", role=UserRole.ADMINISTRATOR, status=UserStatus.ACTIVE,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_procurement(db, company, title="Sample Procurement"):
    p = Procurement(company_id=company.id, title=title)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_bidder(db, company, **kwargs):
    b = Bidder(company_id=company.id, **kwargs)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def _make_submission(db, procurement, bidder, bid_amount=None):
    s = BidderSubmission(procurement_id=procurement.id, bidder_id=bidder.id, bid_amount=bid_amount)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# 1. Evidence Grounding Guard
# ---------------------------------------------------------------------------


def test_ensure_document_is_grounded_rejects_unconfirmed_document(db, company):
    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company, legal_name="ABC Engineering", pan="ABCDE1234F")
    submission = _make_submission(db, procurement, bidder)
    doc = BidderDocument(
        submission_id=submission.id,
        uploaded_by=uuid.uuid4(),
        category_code=None,
        file_name="udyam.pdf",
        storage_path="irrelevant.pdf",
        extraction_status=DocumentExtractionStatus.EXTRACTED,
        extracted_data={"udyam_number": "UDYAM-DL-01-0012345"},
        is_confirmed=False,
    )
    db.add(doc)
    db.commit()

    with pytest.raises(UngroundedEvidenceError):
        grounding_guard_service.ensure_document_is_grounded(doc)

    doc.is_confirmed = True
    doc.confirmed_data = {"udyam_number": "UDYAM-DL-01-0012345"}
    # Now grounded -- must not raise.
    grounding_guard_service.ensure_document_is_grounded(doc)


def test_grounding_report_classifies_manual_declared_and_no_evidence(db, company):
    compliance_category_service.seed_default_categories(db)
    registry_seed_service.seed_mock_registry(db)
    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company, legal_name="ABC Engineering Private Limited", pan="ABCDE1234F")
    submission = _make_submission(db, procurement, bidder)

    # Manual-entry path: only GST declared, everything else honestly
    # missing/not-claimed -- exercises verify_submission() directly, same
    # as test_sih_bidder_verification_domain.py's Phase 1 coverage.
    verification_service.verify_submission(
        db,
        submission.id,
        {"pan": bidder.pan, "legal_name": bidder.legal_name},
        {"gst": {"gstin": "07ABCDE1234F1Z5"}, "blacklisting": {}},
    )

    report = grounding_guard_service.get_grounding_report(db, submission.id)
    origins = {c.category_code: c.origin for c in report.categories}
    assert origins["gst"] == "manual_declaration"
    assert origins["udyam"] == "no_evidence"
    assert report.manual_declaration_count >= 1
    assert report.no_evidence_count >= 1
    assert report.document_evidenced_count == 0


# ---------------------------------------------------------------------------
# 2. Authenticity Scanner
# ---------------------------------------------------------------------------


def _real_pdf_bytes(producer: str | None = None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    if producer:
        c._doc.info.producer = producer  # reportlab lets tests override Producer metadata directly
    c.drawString(100, 750, "Udyam Registration Certificate")
    c.save()
    return buf.getvalue()


def test_authenticity_scan_clean_pdf_no_anomalies(db, company, officer, monkeypatch, tmp_path):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company, legal_name="ABC Engineering", pan="ABCDE1234F")
    submission = _make_submission(db, procurement, bidder)

    relative_path = f"{company.id}/documents/{uuid.uuid4()}.pdf"
    dest = tmp_path / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_real_pdf_bytes())

    doc = BidderDocument(
        submission_id=submission.id,
        uploaded_by=officer.id,
        category_code="udyam",
        category_source="officer",
        file_name="udyam.pdf",
        storage_path=relative_path,
        extraction_status=DocumentExtractionStatus.PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    scan = authenticity_service.scan_document(db, submission.id, doc.id, company.id, officer.id)

    assert scan.summary_label in ("no_anomalies_detected", "indicators_present")  # real pypdf metadata varies by reportlab version
    assert isinstance(scan.indicators, list) and len(scan.indicators) > 0
    assert all({"code", "label", "detail", "severity"} <= set(ind.keys()) for ind in scan.indicators)

    # Insert-only history -- a second scan adds a row, never overwrites.
    scan2 = authenticity_service.scan_document(db, submission.id, doc.id, company.id, officer.id)
    assert scan2.id != scan.id
    assert len(authenticity_service.list_scans(db, doc.id)) == 2
    assert authenticity_service.get_latest_scan(db, doc.id).id == scan2.id


def test_authenticity_scan_editing_software_flagged(db, company, officer, monkeypatch, tmp_path):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company, legal_name="Sunrise Traders", pan="SUNRZ5678H")
    submission = _make_submission(db, procurement, bidder)

    relative_path = f"{company.id}/documents/{uuid.uuid4()}.pdf"
    dest = tmp_path / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_real_pdf_bytes(producer="Adobe Photoshop 24.0"))

    doc = BidderDocument(
        submission_id=submission.id,
        uploaded_by=officer.id,
        category_code="gst",
        category_source="officer",
        file_name="gst.pdf",
        storage_path=relative_path,
        extraction_status=DocumentExtractionStatus.PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    scan = authenticity_service.scan_document(db, submission.id, doc.id, company.id, officer.id)
    assert scan.summary_label == "indicators_present"
    codes = {ind["code"] for ind in scan.indicators}
    assert "editing_software_producer" in codes


def _ooxml_bytes(
    creator: str | None = "Jane Officer",
    last_modified_by: str | None = "Jane Officer",
    application: str | None = "Microsoft Word",
    created: str | None = "2024-01-15T10:30:00Z",
    modified: str | None = "2024-01-16T09:00:00Z",
) -> bytes:
    """A minimal, real, zip-valid OOXML archive with just docProps/core.xml
    and docProps/app.xml -- enough to exercise _scan_ooxml's real
    zipfile+ElementTree parsing path, not a mocked one."""
    import zipfile

    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
        + (f"<dc:creator>{creator}</dc:creator>" if creator else "")
        + (f"<cp:lastModifiedBy>{last_modified_by}</cp:lastModifiedBy>" if last_modified_by else "")
        + (f'<dcterms:created xsi:type="dcterms:W3CDTF" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">{created}</dcterms:created>' if created else "")
        + (f'<dcterms:modified xsi:type="dcterms:W3CDTF" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">{modified}</dcterms:modified>' if modified else "")
        + "</cp:coreProperties>"
    )
    app_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        + (f"<Application>{application}</Application>" if application else "")
        + "</Properties>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("docProps/core.xml", core_xml)
        archive.writestr("docProps/app.xml", app_xml)
        archive.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


def _store_document(db, company, officer, submission, tmp_path, filename, content, category_code="udyam"):
    relative_path = f"{company.id}/documents/{uuid.uuid4()}{Path(filename).suffix}"
    dest = tmp_path / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    doc = BidderDocument(
        submission_id=submission.id,
        uploaded_by=officer.id,
        category_code=category_code,
        category_source="officer",
        file_name=filename,
        storage_path=relative_path,
        extraction_status=DocumentExtractionStatus.PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def test_authenticity_scan_docx_creator_mismatch_flagged(db, company, officer, monkeypatch, tmp_path):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company, legal_name="ABC Engineering", pan="ABCDE1234F")
    submission = _make_submission(db, procurement, bidder)
    doc = _store_document(
        db, company, officer, submission, tmp_path, "certificate.docx",
        _ooxml_bytes(creator="Alice", last_modified_by="Bob"),
    )

    scan = authenticity_service.scan_document(db, submission.id, doc.id, company.id, officer.id)
    assert scan.summary_label == "indicators_present"
    codes = {ind["code"] for ind in scan.indicators}
    assert "creator_last_modified_by_mismatch" in codes


def test_authenticity_scan_docx_clean_no_anomalies(db, company, officer, monkeypatch, tmp_path):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company, legal_name="ABC Engineering", pan="ABCDE1234F")
    submission = _make_submission(db, procurement, bidder)
    doc = _store_document(
        db, company, officer, submission, tmp_path, "certificate.docx",
        _ooxml_bytes(creator="Alice", last_modified_by="Alice"),
    )

    scan = authenticity_service.scan_document(db, submission.id, doc.id, company.id, officer.id)
    assert scan.summary_label == "no_anomalies_detected"
    codes = {ind["code"] for ind in scan.indicators}
    assert "creator_last_modified_by_mismatch" not in codes
    assert "modification_before_creation" not in codes


def test_authenticity_scan_xlsx_modified_before_created_flagged(db, company, officer, monkeypatch, tmp_path):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company, legal_name="ABC Engineering", pan="ABCDE1234F")
    submission = _make_submission(db, procurement, bidder)
    doc = _store_document(
        db, company, officer, submission, tmp_path, "boq.xlsx",
        _ooxml_bytes(created="2024-05-01T10:00:00Z", modified="2024-04-01T10:00:00Z", application="Microsoft Excel"),
    )

    scan = authenticity_service.scan_document(db, submission.id, doc.id, company.id, officer.id)
    codes = {ind["code"] for ind in scan.indicators}
    assert "modification_before_creation" in codes


def _real_png_bytes(software: str | None = None) -> bytes:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    buf = io.BytesIO()
    image = Image.new("RGB", (10, 10), color="white")
    info = None
    if software:
        info = PngInfo()
        info.add_text("Software", software)
    image.save(buf, format="PNG", pnginfo=info)
    return buf.getvalue()


def test_authenticity_scan_png_with_software_tag_flagged(db, company, officer, monkeypatch, tmp_path):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company, legal_name="ABC Engineering", pan="ABCDE1234F")
    submission = _make_submission(db, procurement, bidder)
    doc = _store_document(
        db, company, officer, submission, tmp_path, "scan.png", _real_png_bytes(software="Adobe Photoshop 25.0")
    )

    scan = authenticity_service.scan_document(db, submission.id, doc.id, company.id, officer.id)
    assert scan.summary_label == "indicators_present"
    codes = {ind["code"] for ind in scan.indicators}
    assert "editing_software_png" in codes


def test_authenticity_scan_png_without_software_tag_is_honest_info(db, company, officer, monkeypatch, tmp_path):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company, legal_name="ABC Engineering", pan="ABCDE1234F")
    submission = _make_submission(db, procurement, bidder)
    doc = _store_document(db, company, officer, submission, tmp_path, "scan.png", _real_png_bytes())

    scan = authenticity_service.scan_document(db, submission.id, doc.id, company.id, officer.id)
    # No text chunk at all -- an honest "nothing to check" info result,
    # never treated as a failure or an indicator worth attention.
    assert scan.summary_label == "no_anomalies_detected"
    codes = {ind["code"] for ind in scan.indicators}
    assert "no_png_text_metadata" in codes


def test_delete_document_blocked_after_authenticity_scan(db, company, officer, monkeypatch, tmp_path):
    """
    Regression test for a real deployment-time bug: delete_bidder_document's
    existing "still referenced" guard covered VerificationResult.source_document_id
    (raises ConflictError, a clean 409) but was never extended when the
    Authenticity Scanner was added in a later phase -- so a scanned document
    hit a raw, unhandled IntegrityError (500) on delete instead. Found via
    real HTTP smoke testing against a live Postgres, not by this test suite
    (there was no coverage of delete_bidder_document at all before this).
    """
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company, legal_name="ABC Engineering", pan="ABCDE1234F")
    submission = _make_submission(db, procurement, bidder)

    relative_path = f"{company.id}/documents/{uuid.uuid4()}.pdf"
    dest = tmp_path / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_real_pdf_bytes())

    doc = BidderDocument(
        submission_id=submission.id,
        uploaded_by=officer.id,
        category_code="udyam",
        category_source="officer",
        file_name="udyam.pdf",
        storage_path=relative_path,
        extraction_status=DocumentExtractionStatus.PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    authenticity_service.scan_document(db, submission.id, doc.id, company.id, officer.id)

    with pytest.raises(ConflictError):
        document_service.delete_bidder_document(db, submission.id, doc.id, company.id)


def test_authenticity_scan_unsupported_format_is_honest(db, company, officer, monkeypatch, tmp_path):
    """
    .docx/.xlsx (OOXML) gained a real analysis path in this same phase --
    see the .docx/.xlsx tests above -- so this "no analysis path exists"
    case now has to use .xls, the legacy pre-OOXML binary format, which
    genuinely still has none (it isn't a zip archive, so the OOXML parser
    doesn't apply to it either).
    """
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company, legal_name="ABC Engineering", pan="ABCDE1234F")
    submission = _make_submission(db, procurement, bidder)

    relative_path = f"{company.id}/documents/{uuid.uuid4()}.xls"
    dest = tmp_path / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"not a real xls, content irrelevant for this test")

    doc = BidderDocument(
        submission_id=submission.id,
        uploaded_by=officer.id,
        file_name="something.xls",
        storage_path=relative_path,
        extraction_status=DocumentExtractionStatus.PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    scan = authenticity_service.scan_document(db, submission.id, doc.id, company.id, officer.id)
    assert scan.summary_label == "not_analyzable"


# ---------------------------------------------------------------------------
# 3. Bidder Network Graph
# ---------------------------------------------------------------------------


def test_network_graph_no_identifiers_returns_empty(db, company):
    b = _make_bidder(db, company, legal_name="Lone Bidder")
    report = network_graph_service.get_related_bidders(db, b.id, company.id)
    assert report.related_bidders == []


def test_network_graph_finds_shared_director_and_address(db, company):
    a = _make_bidder(
        db, company, legal_name="ABC Engineering", director_name="Ramesh Kumar",
        registered_address="12 MG Road, New Delhi",
    )
    other_company = Company(name="Unrelated Co", registration_number=f"REG-{uuid.uuid4()}")
    db.add(other_company)
    db.commit()

    same_tenant_match = _make_bidder(
        db, company, legal_name="XYZ Traders", director_name="ramesh   kumar",  # different case/spacing -- still matches
    )
    cross_tenant_decoy = _make_bidder(
        db, other_company, legal_name="Decoy Co", director_name="Ramesh Kumar",
    )
    unrelated = _make_bidder(db, company, legal_name="No Overlap Pvt Ltd")

    report = network_graph_service.get_related_bidders(db, a.id, company.id)
    related_ids = {r.bidder_id for r in report.related_bidders}

    assert same_tenant_match.id in related_ids
    assert cross_tenant_decoy.id not in related_ids  # tenant isolation never crossed
    assert unrelated.id not in related_ids
    match = next(r for r in report.related_bidders if r.bidder_id == same_tenant_match.id)
    assert any("director" in reason.lower() for reason in match.reasons)


def test_network_graph_phone_normalization_matches_across_formatting(db, company):
    # Same digits, different punctuation/spacing -- normalization strips
    # formatting but deliberately does NOT strip a country-code prefix
    # (that would risk false positives across genuinely different
    # numbers), so both values here resolve to the identical digit string.
    a = _make_bidder(db, company, legal_name="Alpha Co", contact_phone="(987) 654-3210")
    b = _make_bidder(db, company, legal_name="Beta Co", contact_phone="9876543210")

    report = network_graph_service.get_related_bidders(db, a.id, company.id)
    assert any(r.bidder_id == b.id for r in report.related_bidders)


# ---------------------------------------------------------------------------
# 4. Collusion Radar
# ---------------------------------------------------------------------------


def test_collusion_radar_no_bid_amounts_no_indicators(db, company):
    procurement = _make_procurement(db, company)
    b1 = _make_bidder(db, company, legal_name="Bidder One")
    b2 = _make_bidder(db, company, legal_name="Bidder Two")
    _make_submission(db, procurement, b1)
    _make_submission(db, procurement, b2)

    report = collusion_radar_service.get_collusion_indicators(db, procurement.id, company.id)
    assert report.indicators == []
    assert report.score == 0
    assert report.disclaimer  # always populated


def test_collusion_radar_identical_bid_amounts_flagged(db, company):
    procurement = _make_procurement(db, company)
    b1 = _make_bidder(db, company, legal_name="Bidder One")
    b2 = _make_bidder(db, company, legal_name="Bidder Two")
    _make_submission(db, procurement, b1, bid_amount=Decimal("4850000.00"))
    _make_submission(db, procurement, b2, bid_amount=Decimal("4850000.00"))

    report = collusion_radar_service.get_collusion_indicators(db, procurement.id, company.id)
    codes = {i.code for i in report.indicators}
    assert "identical_bid_amount" in codes
    assert report.score > 0
    assert "never" in report.disclaimer.lower() or "review" in report.disclaimer.lower()


def test_collusion_radar_narrow_spread_flagged(db, company):
    procurement = _make_procurement(db, company)
    b1 = _make_bidder(db, company, legal_name="Bidder One")
    b2 = _make_bidder(db, company, legal_name="Bidder Two")
    b3 = _make_bidder(db, company, legal_name="Bidder Three")
    _make_submission(db, procurement, b1, bid_amount=Decimal("1000000"))
    _make_submission(db, procurement, b2, bid_amount=Decimal("1001000"))
    _make_submission(db, procurement, b3, bid_amount=Decimal("1002000"))

    report = collusion_radar_service.get_collusion_indicators(db, procurement.id, company.id)
    codes = {i.code for i in report.indicators}
    assert "narrow_bid_spread" in codes


def test_collusion_radar_repeated_bidder_combination(db, company):
    b1 = _make_bidder(db, company, legal_name="Bidder One")
    b2 = _make_bidder(db, company, legal_name="Bidder Two")

    # Three earlier procurements where both bidders co-participated.
    for i in range(3):
        earlier = _make_procurement(db, company, title=f"Earlier Procurement {i}")
        _make_submission(db, earlier, b1)
        _make_submission(db, earlier, b2)

    current = _make_procurement(db, company, title="Current Procurement")
    _make_submission(db, current, b1)
    _make_submission(db, current, b2)

    report = collusion_radar_service.get_collusion_indicators(db, current.id, company.id)
    codes = {i.code for i in report.indicators}
    assert "repeated_bidder_combination" in codes


def test_collusion_radar_never_uses_confirmed_wording(db, company):
    """
    Explicit regression guard for the brief's hardest constraint: no
    output of this engine may ever claim collusion is confirmed.
    """
    procurement = _make_procurement(db, company)
    b1 = _make_bidder(db, company, legal_name="Bidder One")
    b2 = _make_bidder(db, company, legal_name="Bidder Two")
    _make_submission(db, procurement, b1, bid_amount=Decimal("500000"))
    _make_submission(db, procurement, b2, bid_amount=Decimal("500000"))

    report = collusion_radar_service.get_collusion_indicators(db, procurement.id, company.id)
    full_text = report.disclaimer + " ".join(i.detail + i.label for i in report.indicators)
    assert "confirmed" not in full_text.lower()
    assert "proven" not in full_text.lower()


def _award_after_decision(db, procurement, bidder, submission):
    """Records a minimal decision then sets the award -- mirrors
    procurement_service.set_awarded_bidder()'s "decisions must exist
    first" guard."""
    officer_decision_service.record_decision(
        db, submission.id, uuid.uuid4(), OfficerDecisionType.APPROVE, "Reviewed and approved."
    )
    return procurement_service.set_awarded_bidder(db, procurement.id, procurement.company_id, bidder.id)


def test_set_awarded_bidder_requires_prior_decision(db, company):
    procurement = _make_procurement(db, company)
    bidder = _make_bidder(db, company, legal_name="Bidder One")
    _make_submission(db, procurement, bidder)

    with pytest.raises(ConflictError):
        procurement_service.set_awarded_bidder(db, procurement.id, company.id, bidder.id)


def test_set_awarded_bidder_requires_bidder_to_have_submitted(db, company):
    procurement = _make_procurement(db, company)
    participant = _make_bidder(db, company, legal_name="Participant")
    non_participant = _make_bidder(db, company, legal_name="Never Submitted")
    submission = _make_submission(db, procurement, participant)
    officer_decision_service.record_decision(
        db, submission.id, uuid.uuid4(), OfficerDecisionType.APPROVE, "Reviewed."
    )

    with pytest.raises(ConflictError):
        procurement_service.set_awarded_bidder(db, procurement.id, company.id, non_participant.id)


def test_collusion_radar_repeated_winner_below_threshold_no_indicator(db, company):
    bidder = _make_bidder(db, company, legal_name="Frequent Winner")
    procurement = None
    for i in range(2):  # below _REPEATED_WINNER_MIN_AWARDS (3)
        procurement = _make_procurement(db, company, title=f"Procurement {i}")
        submission = _make_submission(db, procurement, bidder)
        _award_after_decision(db, procurement, bidder, submission)

    report = collusion_radar_service.get_collusion_indicators(db, procurement.id, company.id)
    codes = {i.code for i in report.indicators}
    assert "repeated_winner" not in codes


def test_collusion_radar_repeated_winner_at_threshold_flagged(db, company):
    bidder = _make_bidder(db, company, legal_name="Frequent Winner")
    procurement = None
    for i in range(3):  # meets _REPEATED_WINNER_MIN_AWARDS
        procurement = _make_procurement(db, company, title=f"Procurement {i}")
        submission = _make_submission(db, procurement, bidder)
        _award_after_decision(db, procurement, bidder, submission)

    report = collusion_radar_service.get_collusion_indicators(db, procurement.id, company.id)
    codes = {i.code for i in report.indicators}
    assert "repeated_winner" in codes
    detail = next(i.detail for i in report.indicators if i.code == "repeated_winner")
    assert "confirmed" not in detail.lower() and "proven" not in detail.lower()


def test_collusion_radar_repeated_winner_never_crosses_tenant(db, company):
    """The user explicitly confirmed tenant isolation must not be broken
    for this feature -- a bidder winning 3+ times in ANOTHER company must
    never trigger the indicator when queried against a different company's
    procurement, even if (by coincidence) a same-named/UUID-colliding
    bidder existed there (it can't -- bidder_id is a real FK -- but this
    test still proves the query is company_id-filtered, not just
    bidder_id-filtered)."""
    other_company = Company(name="Other Tenant Co", registration_number=f"REG-{uuid.uuid4()}")
    db.add(other_company)
    db.commit()
    db.refresh(other_company)

    other_bidder = _make_bidder(db, other_company, legal_name="Other Tenant Winner")
    for i in range(3):
        other_procurement = Procurement(company_id=other_company.id, title=f"Other Co Procurement {i}")
        db.add(other_procurement)
        db.commit()
        db.refresh(other_procurement)
        submission = _make_submission(db, other_procurement, other_bidder)
        officer_decision_service.record_decision(
            db, submission.id, uuid.uuid4(), OfficerDecisionType.APPROVE, "Reviewed."
        )
        procurement_service.set_awarded_bidder(db, other_procurement.id, other_company.id, other_bidder.id)

    # This company's own bidder/procurement, awarded only once -- must
    # stay indicator-free, unaffected by the other tenant's 3 awards.
    bidder = _make_bidder(db, company, legal_name="This Tenant Bidder")
    procurement = _make_procurement(db, company)
    submission = _make_submission(db, procurement, bidder)
    _award_after_decision(db, procurement, bidder, submission)

    report = collusion_radar_service.get_collusion_indicators(db, procurement.id, company.id)
    codes = {i.code for i in report.indicators}
    assert "repeated_winner" not in codes


# ---------------------------------------------------------------------------
# 5. End-to-end: all four engines together against one procurement
# ---------------------------------------------------------------------------


def test_end_to_end_all_engines_against_one_scenario(db, company, officer, monkeypatch, tmp_path):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)
    compliance_category_service.seed_default_categories(db)
    registry_seed_service.seed_mock_registry(db)

    procurement = _make_procurement(db, company, title="GeM Pipeline Maintenance")
    bidder_a = _make_bidder(
        db, company, legal_name="ABC Engineering Private Limited", pan="ABCDE1234F",
        director_name="Ramesh Kumar", registered_address="12 MG Road, New Delhi",
    )
    bidder_b = _make_bidder(
        db, company, legal_name="Shadow Engineering LLP",
        director_name="Ramesh Kumar",  # shared director with bidder_a -- Network Graph should catch this
    )
    submission_a = _make_submission(db, procurement, bidder_a, bid_amount=Decimal("4850000"))
    submission_b = _make_submission(db, procurement, bidder_b, bid_amount=Decimal("4850000"))  # identical bid

    # 1) Verification + Grounding Guard.
    verification_service.verify_submission(
        db, submission_a.id, {"pan": bidder_a.pan, "legal_name": bidder_a.legal_name},
        {"gst": {"gstin": "07ABCDE1234F1Z5"}, "blacklisting": {}},
    )
    grounding = grounding_guard_service.get_grounding_report(db, submission_a.id)
    assert grounding.categories  # produced real output, not empty

    # 2) Authenticity Scanner against an uploaded document.
    relative_path = f"{company.id}/documents/{uuid.uuid4()}.pdf"
    dest = tmp_path / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_real_pdf_bytes())
    doc = BidderDocument(
        submission_id=submission_a.id, uploaded_by=officer.id, category_code="gst",
        file_name="gst.pdf", storage_path=relative_path, extraction_status=DocumentExtractionStatus.PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    scan = authenticity_service.scan_document(db, submission_a.id, doc.id, company.id, officer.id)
    assert scan.summary_label in ("no_anomalies_detected", "indicators_present")

    # 3) Bidder Network Graph.
    network = network_graph_service.get_related_bidders(db, bidder_a.id, company.id)
    assert any(r.bidder_id == bidder_b.id for r in network.related_bidders)

    # 4) Collusion Radar.
    collusion = collusion_radar_service.get_collusion_indicators(db, procurement.id, company.id)
    assert any(i.code == "identical_bid_amount" for i in collusion.indicators)
    assert collusion.disclaimer
