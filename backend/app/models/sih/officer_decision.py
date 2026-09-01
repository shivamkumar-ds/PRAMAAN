"""
OfficerDecision -- SIH26100's human-decision pattern, modeled on
app.models.qualification_override.QualificationOverride's audited-
override shape, but deliberately NOT the same table and NOT a
unique-per-target toggle. QualificationOverride itself is untouched by
this file.

QualificationOverride is a 2-state toggle (overridden / not) with a real
DELETE for "remove" -- appropriate there because removing an override IS
the meaningful action, and no history of toggles is needed. An
OfficerDecision is different: it is a 3-way outcome (APPROVE / REJECT /
REQUEST_CLARIFICATION) that must never be silently overwritten, per the
SIH26100 problem statement's audit-trail requirement. So this table is
insert-only, mirroring Recommendation's history pattern instead --
every decision action inserts a new row; nothing is ever deleted or
updated in place. The "current" decision for a submission is simply the
most recent row by decided_at -- see
app/services/sih/officer_decision_service.get_latest_decision().

`note` is NOT NULL at the DB layer (unlike QualificationOverride.note,
which is nullable at the DB layer and only required at the schema/API
boundary): Phase 1 requirement 6 makes the note mandatory, and since
this table has no API router yet in Phase 1, there is no schema layer to
enforce it instead. app/services/sih/officer_decision_service.py also
validates non-blank before insert, so both layers agree.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin
from app.models.sih.enums import OfficerDecisionType


class OfficerDecision(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "sih_officer_decisions"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sih_bidder_submissions.id"), nullable=False, index=True
    )
    officer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    decision: Mapped[OfficerDecisionType] = mapped_column(
        Enum(OfficerDecisionType, name="sih_officer_decision_type"), nullable=False
    )
    note: Mapped[str] = mapped_column(String, nullable=False)
    # Client-side `default` (microsecond precision) takes priority over
    # `server_default` at ORM-insert time -- deliberate, not redundant:
    # this table is insert-only and ordered by decided_at to determine
    # "the current decision" (get_latest_decision()), and Postgres'
    # func.now() is microsecond-precise but SQLite's (used by this
    # package's in-memory test DB) is only second-precise, which made two
    # decisions recorded within the same second silently tie and sort
    # unpredictably. server_default is kept as a DB-level fallback for
    # any insert that bypasses the ORM.
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
