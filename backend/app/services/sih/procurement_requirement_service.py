"""
Requirement-to-Evidence Mapping engine -- SIH26100.

Upload the officer's own tender/procurement document, extract its
discrete eligibility/compliance requirements (app/agents/
procurement_requirement_extractor.py, reusing the same
app.agents.llm_client provider abstraction every other SIH26100
extraction path uses -- no second LLM integration), and derive a
read-only, per-bidder-submission "does this bidder's verified evidence
actually cover this requirement?" view.

Ownership: every function here takes a company_id and resolves it
through procurement_service.get_procurement() first, mirroring every
other Phase 2+ SIH service's tenant-scoping discipline -- a
ProcurementDocument/ProcurementRequirement is never reachable except
through a Procurement this caller's company actually owns.

get_requirement_evidence_map() is deliberately read-only derived data,
never a new persisted verdict of its own -- consistent with this whole
package's "AI assembles evidence, officer decides" posture (see
grounding_guard_service.py's module docstring for the sibling pattern
this one is built to match): it re-reads verification_service's
already-persisted VerificationResult rows and category_hint's fixed
checklist mapping, and never writes anything.
"""

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.agents import procurement_requirement_extractor
from app.core import storage
from app.models.sih.compliance import VerificationResult
from app.models.sih.enums import ComplianceVerificationStatus, ProcurementDocumentExtractionStatus
from app.models.sih.procurement_document import ProcurementDocument
from app.models.sih.procurement_requirement import ProcurementRequirement
from app.services.exceptions import ExtractionError, NotFoundError
from app.services.sih import procurement_service, submission_service, verification_service

logger = logging.getLogger(__name__)

# Statuses that count as "the bidder actually cleared this category" for
# the purposes of a requirement-evidence match -- deliberately just
# VERIFIED (the only "this checked out" outcome in
# ComplianceVerificationStatus; see app/models/sih/enums.py). NOT_APPLICABLE
# is a real, distinct outcome (the adapter itself decided this bidder is
# exempt) and is treated as "matched" too -- the requirement is honestly
# covered, just not via a positive check.
_PASSING_STATUSES = {ComplianceVerificationStatus.VERIFIED, ComplianceVerificationStatus.NOT_APPLICABLE}
# Statuses that count as an active failure, distinct from simply missing.
_FAILING_STATUSES = {ComplianceVerificationStatus.MISMATCH, ComplianceVerificationStatus.CRITICAL_FAIL}


async def upload_and_extract(
    db: Session,
    procurement_id: uuid.UUID,
    company_id: uuid.UUID,
    file: UploadFile,
    uploaded_by: uuid.UUID | None,
) -> tuple[ProcurementDocument, list[ProcurementRequirement]]:
    """
    Stores the uploaded tender document (reusing app.core.storage exactly
    like BidderDocument's upload path), then runs extraction
    synchronously inline with the request -- a deliberate hackathon-scope
    simplification mirroring how BidderDocument extraction is triggered
    (a separate explicit call in that domain, but the same "no background
    job queue exists in this codebase" constraint applies here too; see
    document_service.extract_document). A failed extraction still leaves
    the document row in place (extraction_status=FAILED, extraction_error
    populated) rather than rolling back the upload -- the officer keeps
    the file and can see why extraction didn't produce requirements,
    exactly like BidderDocument's FAILED state.
    """
    procurement_service.get_procurement(db, procurement_id, company_id)

    storage.validate_file_type(file.filename, file.content_type)
    relative_path, _unique_filename, size = await storage.save_upload(company_id, file)

    document = ProcurementDocument(
        procurement_id=procurement_id,
        original_filename=file.filename or "unnamed",
        storage_path=relative_path,
        mime_type=file.content_type,
        file_size_bytes=size,
        uploaded_by=uploaded_by,
        extraction_status=ProcurementDocumentExtractionStatus.PENDING,
    )
    db.add(document)
    try:
        db.commit()
    except Exception:
        logger.exception("Procurement document upload failed, rolling back: procurement_id=%s", procurement_id)
        db.rollback()
        storage.delete_file(relative_path)
        raise
    db.refresh(document)

    extension = Path(document.storage_path).suffix.lower()
    try:
        with storage.local_file_for_read(document.storage_path) as file_path:
            result = await procurement_requirement_extractor.extract_procurement_requirements(file_path, extension)
    except Exception as exc:
        logger.exception(
            "Procurement requirement extraction failed: document_id=%s procurement_id=%s",
            document.id,
            procurement_id,
        )
        document.extraction_status = ProcurementDocumentExtractionStatus.FAILED
        document.extraction_error = str(exc)
        db.commit()
        db.refresh(document)
        # Extraction failing is a real, reportable outcome, not silently
        # swallowed -- same posture as document_service.extract_document's
        # ExtractionError re-raise. The document row itself is preserved
        # (see this function's own docstring).
        raise ExtractionError(f"Requirement extraction failed for document '{document.id}': {exc}") from exc

    created: list[ProcurementRequirement] = []
    for extracted in result.requirements:
        requirement = ProcurementRequirement(
            procurement_id=procurement_id,
            source_document_id=document.id,
            requirement_text=extracted.requirement_text,
            category_hint=extracted.category_hint,
            is_mandatory=extracted.is_mandatory,
        )
        db.add(requirement)
        created.append(requirement)

    document.extraction_status = ProcurementDocumentExtractionStatus.EXTRACTED
    document.extraction_error = None
    db.commit()
    db.refresh(document)
    for requirement in created:
        db.refresh(requirement)

    return document, created


