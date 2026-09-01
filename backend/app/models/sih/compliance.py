"""
ComplianceCategory, RegistryRecord, VerificationResult -- SIH26100.

ComplianceCategory is a small, fixed, seeded registry (Udyam, GST, PAN/
ITR, EPFO/ESIC, Blacklisting, plus roadmap categories marked inactive) --
deliberately NOT modeled as app.models.tender.Requirement rows. A
Requirement is extracted per-tender from unbounded document text; a
ComplianceCategory is a closed, universal set that doesn't change per
Procurement (see the Phase 0 report's "fixed categories vs extracted
requirements" analysis). Default seed data lives in
app/services/sih/compliance_category_service.py.

RegistryRecord is the deterministic mock government-registry data store
-- Phase 1 explicitly never calls a real government API (the SIH26100
problem statement itself requires this to be simulated). Adapters in
app/services/sih/registry_adapters.py read from this table.

VerificationResult is the SIH analogue of ComplianceMatrix/MatchResult,
but persists both sides of a comparison (bidder-declared vs registry)
plus discrepancies, not just a verdict -- the officer-facing UI needs to
show "bidder said X / registry says Y" side by side. Deterministic
registry facts (source/checked_at/discrepancies/reason) are kept
strictly separate from any later AI-generated explanation
(ai_explanation, unpopulated in Phase 1 -- no AI explanation generation
exists yet), per the Phase 0 report's identity-resolution/score-risk
discussion.

Insert-only, mirroring decision_service.run_evaluation()'s history
pattern: each verification run inserts fresh VerificationResult rows
rather than updating in place, so a submission's verification history is
never silently overwritten. "Current" state for a (submission, category)
pair is the most recent row by checked_at -- see
app/services/sih/verification_service.get_latest_results().
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin
from app.models.sih.enums import ComplianceVerificationStatus


class ComplianceCategory(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "sih_compliance_categories"

    code: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # Default mandatory-ness. Per-submission mandatory-ness (e.g. Startup
    # India is only mandatory if the bidder claims that benefit) is
    # resolved by verification_service, not hardcoded here as a single
    # boolean -- see the Phase 0 report's "fixed categories" section.
    mandatory_by_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    risk_weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    # Matches a key in app/services/sih/registry_adapters.py's adapter
    # registry. Categories with no adapter implemented yet (roadmap
    # items) are seeded with is_active=False rather than omitted, so a
    # future UI can show the full 9/10-category checklist without
    # pretending unimplemented categories don't exist.
    adapter_key: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RegistryRecord(Base, UUIDPrimaryKeyMixin):
    """
    One deterministic mock government-registry entry. Phase 1 never
    calls a real government API -- adapters query this table by
    (category_code, identifier_type, identifier_value). Seed data lives
    in app/services/sih/mock_registry_data.py.
    """

    __tablename__ = "sih_registry_records"

    category_code: Mapped[str] = mapped_column(
        String, ForeignKey("sih_compliance_categories.code"), nullable=False, index=True
    )
    identifier_type: Mapped[str] = mapped_column(String, nullable=False)
    identifier_value: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # The registry's own facts, shaped per category (entity_name, status,
    # issue_date, etc.) -- deliberately schemaless at the DB layer since
    # each category's real-world registry has a different field set;
    # each adapter knows how to read its own category's shape.
    record_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VerificationResult(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "sih_verification_results"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sih_bidder_submissions.id"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sih_compliance_categories.id"), nullable=False, index=True
    )
    status: Mapped[ComplianceVerificationStatus] = mapped_column(
        Enum(ComplianceVerificationStatus, name="sih_verification_status"), nullable=False
    )
    # Both sides of the comparison, preserved -- what the bidder claims
    # and what the (mock) registry says -- so an officer-facing UI can
    # show them side by side rather than only a collapsed verdict.
    declared_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    registry_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    discrepancies: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # AI-assisted identity-resolution confidence (e.g. fuzzy name/address
    # match) -- deliberately unused for the deterministic categories
    # built in Phase 1 (PAN comparisons are exact, never confidence-
    # scored; see the Phase 0 report's identity-resolution proposal).
    # Reserved for a later phase.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    # Deterministic, adapter-generated explanation of the verdict -- kept
    # strictly separate from any later AI-generated natural-language
    # explanation (ai_explanation, unpopulated in Phase 1).
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_explanation: Mapped[str | None] = mapped_column(String, nullable=True)
    # Phase 5 evidence linking: which BidderDocument (if any) the
    # declared_value on this row came from -- lets the officer trace
    # "why this result?" back to a specific uploaded file without
    # re-reading raw document text. NULL for the manual-entry verify path
    # (POST .../verify with a hand-typed declared_facts body) and for
    # categories with no matching document (e.g. blacklisting, which is a
    # pure PAN/registry lookup) -- never guessed or backfilled.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sih_bidder_documents.id"), nullable=True
    )
    # Client-side `default` (microsecond precision), same reasoning as
    # OfficerDecision.decided_at -- this table is insert-only and
    # get_latest_results() relies on checked_at ordering to collapse to
    # "the current result per category," which needs sub-second
    # precision to stay correct when a submission is re-verified quickly
    # (as happens in tests, and could happen in production too).
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    submission: Mapped["BidderSubmission"] = relationship()
    category: Mapped["ComplianceCategory"] = relationship()
    source_document: Mapped["BidderDocument | None"] = relationship()
