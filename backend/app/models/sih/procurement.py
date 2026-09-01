"""
Procurement -- a GeM procurement opportunity, from the Procurement
Officer's side (SIH26100).

Deliberately NOT the same entity as app.models.tender.Tender (bidder-
side self-assessment): per the Phase 0 inspection report, most bidder
compliance facts (GST/PAN/Udyam/blacklist) are bidder-level, not
tender-level, and coupling this to Tender/Mission would force the same
Bidder to be re-verified from scratch on every Procurement, which is
neither how GeM should work nor cheap to build. See app/models/sih/bidder.py
for how Bidder stays independent of Procurement for exactly this reason.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin
from app.models.sih.enums import ProcurementStatus


class Procurement(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "sih_procurements"

    # Same multi-tenant boundary as the rest of BidOps -- the Company
    # running this Procurement Officer workflow (e.g. CPCL's own BidOps
    # tenant), never the Bidder being verified.
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    organization: Mapped[str | None] = mapped_column(String, nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String, nullable=True)
    # Plain string, not an enum -- same reasoning as Tender.category:
    # a product/UX classification that may grow without a migration.
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    closing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[ProcurementStatus] = mapped_column(
        Enum(ProcurementStatus, name="sih_procurement_status"),
        default=ProcurementStatus.OPEN,
        nullable=False,
    )
    # SIH26100 demo-scope expansion (Collusion Radar repeat-winner
    # indicator) -- which Bidder (if any) this Procurement was awarded to.
    # Nullable: most Procurements never reach an award in this prototype,
    # and nothing here infers one from OfficerDecision.APPROVE -- APPROVE
    # means "found compliant," never "won" (see collusion_radar_service.py's
    # original module docstring for why that conflation was explicitly
    # avoided). Settable only by an officer via
    # procurement_service.set_awarded_bidder(), gated
    # require_sih_award_role (Administrator/Executive only) -- awarding is
    # a business decision, not routine evidence-gathering, and this field
    # directly feeds the repeat-winner heuristic below, so it should never
    # be set casually or inferred automatically.
    awarded_bidder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sih_bidders.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    submissions: Mapped[list["BidderSubmission"]] = relationship(back_populates="procurement")