def list_documents(db: Session, procurement_id: uuid.UUID, company_id: uuid.UUID) -> list[ProcurementDocument]:
    procurement_service.get_procurement(db, procurement_id, company_id)
    return (
        db.query(ProcurementDocument)
        .filter(ProcurementDocument.procurement_id == procurement_id)
        .order_by(ProcurementDocument.uploaded_at.desc())
        .all()
    )


def delete_document(db: Session, procurement_id: uuid.UUID, document_id: uuid.UUID, company_id: uuid.UUID) -> None:
    """
    Deletes an uploaded ProcurementDocument (row + stored file). Unlike
    BidderDocument's delete path (document_service.delete_bidder_document),
    a ProcurementDocument is never blocked by downstream references --
    see ProcurementRequirement.source_document_id's docstring: a
    requirement whose source document was deleted stands on its own,
    there is no FK ondelete cascade onto sih_procurement_requirements.
    So this bulk-nulls source_document_id on every requirement that
    still points at this document (the requirement rows themselves are
    never touched otherwise) before deleting the row, which both keeps
    the FK happy (no ondelete clause means the raw delete would
    otherwise hit a RESTRICT violation) and matches the model's own
    documented "requirements survive their source document" intent.
    """
    procurement_service.get_procurement(db, procurement_id, company_id)
    document = db.get(ProcurementDocument, document_id)
    if document is None or document.procurement_id != procurement_id:
        raise NotFoundError(f"ProcurementDocument '{document_id}' not found for procurement '{procurement_id}'.")

    db.query(ProcurementRequirement).filter(ProcurementRequirement.source_document_id == document_id).update(
        {ProcurementRequirement.source_document_id: None}
    )

    relative_path = document.storage_path
    db.delete(document)
    db.commit()
    storage.delete_file(relative_path)


def delete_requirement(
    db: Session, procurement_id: uuid.UUID, requirement_id: uuid.UUID, company_id: uuid.UUID
) -> None:
    """
    Deletes a single extracted ProcurementRequirement row -- e.g. an
    officer correcting an over-extraction (a duplicate, or text the LLM
    mis-split into two requirements). Unlike delete_document, this has
    no downstream references to clean up: nothing else FKs onto
    sih_procurement_requirements.id. get_requirement_evidence_map()
    simply won't see this requirement anymore, exactly as if it had
    never been extracted.
    """
    procurement_service.get_procurement(db, procurement_id, company_id)
    requirement = db.get(ProcurementRequirement, requirement_id)
    if requirement is None or requirement.procurement_id != procurement_id:
        raise NotFoundError(
            f"ProcurementRequirement '{requirement_id}' not found for procurement '{procurement_id}'."
        )
    db.delete(requirement)
    db.commit()


