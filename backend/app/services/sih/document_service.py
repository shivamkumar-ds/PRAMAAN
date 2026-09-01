"""
BidderDocument CRUD + extraction orchestration -- SIH26100 Phase 4.

Mirrors app/services/document_service.py (upload/storage) and
app/services/capability_service.build_capability_from_document()
(extraction status lifecycle) as closely as the two domains' shapes
allow. Reuses app.core.storage unchanged -- no second file-storage
abstraction -- and app.agents.sih_document_extractor (which itself
reuses app.agents.llm_client / document_parser / json_utils unchanged)
-- no second LLM integration, no second verification engine.

Ownership: every function here takes a company_id and resolves it through
submission_service.get_owned_submission() first, exactly like every other
Phase 2 submission-scoped service -- a BidderDocument is never reachable
except through a submission this caller's company actually owns.
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pydantic
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.agents import sih_document_extractor
from app.core import storage
from app.models.sih.compliance import ComplianceCategory, VerificationResult
from app.models.sih.document import AuthenticityScan, BidderDocument
from app.models.sih.enums import DocumentExtractionStatus
from app.schemas.sih_extraction import CATEGORY_EXTRACTION_SCHEMAS
from app.services.exceptions import ConflictError, ExtractionError, NotFoundError
from app.services.sih import submission_service
from app.services.sih.grounding_guard_service import ensure_document_is_grounded

logger = logging.getLogger(__name__)

# Maps each category's validated extraction fields onto exactly the keys
# the corresponding Phase 1 adapter reads from declared_facts (see
# app/services/sih/registry_adapters.py) -- deliberately narrow, so an
# extraction that also picked up e.g. "status" or "address" never leaks
# into declared_facts and silently changes verification behavior beyond
# what the adapter actually inspects.
_DECLARED_FACTS_MAPPERS = {
    "udyam": lambda fields: {
        k: v for k, v in {"udyam_number": fields.get("udyam_number"), "entity_name": fields.get("entity_name")}.items() if v
    },
    "gst": lambda fields: {k: v for k, v in {"gstin": fields.get("gstin")}.items() if v},
    "pan_itr": lambda fields: (
        {"itr_years_claimed": fields["itr_years_claimed"]} if fields.get("itr_years_claimed") else {}
    ),
    "epfo_esic": lambda fields: {
        k: v for k, v in {"establishment_id": fields.get("establishment_id")}.items() if v
    },
    # blacklisting is always included, always empty -- see
    # sih_extraction.BlacklistingExtraction's docstring: nothing extracted
    # from a document ever feeds the blacklisting check, which stays a
    # pure PAN/registry lookup.
    "blacklisting": lambda _fields: {},
    # --- SIH26100 demo-scope expansion ---
    # mca21/epfo/esic/nsic/startup_india all extract via the shared
    # IdentifierStatusExtraction schema (generic "identifier" field-name);
    # each mapper here renames it to whatever key that category's adapter
    # actually reads from declared_facts (registry_adapters.py).
    "mca21": lambda fields: ({"cin": fields["identifier"]} if fields.get("identifier") else {}),
    "epfo": lambda fields: (
        {"establishment_id": fields["identifier"], **({"legal_name": fields["entity_name"]} if fields.get("entity_name") else {})}
        if fields.get("identifier")
        else {}
    ),
    "esic": lambda fields: (
        {"establishment_id": fields["identifier"], **({"legal_name": fields["entity_name"]} if fields.get("entity_name") else {})}
        if fields.get("identifier")
        else {}
    ),
    "nsic": lambda fields: (
        {"nsic_registration_number": fields["identifier"]} if fields.get("identifier") else {}
    ),
    "startup_india": lambda fields: (
        {"dpiit_number": fields["identifier"]} if fields.get("identifier") else {}
    ),
    "oem_authorization": lambda fields: (
        {
            "authorization_number": fields["authorization_number"],
            **({"bidder_name": fields["authorized_bidder_name"]} if fields.get("authorized_bidder_name") else {}),
        }
        if fields.get("authorization_number")
        else {}
    ),
    "digilocker": lambda fields: (
        {"digilocker_reference": fields["digilocker_reference"]} if fields.get("digilocker_reference") else {}
    ),
    "make_in_india": lambda fields: (
        {"local_content_percentage": fields["declared_local_content_percentage"]}
        if fields.get("declared_local_content_percentage") is not None
        else {}
    ),
}


async def upload_bidder_document(
    db: Session,
    submission_id: uuid.UUID,
    company_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    file: UploadFile,
    category_code: str | None,
) -> BidderDocument:
    submission_service.get_owned_submission(db, submission_id, company_id)

    storage.validate_file_type(file.filename, file.content_type)
    # Same {company_id}/documents/{uuid}.{ext} layout as
    # app.services.document_service.upload_document -- a bidder document
    # is still ultimately owned by the officer's own company (the tenant
    # running verification), not the bidder, so it lives in that
    # company's own storage namespace, isolated from every other tenant's
    # files exactly like every other upload in this codebase.
    relative_path, _unique_filename, _size = await storage.save_upload(company_id, file)

    category_source = "officer" if category_code else "unclassified"
    if category_code:
        category = db.query(ComplianceCategory).filter(ComplianceCategory.code == category_code).one_or_none()
        if category is None:
            storage.delete_file(relative_path)
            raise NotFoundError(f"Compliance category '{category_code}' not found.")

    document = BidderDocument(
        submission_id=submission_id,
        uploaded_by=uploaded_by,
        category_code=category_code,
        category_source=category_source,
        file_name=file.filename or "unnamed",
        storage_path=relative_path,
        extraction_status=DocumentExtractionStatus.PENDING,
    )
    db.add(document)
    try:
        db.commit()
    except Exception:
        logger.exception("Bidder document upload failed, rolling back: submission_id=%s", submission_id)
        db.rollback()
        storage.delete_file(relative_path)
        raise
    db.refresh(document)
    return document


async def attach_manual_evidence(
    db: Session,
    submission_id: uuid.UUID,
    company_id: uuid.UUID,
    officer_id: uuid.UUID,
    category_code: str,
    declared_fields: dict,
    file: UploadFile,
) -> BidderDocument:
    """
    Stores a supporting document an officer attaches directly to a manual
    declared-facts entry (POST .../verify's optional attachment -- see
    app/api/v1/sih.py) -- e.g. a scanned certificate the officer typed the
    declared facts in from. Deliberately NOT routed through
    extract_document()/confirm_document(): there is no AI extraction step
    to run or confirm here, the officer already typed the facts they're
    declaring, so is_confirmed is set True immediately and confirmed_data
    is exactly declared_fields, never merged/re-derived from anything the
    file itself might contain. extracted_data mirrors confirmed_data
    (rather than staying empty) so the audit trail still shows what was
    on file at confirmation time, consistent with every other
    BidderDocument row -- manually_corrected stays False, since nothing
    here was corrected against a prior AI output; there never was one.

    category_code is required and must be one of the categories present
    in this same verify request's declared_facts -- the caller
    (app/api/v1/sih.py::verify_submission) enforces that before calling
    this function, so this attaches evidence for the exact category it's
    evidencing, never left ambiguous.
    """
    submission_service.get_owned_submission(db, submission_id, company_id)
    category = db.query(ComplianceCategory).filter(ComplianceCategory.code == category_code).one_or_none()
    if category is None:
        raise NotFoundError(f"Compliance category '{category_code}' not found.")

    storage.validate_file_type(file.filename, file.content_type)
    relative_path, _unique_filename, _size = await storage.save_upload(company_id, file)

    now = datetime.now(timezone.utc)
    document = BidderDocument(
        submission_id=submission_id,
        uploaded_by=officer_id,
        category_code=category_code,
        category_source="officer",
        file_name=file.filename or "unnamed",
        storage_path=relative_path,
        extraction_status=DocumentExtractionStatus.EXTRACTED,
        extracted_data=declared_fields,
        extraction_confidence=None,
        extracted_at=now,
        is_confirmed=True,
        confirmed_data=declared_fields,
        confirmed_at=now,
        confirmed_by=officer_id,
        manually_corrected=False,
    )
    db.add(document)
    try:
        db.commit()
    except Exception:
        logger.exception(
            "Manual-evidence attachment upload failed, rolling back: submission_id=%s category_code=%s",
            submission_id,
            category_code,
        )
        db.rollback()
        storage.delete_file(relative_path)
        raise
    db.refresh(document)
    return document


def get_owned_document(db: Session, submission_id: uuid.UUID, document_id: uuid.UUID, company_id: uuid.UUID) -> BidderDocument:
    submission_service.get_owned_submission(db, submission_id, company_id)
    document = (
        db.query(BidderDocument)
        .filter(BidderDocument.id == document_id, BidderDocument.submission_id == submission_id)
        .one_or_none()
    )
    if document is None:
        raise NotFoundError(f"BidderDocument '{document_id}' not found.")
    return document


def list_bidder_documents(db: Session, submission_id: uuid.UUID, company_id: uuid.UUID) -> list[BidderDocument]:
    submission_service.get_owned_submission(db, submission_id, company_id)
    return (
        db.query(BidderDocument)
        .filter(BidderDocument.submission_id == submission_id)
        .order_by(BidderDocument.uploaded_at.desc())
        .all()
    )


def delete_bidder_document(db: Session, submission_id: uuid.UUID, document_id: uuid.UUID, company_id: uuid.UUID) -> None:
    """
    Hard-deletes a wrongly-uploaded BidderDocument -- unlike the general
    app.services.document_service.delete_document (soft-delete, since a
    Document can be a Tender's/capability's source_document_id an audit
    trail must keep resolving), a BidderDocument has no such long-lived
    downstream reference UNTIL it's actually been used as verification
    evidence (VerificationResult.source_document_id, Phase 5). So:

    - Never yet run through .../verify (no VerificationResult points at
      it): safe to actually remove, row and file both -- there's nothing
      to preserve provenance for. This is the common case this feature
      exists for: "wrong file, re-upload the right one," not a
      post-decision audit correction.
    - Already the source_document_id on a recorded VerificationResult:
      blocked (ConflictError) exactly like Document.delete_document's own
      Tender/capability guards -- deleting it would either violate the FK
      (sih_verification_results.source_document_id has no ON DELETE
      clause -- see migration d1e2f3a4b5c6) or, if it didn't, silently
      break "why this result?" provenance for a decision that may already
      be officer-approved. The officer re-verifies (which produces a new
      VerificationResult row and clears this document as the *latest*
      evidence) before this document can be removed.
    """
    document = get_owned_document(db, submission_id, document_id, company_id)
    still_referenced = (
        db.query(VerificationResult.id).filter(VerificationResult.source_document_id == document_id).first()
    )
    if still_referenced is not None:
        raise ConflictError(
            "This document is the recorded evidence source for an existing verification result and can't be "
            "deleted. Re-run verification for this category first, then delete it."
        )
    # Same guard, extended to AuthenticityScan (Phase 2, added after this
    # delete path already existed): sih_authenticity_scans.document_id has
    # no ON DELETE clause either (insert-only scan history, same
    # provenance-preservation intent as VerificationResult above), so a
    # document that has ever been authenticity-scanned would otherwise hit
    # a raw IntegrityError instead of this same explainable ConflictError.
    has_authenticity_scans = (
        db.query(AuthenticityScan.id).filter(AuthenticityScan.document_id == document_id).first()
    )
    if has_authenticity_scans is not None:
        raise ConflictError(
            "This document has recorded authenticity-scan history and can't be deleted -- that would erase "
            "part of the audit trail. Re-upload as a new document instead."
        )

    relative_path = document.storage_path
    db.delete(document)
    db.commit()
    storage.delete_file(relative_path)


def set_document_category(
    db: Session, submission_id: uuid.UUID, document_id: uuid.UUID, company_id: uuid.UUID, category_code: str
) -> BidderDocument:
    """Officer correction path (Phase 4 brief section 10/8): lets an
    officer assign or fix a document's category before/after extraction.
    Resets extraction_status back to PENDING so a stale extraction run
    under the wrong category is never presented as current. Also resets
    any confirmation (Phase 5) -- a confirmation made under the old,
    wrong category can never remain authoritative once the category
    itself changes."""
    document = get_owned_document(db, submission_id, document_id, company_id)
    category = db.query(ComplianceCategory).filter(ComplianceCategory.code == category_code).one_or_none()
    if category is None:
        raise NotFoundError(f"Compliance category '{category_code}' not found.")
    document.category_code = category_code
    document.category_source = "officer"
    document.extraction_status = DocumentExtractionStatus.PENDING
    document.extracted_data = None
    document.extraction_error = None
    _reset_confirmation(document)
    db.commit()
    db.refresh(document)
    return document


def _reset_confirmation(document: BidderDocument) -> None:
    """Clears any prior officer confirmation -- called whenever the
    underlying extracted data could change (category correction,
    re-extraction), so a stale confirmation can never be mistaken for
    sign-off on the current data."""
    document.is_confirmed = False
    document.confirmed_data = None
    document.confirmed_at = None
    document.confirmed_by = None
    document.manually_corrected = False


async def extract_document(
    db: Session, submission_id: uuid.UUID, document_id: uuid.UUID, company_id: uuid.UUID
) -> BidderDocument:
    document = get_owned_document(db, submission_id, document_id, company_id)
    extension = Path(document.storage_path).suffix.lower()
    # A document can be (re-)extracted after having been confirmed --
    # e.g. a retry, or an officer deliberately re-running extraction. The
    # prior confirmation covered the OLD extracted_data; it must never be
    # left standing over new, unreviewed output.
    _reset_confirmation(document)

    if document.category_code is None:
        # Attempt classification first -- see
        # sih_document_extractor.classify_document()'s docstring for why
        # this is a deterministic keyword heuristic, not an LLM call.
        with storage.local_file_for_read(document.storage_path) as file_path:
            from app.agents.document_parser import extract_text

            parsed = extract_text(file_path, extension)
        category_code, _confidence = sih_document_extractor.classify_document(parsed.text)
        if category_code is None:
            document.extraction_status = DocumentExtractionStatus.REVIEW_REQUIRED
            document.extraction_error = (
                "Could not confidently determine this document's compliance category. "
                "An officer must assign one manually before extraction can run."
            )
            db.commit()
            db.refresh(document)
            return document
        document.category_code = category_code
        document.category_source = "auto"
        db.commit()

    document.extraction_status = DocumentExtractionStatus.PROCESSING
    db.commit()

    try:
        with storage.local_file_for_read(document.storage_path) as file_path:
            result = await sih_document_extractor.extract_bidder_document(file_path, extension, document.category_code)
    except Exception as exc:
        logger.exception(
            "SIH document extraction failed: document_id=%s category_code=%s", document_id, document.category_code
        )
        document.extraction_status = DocumentExtractionStatus.FAILED
        document.extraction_error = str(exc)
        document.extracted_at = datetime.now(timezone.utc)
        db.commit()
        raise ExtractionError(f"Extraction failed for document '{document_id}': {exc}") from exc

    document.extracted_data = result.fields
    document.extraction_confidence = result.confidence
    document.extraction_status = DocumentExtractionStatus.EXTRACTED
    document.extraction_error = None
    document.extracted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(document)
    return document


def confirm_document(
    db: Session,
    submission_id: uuid.UUID,
    document_id: uuid.UUID,
    company_id: uuid.UUID,
    confirmed_by: uuid.UUID,
    corrected_fields: dict | None,
) -> BidderDocument:
    """
    The Phase 5 gate: AI extraction alone never becomes authoritative
    verification input (see build_verification_inputs_from_documents) --
    an officer must explicitly confirm it first, optionally correcting
    any field along the way. Only EXTRACTED documents can be confirmed;
    PENDING/PROCESSING/REVIEW_REQUIRED/FAILED have no extracted_data to
    confirm.

    corrected_fields is merged over extracted_data and re-validated
    against the category's own extraction schema (same schema extraction
    itself used) -- an officer correction is held to the identical
    structural bar as an AI extraction, it just skips the LLM. The result
    becomes confirmed_data; extracted_data (the AI's original output) is
    left untouched as an audit trail. manually_corrected records whether
    the confirmed value actually differs from what the AI produced.
    """
    document = get_owned_document(db, submission_id, document_id, company_id)
    if document.extraction_status != DocumentExtractionStatus.EXTRACTED:
        raise ConflictError(
            f"Document '{document_id}' has not been successfully extracted "
            f"(status={document.extraction_status.value}) and cannot be confirmed yet."
        )

    schema = CATEGORY_EXTRACTION_SCHEMAS.get(document.category_code) if document.category_code else None
    merged = {**(document.extracted_data or {}), **(corrected_fields or {})}
    if schema is not None:
        try:
            validated = schema.model_validate(merged).model_dump()
        except pydantic.ValidationError as exc:
            raise ExtractionError(f"Corrected fields are invalid for category '{document.category_code}': {exc}") from exc
    else:
        validated = merged

    document.confirmed_data = validated
    document.manually_corrected = bool(corrected_fields) and validated != (document.extracted_data or {})
    document.is_confirmed = True
    document.confirmed_at = datetime.now(timezone.utc)
    document.confirmed_by = confirmed_by
    db.commit()
    db.refresh(document)
    return document


def build_verification_inputs_from_documents(
    db: Session, submission_id: uuid.UUID
) -> tuple[dict[str, dict], dict[str, uuid.UUID]]:
    """
    Aggregates the latest CONFIRMED (never merely EXTRACTED --
    see confirm_document's docstring) BidderDocument per category into
    exactly the declared_facts_by_category shape
    verification_service.verify_submission() already accepts, plus a
    parallel map of which document each category's facts came from, for
    evidence linking (VerificationResult.source_document_id). This is
    the ONLY place Phase 4/5 touch the verification pipeline;
    verify_submission itself is completely unmodified, per the Phase 4
    brief's explicit "Do NOT create a second verification engine."

    An EXTRACTED-but-unconfirmed document contributes nothing here --
    its category simply falls back to verify_submission's normal
    "nothing declared" handling (MISSING/NOT_CLAIMED), never silently
    treated as authoritative.

    blacklisting is always included (even with no document uploaded for
    it) -- identical to the Phase 3 frontend's automatic inclusion,
    documented in BidderVerification.tsx: it is a pure PAN/registry check,
    never dependent on a bidder-submitted document, so it never has a
    source_document_id either.
    """
    documents = (
        db.query(BidderDocument)
        .filter(
            BidderDocument.submission_id == submission_id,
            BidderDocument.is_confirmed.is_(True),
        )
        .order_by(BidderDocument.confirmed_at.desc())
        .all()
    )
    latest_by_category: dict[str, BidderDocument] = {}
    for doc in documents:
        if doc.category_code and doc.category_code not in latest_by_category:
            latest_by_category[doc.category_code] = doc

    declared: dict[str, dict] = {}
    source_documents: dict[str, uuid.UUID] = {}
    for category_code, doc in latest_by_category.items():
        mapper = _DECLARED_FACTS_MAPPERS.get(category_code)
        if mapper is None:
            continue
        # Evidence Grounding Guard (formalized invariant, see
        # grounding_guard_service.py's module docstring) -- defense in
        # depth on top of the is_confirmed.is_(True) filter above: this
        # loop must never reach a document whose data isn't grounded, and
        # this call turns "was that ever accidentally skipped?" into a
        # raised, test-covered error rather than a silent possibility.
        ensure_document_is_grounded(doc)
        declared[category_code] = mapper(doc.confirmed_data or {})
        source_documents[category_code] = doc.id
    declared.setdefault("blacklisting", {})
    return declared, source_documents


def build_declared_facts_from_documents(db: Session, submission_id: uuid.UUID) -> dict[str, dict]:
    """Backward-compatible wrapper over build_verification_inputs_from_documents
    for callers that only need declared_facts (e.g. existing tests) --
    see that function's docstring for the confirmation gate."""
    declared, _source_documents = build_verification_inputs_from_documents(db, submission_id)
    return declared
