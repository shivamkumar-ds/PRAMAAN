"""
Tender service.

upload_tender() implements 06_API_Design.md's existing contract (tender
upload returns both Tender ID and Mission ID) — it creates a minimal,
inert Mission row alongside the Tender, with no orchestration logic.
State transitions and agent coordination remain M7's job; this Mission
just exists in CREATED status until M7 can drive it.

Company scoping goes through Tender -> Mission -> company_id, since
Tender has no company_id column of its own.
"""

import tempfile
import uuid
from contextlib import ExitStack
from datetime import date
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.agents import document_parser, tender_analyzer, tender_metadata_guess
from app.agents.tender_analyzer import TenderSourceDocument
from app.core import storage
from app.models import Document, Mission, Requirement, Tender
from app.models.enums import DocumentProcessingStatus, MissionStatus, RequirementNature, RequirementType
from app.services import document_service
from app.services.exceptions import ExtractionError, NotFoundError

# Filename-based document-role inference (Section 5 of the governing
# spec: infer where reasonably possible, never force the user through a
# manual classification step for the common case). Deliberately simple
# substring matching, not a second AI call -- checked in order, first
# match wins. Anything unmatched defaults to "annexure" (Supporting),
# the safest default since it's still included in LLM extraction input
# (unlike "financial", which is excluded -- see tender_analyzer.py).
_ROLE_KEYWORDS: list[tuple[str, str]] = [
    ("boq", "financial"),
    ("financial", "financial"),
    ("price", "financial"),
    ("commercial", "financial"),
    ("tech", "technical"),
    ("annex", "annexure"),
    ("supporting", "annexure"),
]


def _infer_document_role(file_name: str) -> str:
    lowered = file_name.lower()
    for keyword, role in _ROLE_KEYWORDS:
        if keyword in lowered:
            return role
    return "annexure"


async def upload_tender(
    db: Session,
    company_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    file: UploadFile,
    tender_name: str | None = None,
    organization: str | None = None,
    closing_date: date | None = None,
    category: str | None = None,
) -> tuple[Mission, Tender]:
    document = await document_service.upload_document(db, company_id, uploaded_by, "tender", file)

    mission = Mission(
        company_id=company_id,
        user_id=uploaded_by,
        mission_type="tender_evaluation",
        status=MissionStatus.CREATED,
    )
    db.add(mission)
    db.flush()  # assigns mission.id without committing yet

    tender = Tender(
        mission_id=mission.id,
        tender_name=tender_name,
        organization=organization,
        category=category,
        closing_date=closing_date,
        uploaded_document=document.id,
        processing_status=DocumentProcessingStatus.PENDING.value,
    )
    db.add(tender)
    db.flush()  # assigns tender.id so the document can be linked to it below

    # General Tender<->Document relationship (multi-document support) --
    # the original PDF is always "main". uploaded_document above is kept
    # unchanged for backward compatibility (see migration
    # d4e5f6a7b8c9's docstring); this is the new, general link that
    # run_analysis() and GET /tenders/{id}'s documents list actually use.
    document.tender_id = tender.id
    document.document_role = "main"

    db.commit()
    db.refresh(mission)
    db.refresh(tender)
    return mission, tender


async def add_tender_document(
    db: Session,
    tender_id: uuid.UUID,
    company_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    file: UploadFile,
    document_role: str | None = None,
) -> Document:
    """
    Attaches an additional source document (e.g. tech.xls, BOQ_*.xls) to
    an existing Tender -- Section 1 of the governing spec. Reuses
    document_service.upload_document() for storage/validation (same
    ALLOWED_EXTENSIONS gate as any other document, so PDF/XLS/XLSX are
    all accepted, everything else still rejected exactly as before);
    this function only adds the tender-linking step upload_tender()
    already does for the main document.
    """
    tender = get_tender(db, tender_id, company_id)  # raises NotFoundError if not this company's

    document = await document_service.upload_document(db, company_id, uploaded_by, "tender", file)
    document.tender_id = tender.id
    document.document_role = document_role or _infer_document_role(document.file_name)
    db.commit()
    db.refresh(document)
    return document


def list_tender_documents(db: Session, tender_id: uuid.UUID, company_id: uuid.UUID) -> list[Document]:
    get_tender(db, tender_id, company_id)  # raises NotFoundError / enforces company scoping
    return (
        db.query(Document)
        .filter(Document.tender_id == tender_id, Document.removed_at.is_(None))
        .order_by(Document.upload_time.asc())
        .all()
    )


