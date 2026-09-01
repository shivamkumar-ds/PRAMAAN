"""
BidderDocument -- SIH26100 Phase 4.

The minimum SIH-specific persistence needed to associate an uploaded
bidder document with a BidderSubmission and track its AI extraction
lifecycle. Deliberately its own table, not a reuse of app.models.Document:
that model is company-scoped (uploaded by a BidOps *tenant* about their
own capabilities) with no concept of a BidderSubmission at all, and
retrofitting a submission_id + extraction-status vocabulary onto it would
be exactly the kind of force-fit into an unrelated domain the Phase 0
report already ruled against for Tender/Requirement. The physical file
itself IS reused, though -- every byte goes through the existing
app.core.storage module (save_upload/local_file_for_read/delete_file),
scoped under the bidder's own company_id, unchanged.

extracted_data is JSONB, not individual relational columns: each
compliance category's extraction schema has a different field set (see
app/schemas/sih_extraction.py), exactly the same reasoning already
applied to RegistryRecord.record_data and VerificationResult.declared_value/
registry_value in Phase 1.

Confirmation (Phase 5) -- is_confirmed / confirmed_data / confirmed_at /
confirmed_by / manually_corrected: deliberately a separate flag+column
set, NOT a new DocumentExtractionStatus enum member. Two reasons: (1)
Postgres enum types can only gain a value via ALTER TYPE ... ADD VALUE,
which cannot run inside a transaction on the Postgres versions this
project has to assume in the field, and is effectively irreversible (no
DROP VALUE) -- a plain boolean+columns migration is safe to both apply
and roll back cleanly, consistent with every other additive migration in
this package; (2) "confirmed" is orthogonal to "how extraction went" --
a document can be EXTRACTED-and-unconfirmed or EXTRACTED-and-confirmed,
but FAILED/REVIEW_REQUIRED/PENDING can never be confirmed at all, which
reads more clearly as a guard on `is_confirmed` than as five more enum
combinations. confirmed_data is deliberately its own column, not an
in-place overwrite of extracted_data: extracted_data stays the immutable
record of what the AI actually produced (audit trail), while
confirmed_data is what the officer signed off on -- identical to
extracted_data when accepted as-is, different when corrected
(manually_corrected=True). Only confirmed_data (never extracted_data)
ever reaches declared_facts -- see
app/services/sih/document_service.build_verification_inputs_from_documents().
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin
from app.models.sih.enums import DocumentExtractionStatus


class BidderDocument(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "sih_bidder_documents"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sih_bidder_submissions.id"), nullable=False, index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Nullable -- an officer may upload without picking a category, in
    # which case classify_document() (deterministic keyword heuristic,
    # not an LLM call -- see sih_document_extractor.py) attempts to
    # determine it. If it can't decide confidently, this stays NULL and
    # extraction_status is REVIEW_REQUIRED -- never a silent guess.
    category_code: Mapped[str | None] = mapped_column(
        String, ForeignKey("sih_compliance_categories.code"), nullable=True, index=True
    )
    # "officer": the uploader explicitly chose the category at upload time.
    # "auto": classify_document() assigned it. "unclassified": neither --
    # category_code is NULL and extraction_status is REVIEW_REQUIRED.
    category_source: Mapped[str] = mapped_column(String, nullable=False, default="unclassified")

    file_name: Mapped[str] = mapped_column(String, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    extraction_status: Mapped[DocumentExtractionStatus] = mapped_column(
        Enum(DocumentExtractionStatus, name="sih_document_extraction_status"),
        default=DocumentExtractionStatus.PENDING,
        nullable=False,
    )
    # The validated, structured extraction result (one of the schemas in
    # app/schemas/sih_extraction.py, model_dump()'d) -- never raw LLM
    # prose. Populated only when extraction_status == EXTRACTED.
    extracted_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(String, nullable=True)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Officer confirmation (Phase 5) -- see module docstring. ---
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmed_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    manually_corrected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    submission: Mapped["BidderSubmission"] = relationship()


class AuthenticityScan(Base, UUIDPrimaryKeyMixin):
    """
    One Authenticity Scanner run against a BidderDocument's actual stored
    file (SIH26100 demo-scope expansion, minimal-real engine) --
    insert-only, mirroring VerificationResult: a document's scan history
    is preserved across re-scans, never overwritten in place.

    Deliberately narrow scope, per the governing brief: metadata analysis
    (PDF producer/creator/mod-vs-creation-date via pypdf, image EXIF
    presence/consistency via Pillow) and basic structural consistency
    checks against the SAME physical file BidderDocument.storage_path
    already points to -- app.services.sih.authenticity_service reuses
    app.core.storage unchanged, no second file-storage path. This is
    explicitly NOT forensic image analysis (no pixel-level tamper
    detection, no ELA, no ML classifier) -- indicators is a list of
    named, explainable observations, and summary_label is one of a
    small closed vocabulary (see authenticity_service.py) that never
    asserts a document is "genuine" or "forged," only what was and
    wasn't observed.
    """

    __tablename__ = "sih_authenticity_scans"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sih_bidder_documents.id"), nullable=False, index=True
    )
    # Structured, explainable indicator list -- see
    # authenticity_service.AuthenticityIndicator for the shape each entry
    # takes (code, label, detail, severity). Never a raw score alone.
    indicators: Mapped[list] = mapped_column(JSONB, nullable=False)
    # One of authenticity_service.SummaryLabel's closed set -- e.g.
    # "no_anomalies_detected" / "indicators_present" / "not_analyzable" --
    # deliberately never "authentic" or "forged".
    summary_label: Mapped[str] = mapped_column(String, nullable=False)
    scanned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    document: Mapped["BidderDocument"] = relationship()
