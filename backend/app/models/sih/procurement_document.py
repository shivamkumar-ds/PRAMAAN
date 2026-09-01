"""
ProcurementDocument -- Requirement-to-Evidence Mapping engine.

The officer's own uploaded tender/procurement document (e.g. the GeM
bid document that spells out eligibility/compliance requirements) --
NOT a third-party bidder's evidence. This is the key distinction from
BidderDocument (app/models/sih/document.py): a BidderDocument is a
claim made by someone else (the bidder) that must be officer-confirmed
before it can ground a verification result (see
grounding_guard_service.py). A ProcurementDocument is the officer's own
upload about their own tender -- there is no third party to distrust
here, so there is deliberately no is_confirmed/confirmed_data
confirmation gate on this model. The requirements extracted FROM it
(ProcurementRequirement, procurement_requirement.py) still carry their
own "extracted, officer-reviewable, not yet authoritative" caveat --
see that model's docstring -- but that caveat is about extraction
accuracy, not about trusting a third party.

Same storage reuse discipline as BidderDocument: every byte goes
through the existing app.core.storage module (save_upload/
local_file_for_read/delete_file), scoped under the officer's own
company_id, unchanged. No second file-storage abstraction.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin
from app.models.sih.enums import ProcurementDocumentExtractionStatus


class ProcurementDocument(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "sih_procurement_documents"

    procurement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sih_procurements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    extraction_status: Mapped[ProcurementDocumentExtractionStatus] = mapped_column(
        Enum(ProcurementDocumentExtractionStatus, name="sih_procurement_document_extraction_status"),
        default=ProcurementDocumentExtractionStatus.PENDING,
        nullable=False,
    )
    extraction_error: Mapped[str | None] = mapped_column(String, nullable=True)

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Nullable -- unlike BidderDocument.uploaded_by (always a real officer
    # action), this is left nullable defensively for any future
    # system-initiated upload path; every current call site always sets
    # it to the requesting officer's user id.
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    procurement: Mapped["Procurement"] = relationship()
