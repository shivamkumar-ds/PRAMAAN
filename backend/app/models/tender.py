"""Tender, Requirement, CapabilityMapping — 05_Database_Design.md."""

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import CapabilityEntityType, MatchStatus, RequirementNature, RequirementType
from app.models.mixins import UUIDPrimaryKeyMixin


class Tender(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "tenders"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("missions.id"), nullable=False, index=True
    )
    tender_name: Mapped[str | None] = mapped_column(String, nullable=True)
    organization: Mapped[str | None] = mapped_column(String, nullable=True)
    # Free-text category label chosen from the frontend's static
    # TENDER_CATEGORIES list (lib/tenderCategories.ts) -- stored as plain
    # text, not an enum, since the category list is a product/UX choice
    # that may grow without a schema migration. Nullable at the DB level
    # so existing rows uploaded before this column existed stay valid;
    # the frontend enforces it as required for new uploads.
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    closing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    uploaded_document: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    processing_status: Mapped[str | None] = mapped_column(String, nullable=True)


class Requirement(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "requirements"

    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False, index=True
    )
    requirement_type: Mapped[RequirementType] = mapped_column(
        Enum(RequirementType, name="requirement_type"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    # A real PDF page number when the requirement came from a PDF page --
    # None when it came from a non-paginated source (a spreadsheet sheet)
    # or when a segment's original unit can't be resolved back to a page.
    # Unchanged in meaning and always populated exactly as before for a
    # tender with a single PDF document (multi-document support's
    # backward-compatibility guarantee) -- see tender_analyzer.py.
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Which attached Document this requirement was actually extracted
    # from -- always populated once a tender has more than one source
    # document, since source_page alone can no longer identify "which
    # document" once a tender combines a PDF and a spreadsheet. Nullable
    # only for Requirement rows persisted before this column existed.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    # Human-readable, format-agnostic location within source_document_id
    # -- "Page 3" for a PDF page, "Sheet: Sheet1" for a spreadsheet sheet.
    # This (not source_page) is what the evidence trail actually displays
    # for a requirement extracted from a non-PDF source.
    source_location: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    # Architecture debate Phase 1 (see BidOps_Architecture_Debate.md):
    # orthogonal to requirement_type -- what this requirement actually IS
    # from a procurement-consequence standpoint, not what surface
    # category it was filed under. Nullable, no default, no backfill --
    # every Requirement row that existed before this column was added
    # reads as NULL and nothing in decision_engine.py/decision_service.py
    # reads this column yet (deferred to Phase 2). See
    # RequirementNature's docstring in app/models/enums.py for the four
    # values and how they're classified.
    requirement_nature: Mapped[RequirementNature | None] = mapped_column(
        Enum(RequirementNature, name="requirement_nature"), nullable=True
    )


class CapabilityMapping(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "capability_mappings"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id"), nullable=False, index=True
    )

    # Polymorphic reference to one of the five capability entity tables —
    # see the structural-gap note given before this step. Integrity across
    # the referenced table is enforced at the application layer, since a
    # single DB foreign key can't target one of five different tables.
    capability_entity_type: Mapped[CapabilityEntityType] = mapped_column(
        Enum(CapabilityEntityType, name="capability_entity_type"), nullable=False
    )
    # index=True: revalidation_service.find_affected_missions() filters by
    # (capability_entity_type, capability_entity_id) on every capability
    # update/removal (RC-1 audit finding B3) — unindexed until now.
    capability_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    match_status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus, name="match_status"), nullable=False
    )
    evidence: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
