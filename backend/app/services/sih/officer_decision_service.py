"""
Officer decision service -- SIH26100 Phase 1.

Structurally inspired by qualification_override_service.py's persist
shape, but not identical -- see app/models/sih/officer_decision.py's
docstring for why OfficerDecision is insert-only (mirrors
Recommendation's history pattern) rather than a unique-row toggle like
QualificationOverride. A decision is never updated or deleted here --
recording a new one is how a decision is "changed"; the full history
stays queryable via get_decision_history().
"""

import uuid

from sqlalchemy.orm import Session

from app.models.sih.bidder import BidderSubmission
from app.models.sih.enums import OfficerDecisionType
from app.models.sih.officer_decision import OfficerDecision
from app.services.exceptions import NotFoundError


class InvalidDecisionError(Exception):
    """Raised when a decision note is missing/blank, or a decision value is invalid."""


def record_decision(
    db: Session,
    submission_id: uuid.UUID,
    officer_id: uuid.UUID,
    decision: OfficerDecisionType,
    note: str,
) -> OfficerDecision:
    submission = db.get(BidderSubmission, submission_id)
    if submission is None:
        raise NotFoundError(f"BidderSubmission '{submission_id}' not found.")

    if not isinstance(decision, OfficerDecisionType):
        raise InvalidDecisionError(f"'{decision}' is not a valid OfficerDecisionType.")

    # The note is mandatory here at the service layer -- Phase 1 has no
    # API router yet, so there is no schema/Pydantic boundary to enforce
    # it instead (contrast QualificationOverride, whose note is required
    # by OverrideRequirementRequest's field_validator, not the DB/service
    # layer alone).
    if note is None or not note.strip():
        raise InvalidDecisionError("A note explaining the decision is required.")

    record = OfficerDecision(
        submission_id=submission_id,
        officer_id=officer_id,
        decision=decision,
        note=note.strip(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_latest_decision(db: Session, submission_id: uuid.UUID) -> OfficerDecision | None:
    """The current decision -- the most recent row, never mutated in place."""
    return (
        db.query(OfficerDecision)
        .filter(OfficerDecision.submission_id == submission_id)
        .order_by(OfficerDecision.decided_at.desc())
        .first()
    )


def get_decision_history(db: Session, submission_id: uuid.UUID) -> list[OfficerDecision]:
    """Every decision ever recorded for this submission, oldest first --
    nothing is ever silently overwritten, so this is always the complete audit trail."""
    return (
        db.query(OfficerDecision)
        .filter(OfficerDecision.submission_id == submission_id)
        .order_by(OfficerDecision.decided_at.asc())
        .all()
    )
