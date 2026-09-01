"""
Regression coverage for SIH26100 Phase 4 -- bidder document upload, AI
extraction, deterministic document classification, PAN-anchored identity
resolution helpers, and the extracted-facts -> existing verification
pipeline integration.

Storage: same monkeypatch-STORAGE_ROOT-to-tmp_path convention as
test_tender_multi_document.py / test_storage_backend.py -- real bytes
written to a real temp directory, no mocked filesystem.

LLM: document_parser.extract_text() is monkeypatched to return fixed text
directly (both the module-level binding in sih_document_extractor and the
local import in document_service's classification path -- see the
_patch_parsed_text() helper below), so tests never need to construct real
parseable PDFs. get_llm_client() is monkeypatched with a tiny fake client
that returns a scripted JSON string, the same style already used for
decision_engine's LLM seam in test_capability_evaluation_loop.py.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import document_parser, sih_document_extractor
from app.agents.document_parser import ParsedDocument
from app.core import storage
from app.core.database import Base
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
from app.models.sih.enums import DocumentExtractionStatus
from app.services.exceptions import ConflictError, ExtractionError, NotFoundError, UnsupportedFileTypeError, FileTooLargeError
from app.services.sih import compliance_category_service, document_service, registry_seed_service, verification_service
from app.services.sih.identity_resolution import fuzzy_name_match, normalize_name, resolve_pan_identity


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


@pytest.fixture()
def seeded_registry(db):
    compliance_category_service.seed_default_categories(db)
    registry_seed_service.seed_mock_registry(db)


@pytest.fixture()
def submission(db, company):
    procurement = Procurement(company_id=company.id, title="Sample Procurement")
    db.add(procurement)
    db.flush()
    bidder = Bidder(company_id=company.id, legal_name="ABC Engineering Private Limited", pan="ABCDE1234F")
    db.add(bidder)
    db.flush()
    sub = BidderSubmission(procurement_id=procurement.id, bidder_id=bidder.id)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


class _FakeUploadFile:
    """Minimal stand-in for fastapi.UploadFile -- see
    test_tender_multi_document.py's identical helper; storage.save_upload()
    only ever calls .filename / .content_type / (async) .read()."""

    def __init__(self, filename: str, content: bytes, content_type: str):
        self.filename = filename
        self.content_type = content_type
        self._content = content
        self._sent = False

    async def read(self, _size: int = -1) -> bytes:
        if self._sent:
            return b""
        self._sent = True
        return self._content


class _FakeLLMClient:
    def __init__(self, response_text: str):
        self._response_text = response_text

    async def complete(self, system_prompt: str, user_prompt: str, purpose: str = "unspecified") -> str:
        return self._response_text


def _patch_parsed_text(monkeypatch, text: str, used_ocr: bool = False):
    """Both document_parser.extract_text (document_service's local-import
    classification path) and sih_document_extractor's own module-level
    binding must be patched -- a Python `from x import y` binds a name at
    import time, so patching x.y afterward doesn't retroactively affect an
    already-bound reference in a different module."""
    fake = lambda _path, _ext: ParsedDocument(text=text, used_ocr=used_ocr, ocr_confidence=None)
    monkeypatch.setattr(document_parser, "extract_text", fake)
    monkeypatch.setattr(sih_document_extractor, "extract_text", fake)


def _patch_llm_response(monkeypatch, response_text: str):
    monkeypatch.setattr(sih_document_extractor, "get_llm_client", lambda *_: _FakeLLMClient(response_text))


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_upload_valid_document_creates_pending_document(tmp_path, monkeypatch, db, company, officer, submission, seeded_registry):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    file = _FakeUploadFile("gst_certificate.pdf", b"fake pdf bytes", "application/pdf")
    document = asyncio.run(
        document_service.upload_bidder_document(db, submission.id, company.id, officer.id, file, "gst")
    )

    assert document.submission_id == submission.id
    assert document.category_code == "gst"
    assert document.category_source == "officer"
    assert document.extraction_status == DocumentExtractionStatus.PENDING
    assert document.file_name == "gst_certificate.pdf"
    # No local filesystem path exposed anywhere the frontend can see --
    # storage_path is a real DB column but never part of any Read schema
    # (see app/schemas/sih.py's BidderDocumentRead, which omits it).
    assert document.storage_path


def test_upload_invalid_file_type_rejected(tmp_path, monkeypatch, db, company, officer, submission):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    file = _FakeUploadFile("malware.exe", b"MZ\x90\x00", "application/x-msdownload")
    with pytest.raises(UnsupportedFileTypeError):
        asyncio.run(document_service.upload_bidder_document(db, submission.id, company.id, officer.id, file, "gst"))


def test_upload_oversized_file_rejected(tmp_path, monkeypatch, db, company, officer, submission):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)
    # 0MB max -- any non-empty upload exceeds it, without needing to
    # actually construct a multi-megabyte file in the test.
    monkeypatch.setattr(storage.settings, "max_upload_size_mb", 0)

    file = _FakeUploadFile("gst.pdf", b"not tiny enough", "application/pdf")
    with pytest.raises(FileTooLargeError):
        asyncio.run(document_service.upload_bidder_document(db, submission.id, company.id, officer.id, file, "gst"))


# ---------------------------------------------------------------------------
# Manual evidence attachment (POST .../verify's optional attachment)
# ---------------------------------------------------------------------------


def test_attach_manual_evidence_creates_confirmed_document(
    tmp_path, monkeypatch, db, company, officer, submission, seeded_registry
):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    file = _FakeUploadFile("gst_certificate.pdf", b"fake pdf bytes", "application/pdf")
    declared = {"gstin": "07ABCDE1234F1Z5"}
    document = asyncio.run(
        document_service.attach_manual_evidence(db, submission.id, company.id, officer.id, "gst", declared, file)
    )

    assert document.category_code == "gst"
    assert document.category_source == "officer"
    assert document.is_confirmed is True
    assert document.confirmed_data == declared
    assert document.extracted_data == declared
    assert document.manually_corrected is False
    assert document.confirmed_by == officer.id


def test_attach_manual_evidence_unknown_category_raises_not_found(
    tmp_path, monkeypatch, db, company, officer, submission, seeded_registry
):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    file = _FakeUploadFile("cert.pdf", b"fake pdf bytes", "application/pdf")
    with pytest.raises(NotFoundError):
        asyncio.run(
            document_service.attach_manual_evidence(
                db, submission.id, company.id, officer.id, "not_a_real_category", {}, file
            )
        )


def test_verify_submission_with_manual_evidence_populates_source_document_id(
    tmp_path, monkeypatch, db, company, officer, submission, seeded_registry
):
    """
    End-to-end of Task 1's actual goal: a manually declared category with
    an attached document ends up with source_document_id populated on its
    VerificationResult -- the one asymmetry this feature closes (manual
    declarations previously always left source_document_id NULL) -- and
    the Grounding Guard now classifies it as document_evidence, not
    manual_declaration.
    """
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    file = _FakeUploadFile("gst_certificate.pdf", b"fake pdf bytes", "application/pdf")
    declared_gst = {"gstin": "07ABCDE1234F1Z5"}
    document = asyncio.run(
        document_service.attach_manual_evidence(db, submission.id, company.id, officer.id, "gst", declared_gst, file)
    )

    results = verification_service.verify_submission(
        db,
        submission.id,
        {"pan": "ABCDE1234F", "legal_name": "ABC Engineering Private Limited"},
        {"gst": declared_gst, "blacklisting": {}},
        {"gst": document.id},
    )
    gst_result = next(r for r in results if r.category.code == "gst")
    assert gst_result.source_document_id == document.id
    assert gst_result.confidence == 1.0  # document-evidenced, per verification_service's confidence rule

    from app.services.sih import grounding_guard_service

    report = grounding_guard_service.get_grounding_report(db, submission.id)
    gst_grounding = next(c for c in report.categories if c.category_code == "gst")
    assert gst_grounding.origin == "document_evidence"


def test_upload_to_unowned_submission_raises_not_found(tmp_path, monkeypatch, db, officer, submission):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    other_company = Company(name="Other Co", registration_number=str(uuid.uuid4()))
    db.add(other_company)
    db.commit()

    file = _FakeUploadFile("gst.pdf", b"bytes", "application/pdf")
    with pytest.raises(NotFoundError):
        asyncio.run(
            document_service.upload_bidder_document(db, submission.id, other_company.id, officer.id, file, "gst")
        )


# ---------------------------------------------------------------------------
# Deterministic classification
# ---------------------------------------------------------------------------


def test_classify_document_detects_gst_from_keywords():
    category, confidence = sih_document_extractor.classify_document(
        "GST REGISTRATION CERTIFICATE\nGSTIN: 07ABCDE1234F1Z5\nGoods and Services Tax"
    )
    assert category == "gst"
    assert confidence > 0


def test_classify_document_detects_udyam_from_keywords():
    category, _confidence = sih_document_extractor.classify_document("UDYAM REGISTRATION CERTIFICATE\nUdyam Number: UDYAM-DL-01-0012345")
    assert category == "udyam"


def test_classify_document_returns_none_for_unrelated_text():
    category, confidence = sih_document_extractor.classify_document("This is a random cover letter with no relevant content.")
    assert category is None
    assert confidence == 0.0


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def test_extract_document_successful_populates_structured_data(tmp_path, monkeypatch, db, company, officer, submission, seeded_registry):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    file = _FakeUploadFile("gst.pdf", b"bytes", "application/pdf")
    document = asyncio.run(document_service.upload_bidder_document(db, submission.id, company.id, officer.id, file, "gst"))

    _patch_parsed_text(monkeypatch, "GSTIN 07ABCDE1234F1Z5 ABC Engineering Private Limited")
    _patch_llm_response(
        monkeypatch,
        '{"gstin": "07ABCDE1234F1Z5", "legal_name": "ABC Engineering Private Limited", '
        '"trade_name": null, "pan": "ABCDE1234F", "status": "active", "filing_status": null}',
    )

    updated = asyncio.run(document_service.extract_document(db, submission.id, document.id, company.id))

    assert updated.extraction_status == DocumentExtractionStatus.EXTRACTED
    assert updated.extracted_data["gstin"] == "07ABCDE1234F1Z5"
    assert updated.extraction_confidence is not None
    assert updated.extraction_error is None


def test_extract_document_malformed_llm_output_marks_failed(tmp_path, monkeypatch, db, company, officer, submission, seeded_registry):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    file = _FakeUploadFile("gst.pdf", b"bytes", "application/pdf")
    document = asyncio.run(document_service.upload_bidder_document(db, submission.id, company.id, officer.id, file, "gst"))

    _patch_parsed_text(monkeypatch, "some gst text")
    _patch_llm_response(monkeypatch, "this is not JSON at all")

    with pytest.raises(ExtractionError):
        asyncio.run(document_service.extract_document(db, submission.id, document.id, company.id))

    db.refresh(document)
    assert document.extraction_status == DocumentExtractionStatus.FAILED
    assert document.extraction_error is not None
    # Never treated as VERIFIED / silently accepted -- stays unresolved.
    assert document.extracted_data is None


def test_extract_document_empty_extraction_marks_failed(tmp_path, monkeypatch, db, company, officer, submission, seeded_registry):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    file = _FakeUploadFile("gst.pdf", b"bytes", "application/pdf")
    document = asyncio.run(document_service.upload_bidder_document(db, submission.id, company.id, officer.id, file, "gst"))

    _patch_parsed_text(monkeypatch, "illegible scan")
    _patch_llm_response(monkeypatch, '{"gstin": null, "legal_name": null, "trade_name": null, "pan": null, "status": null, "filing_status": null}')

    with pytest.raises(ExtractionError):
        asyncio.run(document_service.extract_document(db, submission.id, document.id, company.id))

    db.refresh(document)
    assert document.extraction_status == DocumentExtractionStatus.FAILED


def test_extract_document_without_category_and_unclassifiable_text_review_required(
    tmp_path, monkeypatch, db, company, officer, submission
):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    file = _FakeUploadFile("mystery.pdf", b"bytes", "application/pdf")
    document = asyncio.run(
        document_service.upload_bidder_document(db, submission.id, company.id, officer.id, file, None)
    )
    assert document.category_source == "unclassified"

    _patch_parsed_text(monkeypatch, "Dear Sir, please find attached our company profile.")
    # No LLM patch needed -- classification should short-circuit before
    # any LLM call is attempted.

    updated = asyncio.run(document_service.extract_document(db, submission.id, document.id, company.id))
    assert updated.extraction_status == DocumentExtractionStatus.REVIEW_REQUIRED
    assert updated.category_code is None
    assert "category" in updated.extraction_error.lower()


def test_extract_document_without_category_auto_classifies_and_extracts(
    tmp_path, monkeypatch, db, company, officer, submission
):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)

    file = _FakeUploadFile("cert.pdf", b"bytes", "application/pdf")
    document = asyncio.run(
        document_service.upload_bidder_document(db, submission.id, company.id, officer.id, file, None)
    )

    _patch_parsed_text(monkeypatch, "UDYAM REGISTRATION CERTIFICATE\nUdyam Number: UDYAM-DL-01-0012345\nEntity: ABC Engineering Private Limited")
    _patch_llm_response(
        monkeypatch,
        '{"udyam_number": "UDYAM-DL-01-0012345", "entity_name": "ABC Engineering Private Limited", '
        '"pan": null, "address": null, "status": "active", "enterprise_type": "small"}',
    )

    updated = asyncio.run(document_service.extract_document(db, submission.id, document.id, company.id))
    assert updated.category_code == "udyam"
    assert updated.category_source == "auto"
    assert updated.extraction_status == DocumentExtractionStatus.EXTRACTED


def test_set_document_category_officer_correction_resets_status(tmp_path, monkeypatch, db, company, officer, submission):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)
    compliance_category_service.seed_default_categories(db)

    file = _FakeUploadFile("doc.pdf", b"bytes", "application/pdf")
    document = asyncio.run(
        document_service.upload_bidder_document(db, submission.id, company.id, officer.id, file, None)
    )
    updated = document_service.set_document_category(db, submission.id, document.id, company.id, "epfo_esic")
    assert updated.category_code == "epfo_esic"
    assert updated.category_source == "officer"
    assert updated.extraction_status == DocumentExtractionStatus.PENDING


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------


def test_normalize_name_strips_legal_suffixes_and_punctuation():
    assert normalize_name("ABC Engineering Pvt. Ltd.") == normalize_name("ABC ENGINEERING PRIVATE LIMITED")


def test_fuzzy_name_match_high_for_near_identical_names():
    score = fuzzy_name_match("ABC Engineering Private Limited", "ABC Engineering Pvt Ltd")
    assert score > 0.9


def test_fuzzy_name_match_low_for_different_names():
    score = fuzzy_name_match("ABC Engineering Private Limited", "Sunrise Traders Private Limited")
    assert score < 0.6


def test_fuzzy_name_match_zero_when_either_name_missing():
    assert fuzzy_name_match(None, "ABC Engineering") == 0.0
    assert fuzzy_name_match("ABC Engineering", "") == 0.0


def test_resolve_pan_identity_match():
    assert resolve_pan_identity("ABCDE1234F", "ABCDE1234F") == "match"


def test_resolve_pan_identity_mismatch():
    assert resolve_pan_identity("ABCDE1234F", "XYZAB9876Z") == "mismatch"


def test_resolve_pan_identity_unavailable_when_either_missing():
    assert resolve_pan_identity(None, "ABCDE1234F") == "unavailable"
    assert resolve_pan_identity("ABCDE1234F", None) == "unavailable"


# ---------------------------------------------------------------------------
# Verification integration -- extracted documents feed the SAME
# verification_service.verify_submission() Phase 2 already uses.
# ---------------------------------------------------------------------------


def _upload_and_extract(db, company, officer, submission, monkeypatch, tmp_path, category_code, text, llm_json):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)
    file = _FakeUploadFile(f"{category_code}.pdf", b"bytes", "application/pdf")
    document = asyncio.run(
        document_service.upload_bidder_document(db, submission.id, company.id, officer.id, file, category_code)
    )
    _patch_parsed_text(monkeypatch, text)
    _patch_llm_response(monkeypatch, llm_json)
    return asyncio.run(document_service.extract_document(db, submission.id, document.id, company.id))


def _upload_extract_confirm(
    db, company, officer, submission, monkeypatch, tmp_path, category_code, text, llm_json, corrected_fields=None
):
    """Full Phase 5 pipeline up to (and including) officer confirmation --
    the state a document must be in before it can feed verification. See
    document_service.confirm_document()'s docstring for why mere
    extraction is never enough."""
    document = _upload_and_extract(db, company, officer, submission, monkeypatch, tmp_path, category_code, text, llm_json)
    return document_service.confirm_document(db, submission.id, document.id, company.id, officer.id, corrected_fields)


def test_build_declared_facts_aggregates_latest_confirmed_documents(
    tmp_path, monkeypatch, db, company, officer, submission, seeded_registry
):
    _upload_extract_confirm(
        db, company, officer, submission, monkeypatch, tmp_path, "gst",
        "GSTIN 07ABCDE1234F1Z5",
        '{"gstin": "07ABCDE1234F1Z5", "legal_name": "ABC Engineering Private Limited", "trade_name": null, "pan": "ABCDE1234F", "status": "active", "filing_status": null}',
    )
    declared = document_service.build_declared_facts_from_documents(db, submission.id)
    assert declared["gst"] == {"gstin": "07ABCDE1234F1Z5"}
    # blacklisting is always present even though never uploaded/extracted.
    assert declared["blacklisting"] == {}


def test_verify_from_confirmed_documents_clean_bidder_scenario_a(
    tmp_path, monkeypatch, db, company, officer, submission, seeded_registry
):
    _upload_extract_confirm(
        db, company, officer, submission, monkeypatch, tmp_path, "udyam",
        "UDYAM-DL-01-0012345 ABC Engineering Private Limited",
        '{"udyam_number": "UDYAM-DL-01-0012345", "entity_name": "ABC Engineering Private Limited", "pan": null, "address": null, "status": "active", "enterprise_type": "small"}',
    )
    _upload_extract_confirm(
        db, company, officer, submission, monkeypatch, tmp_path, "gst",
        "GSTIN 07ABCDE1234F1Z5",
        '{"gstin": "07ABCDE1234F1Z5", "legal_name": "ABC Engineering Private Limited", "trade_name": null, "pan": "ABCDE1234F", "status": "active", "filing_status": null}',
    )
    # "epfo" (not the deactivated combined "epfo_esic") -- extracts via
    # the shared IdentifierStatusExtraction schema, hence the generic
    # "identifier" field name rather than "establishment_id".
    _upload_extract_confirm(
        db, company, officer, submission, monkeypatch, tmp_path, "epfo",
        "Establishment DL/EPFO/998877",
        '{"identifier": "DL/EPFO/998877", "entity_name": "ABC Engineering Private Limited", "status": "active"}',
    )

    declared_facts, source_documents = document_service.build_verification_inputs_from_documents(db, submission.id)
    bidder = submission.bidder
    results = verification_service.verify_submission(
        db, submission.id, {"pan": bidder.pan, "legal_name": bidder.legal_name}, declared_facts, source_documents
    )
    by_code = {r.category.code: r for r in results}
    assert by_code["udyam"].status.value == "verified"
    assert by_code["gst"].status.value == "verified"
    assert by_code["epfo"].status.value == "verified"
    assert by_code["blacklisting"].status.value == "verified"
    # pan_itr was never uploaded -- honestly MISSING, never fabricated.
    assert by_code["pan_itr"].status.value == "missing"
    # Evidence linking: each document-derived result traces back to the
    # confirmed document that produced it; blacklisting never has one.
    assert by_code["gst"].source_document_id == source_documents["gst"]
    assert by_code["blacklisting"].source_document_id is None


def test_verify_from_confirmed_documents_gst_pan_mismatch_is_critical(
    tmp_path, monkeypatch, db, company, officer, submission, seeded_registry
):
    # The submission's bidder has PAN ABCDE1234F (clean), but the
    # extracted GST document's GSTIN belongs to the seeded fraud record
    # (registered to a different PAN in mock_registry_data.py).
    _upload_extract_confirm(
        db, company, officer, submission, monkeypatch, tmp_path, "gst",
        "GSTIN 09FRAUD9999K1Z1",
        '{"gstin": "09FRAUD9999K1Z1", "legal_name": "Genuine Constructions Ltd", "trade_name": null, "pan": null, "status": "active", "filing_status": null}',
    )
    declared_facts = document_service.build_declared_facts_from_documents(db, submission.id)
    bidder = submission.bidder
    results = verification_service.verify_submission(
        db, submission.id, {"pan": bidder.pan, "legal_name": bidder.legal_name}, declared_facts
    )
    by_code = {r.category.code: r for r in results}
    assert by_code["gst"].status.value == "critical_fail"


# ---------------------------------------------------------------------------
# Officer confirmation / correction gate (Phase 5) -- the core requirement
# that AI extraction alone never becomes authoritative verification input.
# ---------------------------------------------------------------------------


def test_confirm_requires_successful_extraction(tmp_path, monkeypatch, db, company, officer, submission, seeded_registry):
    monkeypatch.setattr(storage.settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)
    file = _FakeUploadFile("gst.pdf", b"bytes", "application/pdf")
    document = asyncio.run(
        document_service.upload_bidder_document(db, submission.id, company.id, officer.id, file, "gst")
    )
    # Still PENDING -- extraction was never run.
    with pytest.raises(ConflictError):
        document_service.confirm_document(db, submission.id, document.id, company.id, officer.id, None)


def test_confirm_as_is_matches_extracted_data(tmp_path, monkeypatch, db, company, officer, submission, seeded_registry):
    document = _upload_and_extract(
        db, company, officer, submission, monkeypatch, tmp_path, "gst",
        "GSTIN 07ABCDE1234F1Z5",
        '{"gstin": "07ABCDE1234F1Z5", "legal_name": "ABC Engineering Private Limited", "trade_name": null, "pan": "ABCDE1234F", "status": "active", "filing_status": null}',
    )
    confirmed = document_service.confirm_document(db, submission.id, document.id, company.id, officer.id, None)
    assert confirmed.is_confirmed is True
    assert confirmed.manually_corrected is False
    assert confirmed.confirmed_data == confirmed.extracted_data
    assert confirmed.confirmed_by == officer.id
    assert confirmed.confirmed_at is not None


def test_confirm_with_correction_marks_manually_corrected(
    tmp_path, monkeypatch, db, company, officer, submission, seeded_registry
):
    document = _upload_and_extract(
        db, company, officer, submission, monkeypatch, tmp_path, "gst",
        "GSTIN 07ABCDE1234F1Z5",
        '{"gstin": "07ABCDE1234F1Z5", "legal_name": "ABC Engineering Private Limited", "trade_name": null, "pan": "ABCDE1234F", "status": "active", "filing_status": null}',
    )
    # Officer notices the AI misread the GSTIN and corrects it.
    confirmed = document_service.confirm_document(
        db, submission.id, document.id, company.id, officer.id, {"gstin": "07ABCDE1234F1Z9"}
    )
    assert confirmed.manually_corrected is True
    assert confirmed.confirmed_data["gstin"] == "07ABCDE1234F1Z9"
    # The AI's original output is preserved untouched as an audit trail.
    assert confirmed.extracted_data["gstin"] == "07ABCDE1234F1Z5"


def test_confirm_rejects_structurally_invalid_correction(
    tmp_path, monkeypatch, db, company, officer, submission, seeded_registry
):
    document = _upload_and_extract(
        db, company, officer, submission, monkeypatch, tmp_path, "pan_itr",
        "PAN ABCDE1234F ITR 2023-24",
        '{"pan": "ABCDE1234F", "legal_name": "ABC Engineering Private Limited", "assessment_year": "2023-24", "itr_years_claimed": ["2023-24"], "gross_total_income": null}',
    )
    # itr_years_claimed must be a list, not a bare string -- an officer
    # correction is held to the same structural bar as an AI extraction.
    with pytest.raises(ExtractionError):
        document_service.confirm_document(
            db, submission.id, document.id, company.id, officer.id, {"itr_years_claimed": "not-a-list"}
        )


def test_category_correction_resets_confirmation(tmp_path, monkeypatch, db, company, officer, submission, seeded_registry):
    document = _upload_and_extract(
        db, company, officer, submission, monkeypatch, tmp_path, "gst",
        "GSTIN 07ABCDE1234F1Z5",
        '{"gstin": "07ABCDE1234F1Z5", "legal_name": "ABC Engineering Private Limited", "trade_name": null, "pan": "ABCDE1234F", "status": "active", "filing_status": null}',
    )
    confirmed = document_service.confirm_document(db, submission.id, document.id, company.id, officer.id, None)
    assert confirmed.is_confirmed is True

    corrected_category = document_service.set_document_category(db, submission.id, document.id, company.id, "epfo_esic")
    assert corrected_category.is_confirmed is False
    assert corrected_category.confirmed_data is None


def test_unconfirmed_extraction_is_not_authoritative_verification_input(
    tmp_path, monkeypatch, db, company, officer, submission, seeded_registry
):
    """The central Phase 5 invariant: a document that has been AI-extracted
    but NOT officer-confirmed must never silently feed verification."""
    _upload_and_extract(
        db, company, officer, submission, monkeypatch, tmp_path, "udyam",
        "UDYAM-DL-01-0012345 ABC Engineering Private Limited",
        '{"udyam_number": "UDYAM-DL-01-0012345", "entity_name": "ABC Engineering Private Limited", "pan": null, "address": null, "status": "active", "enterprise_type": "small"}',
    )
    declared_facts, source_documents = document_service.build_verification_inputs_from_documents(db, submission.id)
    assert "udyam" not in declared_facts
    assert "udyam" not in source_documents

    bidder = submission.bidder
    results = verification_service.verify_submission(
        db, submission.id, {"pan": bidder.pan, "legal_name": bidder.legal_name}, declared_facts, source_documents
    )
    by_code = {r.category.code: r for r in results}
    # Never fabricated as VERIFIED just because a document exists --
    # honestly recorded as MISSING, the same as if nothing were uploaded.
    assert by_code["udyam"].status.value == "missing"


def test_verify_from_extracted_documents_blacklisted_bidder_is_critical(
    tmp_path, monkeypatch, db, company, seeded_registry
):
    procurement = Procurement(company_id=company.id, title="Sample Procurement")
    db.add(procurement)
    db.flush()
    officer = User(
        company_id=company.id, name="Officer", email=f"o-{uuid.uuid4()}@example.com",
        password_hash="x", role=UserRole.ADMINISTRATOR, status=UserStatus.ACTIVE,
    )
    db.add(officer)
    bidder = Bidder(company_id=company.id, legal_name="Debarred Contractor Pvt Ltd", pan="DEBAR1234B")
    db.add(bidder)
    db.flush()
    sub = BidderSubmission(procurement_id=procurement.id, bidder_id=bidder.id)
    db.add(sub)
    db.commit()
    db.refresh(sub)

    # No documents uploaded at all -- blacklisting is still checked (pure
    # PAN/registry lookup) via build_declared_facts_from_documents' always-
    # present {} entry.
    declared_facts = document_service.build_declared_facts_from_documents(db, sub.id)
    results = verification_service.verify_submission(
        db, sub.id, {"pan": bidder.pan, "legal_name": bidder.legal_name}, declared_facts
    )
    by_code = {r.category.code: r for r in results}
    assert by_code["blacklisting"].status.value == "critical_fail"
