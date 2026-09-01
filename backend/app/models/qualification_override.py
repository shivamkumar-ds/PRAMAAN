"""
QualificationOverride — an administrator's explicit, audited decision to
let a mandatory CAPABILITY_CLAIM gap stop blocking qualification, even
though no real capability evidence exists for it yet.

This is a DIFFERENT axis from BidReadinessConfirmation (app/models/
bid_readiness.py). Confirmation says "this SUBMISSION_GATING/FUTURE_
CONTRACTUAL_COMMITMENT item is genuinely prepared" -- a fact the matching
engine could never observe, because there is no capability entity that
could ever satisfy an EMD/DSC clause. An override is a different kind of
statement entirely: "the company does NOT yet have real evidence for this
capability requirement, and the administrator is choosing to proceed
anyway" -- a genuine, explicit risk acceptance, not a confirmation of an
already-true fact.

Because of that difference, an override must never be silently
indistinguishable from real evidence. Every consumer that reads
overridden_requirement_ids (decision_engine.compute_qualification(),
GapAnalysisEntry, the PDF report, Action Center, Tender Workspace) is
required to keep the overridden item visible and labeled as an
administrator override -- never absorbed into "requirement met" language.
See decision_engine.compute_qualification()'s own docstring for exactly
how this is threaded through.

Same persistence shape as BidReadinessConfirmation and the same reasoning
for it: keyed by requirement_id (UNIQUE) since a Requirement belongs to
exactly one Tender -> one Mission; overriding again is a no-op guarded at
the service layer; removing an override is a real DELETE (no history of
toggles needed, only "is this currently overridden").
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class QualificationOverride(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "qualification_overrides"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id"), nullable=False, unique=True
    )
    overridden_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    overridden_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Not optional in the API layer (ManualOverrideRequest requires it) --
    # nullable here only so a future non-Action-Center caller can't be
    # blocked by a DB constraint; the real "must explain why" requirement
    # is enforced at the schema/router boundary, matching how every other
    # business-rule validation in this codebase is enforced above the ORM.
    note: Mapped[str | None] = mapped_column(String, nullable=True)