async def extract_tender_metadata(file: UploadFile) -> dict:
    """Best-effort, heuristic-only (no LLM call) read of a just-selected PDF's
    first couple of pages, purely to prefill the New Tender upload form before
    the user commits. Nothing here is persisted -- the file is read into a
    temp path, parsed, and discarded. Any/all fields can legitimately come
    back None."""
    suffix = Path(file.filename).suffix if file.filename else ".pdf"
    contents = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(contents)
        tmp.flush()
        try:
            pages = document_parser.extract_pdf_pages(Path(tmp.name))
        except Exception as exc:
            raise ExtractionError(f"Could not read PDF: {exc}") from exc
    await file.seek(0)
    text = "\n".join(pages[:2])
    return tender_metadata_guess.guess_metadata(text)


def get_tender(db: Session, tender_id: uuid.UUID, company_id: uuid.UUID) -> Tender:
    tender = (
        db.query(Tender)
        .join(Mission, Tender.mission_id == Mission.id)
        .filter(Tender.id == tender_id, Mission.company_id == company_id)
        .one_or_none()
    )
    if tender is None:
        raise NotFoundError(f"Tender '{tender_id}' not found.")
    return tender


def get_requirements(db: Session, tender_id: uuid.UUID) -> list[Requirement]:
    return (
        db.query(Requirement)
        .filter(Requirement.tender_id == tender_id)
        .order_by(Requirement.source_page)
        .all()
    )


async def run_analysis(
    db: Session, tender_id: uuid.UUID, company_id: uuid.UUID, provider: str | None = None
) -> tuple[Tender, list[Requirement]]:
    tender = get_tender(db, tender_id, company_id)  # raises NotFoundError if not this company's

    tender.processing_status = DocumentProcessingStatus.PROCESSING.value
    db.commit()

    # Bug #002: this whole block used to sit outside the try/except below,
    # so a missing Document row or an unresolvable storage path raised a
    # bare AttributeError straight out of the service — an unclean 500,
    # and (worse) the tender was left stuck in PROCESSING forever, since
    # nothing ever set it to FAILED. Folded into the same failure handling
    # as an analyzer error.
    #
    # Multi-document support: every non-removed Document attached to this
    # Tender (Document.tender_id) is gathered, not just the single
    # uploaded_document -- this is the general query the migration's
    # backfill exists to make correct for pre-existing tenders too (every
    # such tender ends up with exactly one tender_id-linked Document,
    # role "main", identical in effect to the old single-document path).
    try:
        documents = (
            db.query(Document)
            .filter(Document.tender_id == tender.id, Document.removed_at.is_(None))
            .order_by(Document.upload_time.asc())
            .all()
        )
        if not documents:
            raise ExtractionError(
                f"Tender '{tender_id}' has no attached documents that still exist."
            )

        # local_file_for_read() is backend-agnostic (Phase 3: GCP
        # deployment) -- downloads from GCS to a temp file first when
        # STORAGE_BACKEND=gcs, yields the existing on-disk path unchanged
        # otherwise. ExitStack holds every attached document's context open
        # simultaneously (a GCS-backed tender may need several temp files
        # alive at once, one per document, for the duration of the single
        # analyze_tender() call below).
        with ExitStack() as stack:
            sources = [
                TenderSourceDocument(
                    document_id=document.id,
                    file_name=document.file_name,
                    document_role=document.document_role,
                    file_path=stack.enter_context(storage.local_file_for_read(document.storage_path)),
                )
                for document in documents
            ]
            results = await tender_analyzer.analyze_tender(sources, provider=provider)
    except Exception as exc:
        tender.processing_status = DocumentProcessingStatus.FAILED.value
        db.commit()
        if isinstance(exc, ExtractionError):
            raise
        raise ExtractionError(f"Tender analysis failed for tender '{tender_id}': {exc}") from exc

    requirement_rows = []
    for result in results:
        requirement = Requirement(
            tender_id=tender.id,
            requirement_type=RequirementType(result.requirement_type),
            description=result.description,
            mandatory=result.mandatory,
            source_page=result.source_page,
            source_document_id=result.source_document_id,
            source_location=result.source_location,
            confidence=result.confidence,
            # Architecture debate Phase 1 -- result.requirement_nature is
            # always a valid RequirementNature value by this point
            # (tender_analyzer._resolve_nature() already resolved/fell
            # back on it), never the LLM's raw, untrusted output.
            requirement_nature=RequirementNature(result.requirement_nature),
        )
        db.add(requirement)
        requirement_rows.append(requirement)

    tender.processing_status = DocumentProcessingStatus.COMPLETED.value
    db.commit()
    for requirement in requirement_rows:
        db.refresh(requirement)

    return tender, requirement_rows
