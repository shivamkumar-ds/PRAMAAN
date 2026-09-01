"""
BidReadinessConfirmation — human confirmation that a bid-readiness gap
item (a SUBMISSION_GATING or FUTURE_CONTRACTUAL_COMMITMENT requirement,
e.g. EMD, DSC, a PPE/safety declaration) has actually been prepared.

Deliberately keyed by requirement_id alone (UNIQUE) — a Requirement
belongs to exactly one Tender, which belongs to exactly one Mission by
convention, so requirement_id is already mission-scoped. One row per
requirement: confirming again is a no-op (handled at the service layer),
unconfirming is a real DELETE, not a soft-delete — there is no need to
keep a history of toggles, only "is this currently confirmed."

Never read by compute_qualification() — see the frozen boundary rule:
confirmations affect ONLY compute_bid_readiness()/classify_remediation().
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class BidReadinessConfirmation(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "bid_readiness_confirmations"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id"), nullable=False, unique=True
    )
    confirmed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String, nullable=True)
