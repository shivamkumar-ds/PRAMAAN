"""
ProcurementRequirement -- Requirement-to-Evidence Mapping engine.

One row per discrete eligibility/compliance requirement extracted from a
ProcurementDocument (e.g. "Bidder must hold a valid GST registration",
"Minimum annual turnover of Rs. 2 crore in the last 3 years", "Bidder
must not be blacklisted by any central government department"). This is
deliberately NOT modeled as app.models.tender.Requirement (the existing
bidder-side self-assessment domain's requirement extraction) -- same
"new, independent sibling domain" reasoning as every other SIH26100
model (see app/models/sih/__init__.py's module docstring): a
Requirement there is matched against a BidOps tenant's OWN capability
records; a ProcurementRequirement here is checked against a
third-party Bidder's compliance verification results for a specific
Procurement, an entirely different comparison.

Extracted-then-officer-reviewable, NOT authoritative until reviewed --
same honesty posture as every AI-extraction boundary in this package
(BidderDocument.extracted_data, ComplianceCategory's fixed checklist
vs. this open-ended extraction). category_hint is the AI's best guess
at which of the fixed ComplianceCategory checklist items (if any) this
requirement corresponds to; it is deliberately called "hint," not
"category," and is never treated as ground truth for scoring -- an
officer can be wrong-footed by a bad hint, but the system itself never
silently promotes a hint to an authoritative compliance verdict. See
procurement_requirement_service.get_requirement_evidence_map() for how
this hint is used: only to derive a read-only, honestly-labeled
mapping status (matched/unmatched_failed/unmatched_missing/
no_automated_check), never a new persisted verdict of its own.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class ProcurementRequirement(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "sih_procurement_requirements"

    procurement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sih_procurements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable -- a requirement whose source document was later deleted
    # (or, in principle, one entered by some future manual-entry path)
    # still stands on its own; there is no FK ondelete cascade from
    # sih_procurement_documents onto this table.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sih_procurement_documents.id"), nullable=True
    )
    requirement_text: Mapped[str] = mapped_column(Text, nullable=False)
    # A ComplianceCategory.code, or NULL when the AI could not map this
    # requirement to any of the fixed checklist categories (e.g. a
    # turnover or experience requirement with no corresponding
    # registry-backed category) -- an honest "nothing to automatically
    # check," never a forced/guessed mapping. No DB-level FK to
    # sih_compliance_categories.code on purpose: category_hint is
    # advisory extracted data, not a referential-integrity-enforced
    # relationship, and a category could in principle be deactivated
    # after extraction without invalidating historical requirement rows.
    category_hint: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    procurement: Mapped["Procurement"] = relationship()
    source_document: Mapped["ProcurementDocument | None"] = relationship()