def list_requirements(db: Session, procurement_id: uuid.UUID, company_id: uuid.UUID) -> list[ProcurementRequirement]:
    procurement_service.get_procurement(db, procurement_id, company_id)
    return (
        db.query(ProcurementRequirement)
        .filter(ProcurementRequirement.procurement_id == procurement_id)
        .order_by(ProcurementRequirement.created_at.asc())
        .all()
    )


@dataclass
class RequirementEvidenceMapEntry:
    requirement_id: uuid.UUID
    requirement_text: str
    category_hint: str | None
    is_mandatory: bool
    # "matched" / "unmatched_failed" / "unmatched_missing" / "no_automated_check"
    status: str
    verification_status: ComplianceVerificationStatus | None
    source_verification_result_id: uuid.UUID | None
    source_document_id: uuid.UUID | None
    source_document_name: str | None


def get_requirement_evidence_map(
    db: Session, procurement_id: uuid.UUID, submission_id: uuid.UUID, company_id: uuid.UUID
) -> list[RequirementEvidenceMapEntry]:
    """
    For each ProcurementRequirement of this procurement, derives an
    honest status against the given bidder submission's latest
    verification results -- see this module's docstring for why this is
    read-only derived data, never a new persisted verdict.

    - category_hint is None -> "no_automated_check": the requirement was
      noted, but there is nothing in the fixed ComplianceCategory
      checklist to automatically compare it against (e.g. a minimum
      turnover requirement) -- an officer must review it manually. Never
      fabricated as a match.
    - category_hint maps to a category with a latest VerificationResult
      whose status is VERIFIED or NOT_APPLICABLE -> "matched", carrying
      which VerificationResult (and, if any, which confirmed
      BidderDocument backs it -- same evidence reference
      grounding_guard_service.get_grounding_report() already exposes)
      backs it.
    - ...MISMATCH or CRITICAL_FAIL -> "unmatched_failed".
    - ...MISSING or NOT_CLAIMED, or no result recorded for that category
      at all (e.g. the submission has never been verified) ->
      "unmatched_missing".
    """
    procurement_service.get_procurement(db, procurement_id, company_id)
    submission = submission_service.get_owned_submission(db, submission_id, company_id)
    if submission.procurement_id != procurement_id:
        # Same "don't leak cross-procurement existence" posture as every
        # other tenant/ownership check in this package -- a submission
        # that belongs to a different procurement than the one in the
        # URL is treated identically to submission_id simply not
        # matching, not surfaced as a more specific error.
        from app.services.exceptions import NotFoundError

        raise NotFoundError(f"BidderSubmission '{submission_id}' not found for procurement '{procurement_id}'.")

    requirements = list_requirements(db, procurement_id, company_id)
    latest_results = verification_service.get_latest_results(db, submission_id)
    results_by_category_code = {result.category.code: result for result in latest_results}

    entries: list[RequirementEvidenceMapEntry] = []
    for requirement in requirements:
        result: VerificationResult | None = (
            results_by_category_code.get(requirement.category_hint) if requirement.category_hint else None
        )

        if requirement.category_hint is None:
            status = "no_automated_check"
        elif result is None:
            status = "unmatched_missing"
        elif result.status in _PASSING_STATUSES:
            status = "matched"
        elif result.status in _FAILING_STATUSES:
            status = "unmatched_failed"
        else:
            # MISSING / NOT_CLAIMED -- checked, nothing declared.
            status = "unmatched_missing"

        entries.append(
            RequirementEvidenceMapEntry(
                requirement_id=requirement.id,
                requirement_text=requirement.requirement_text,
                category_hint=requirement.category_hint,
                is_mandatory=requirement.is_mandatory,
                status=status,
                verification_status=result.status if result else None,
                source_verification_result_id=result.id if result else None,
                source_document_id=result.source_document_id if result else None,
                source_document_name=(
                    result.source_document.file_name if result and result.source_document else None
                ),
            )
        )
    return entries
