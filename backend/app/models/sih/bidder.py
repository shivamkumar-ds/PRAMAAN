"""
Bidder and BidderSubmission -- SIH26100.

A Bidder is independent of any one Procurement (its GST/PAN/Udyam/
blacklist facts don't change per tender -- see procurement.py's
docstring); a BidderSubmission is the join between one Bidder and one
Procurement, and is what actually gets verified/scored/decided on.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin
from app.models.sih.enums import SubmissionStatus


class Bidder(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "sih_bidders"

    # Same multi-tenant boundary as Procurement -- which BidOps company
    # (government/PSU tenant) this Bidder record belongs to.
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    legal_name: Mapped[str] = mapped_column(String, nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # The canonical identity anchor (Phase 0 report's identity-resolution
    # proposal) -- PAN match/mismatch across documents/registries is
    # meant to be deterministic, never AI-softened (see
    # app/services/sih/registry_adapters.py). Indexed, not unique: a
    # bidder without a PAN on file yet is still a valid (if immediately
    # CRITICAL_FAIL-flagged, see PANIncomeTaxAdapter) row, and two
    # different Bidder rows should never silently merge just because a
    # PAN string collides on bad data entry -- de-duplication is a
    # deliberate, later, explicit operation, not an implicit DB
    # constraint.
    pan: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # SIH26100 demo-scope expansion (Bidder Network Graph, minimal-real):
    # optional identifiers a bidder may share with another unrelated-on-
    # paper bidder -- a shared director, registered address, or contact
    # point is a real, checkable signal a procurement officer would want
    # surfaced (never proof of wrongdoing by itself). All four nullable;
    # nothing here is invented when blank -- see
    # app/services/sih/network_graph_service.py for how the absence of a
    # field is handled (that bidder simply contributes no relationship on
    # that dimension, never a fabricated one).
    registered_address: Mapped[str | None] = mapped_column(String, nullable=True)
    director_name: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    submissions: Mapped[list["BidderSubmission"]] = relationship(back_populates="bidder")


class BidderSubmission(Base, UUIDPrimaryKeyMixin):
    """
    One Bidder's submission against one Procurement -- the actual unit
    of verification/scoring/officer-decision. Unique per (procurement,
    bidder) pair: re-submission/re-verification inserts fresh
    VerificationResult/OfficerDecision rows against the SAME
    BidderSubmission, it does not create a second submission row.
    """

    __tablename__ = "sih_bidder_submissions"
    __table_args__ = (
        UniqueConstraint("procurement_id", "bidder_id", name="uq_sih_submission_procurement_bidder"),
    )

    procurement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sih_procurements.id"), nullable=False, index=True
    )
    bidder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sih_bidders.id"), nullable=False, index=True
    )
    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus, name="sih_submission_status"),
        default=SubmissionStatus.SUBMITTED,
        nullable=False,
    )
    # SIH26100 demo-scope expansion (Collusion Radar, minimal-real):
    # the bidder's quoted price for this Procurement. Nullable -- no bid
    # amount existed anywhere in the SIH domain before this column, and
    # nothing here fabricates one; a submission with no bid_amount is
    # simply excluded from value-based collusion heuristics (see
    # app/services/sih/collusion_radar_service.py), never assumed to be
    # zero or an average.
    bid_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    procurement: Mapped["Procurement"] = relationship(back_populates="submissions")
    bidder: Mapped["Bidder"] = relationship(back_populates="submissions")
