"""
Bid-readiness confirmation service.

Persistence + ownership checks for the "Confirm Prepared" action on
bid-readiness gap items (SUBMISSION_GATING / FUTURE_CONTRACTUAL_COMMITMENT
requirements) — see app/models/bid_readiness.py's docstring for what a
BidReadinessConfirmation row represents and the frozen boundary rule
(confirmations affect ONLY compute_bid_readiness()/classify_remediation(),
never compute_qualification()).
"""

import uuid

from sqlalchemy.orm import Session

from app.models import BidReadinessConfirmation, Requirement, Tender
from app.services import mission_service
from app.services.exceptions import ConflictError, NotFoundError


def _get_owned_requirement(
    db: Session, mission_id: uuid.UUID, requirement_id: uuid.UUID, company_id: uuid.UUID
) -> Requirement:
    """
    Ownership check for a mission-scoped requirement action, one hop
    beyond mission_service.get_mission()'s own company_id check: also
    verifies the requirement's tender genuinely belongs to the given
    mission_id, since a caller could otherwise pass a real requirement_id
    that belongs to a DIFFERENT mission the same company owns. A
    Requirement belongs to exactly one Tender, which belongs to exactly
    one Mission by convention (see app/models/tender.py), so this single
    tender_id -> mission_id hop is sufficient.
    """
    mission_service.get_mission(db, mission_id, company_id)  # raises NotFoundError if not owned by this company

    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise NotFoundError(f"Requirement '{requirement_id}' not found.")

    tender = db.query(Tender).filter(Tender.id == requirement.tender_id).one_or_none()
    if tender is None or tender.mission_id != mission_id:
        raise NotFoundError(f"Requirement '{requirement_id}' does not belong to mission '{mission_id}'.")

    return requirement


def confirm_requirement(
    db: Session,
    mission_id: uuid.UUID,
    requirement_id: uuid.UUID,
    company_id: uuid.UUID,
    confirmed_by: uuid.UUID,
    note: str | None = None,
) -> BidReadinessConfirmation:
    _get_owned_requirement(db, mission_id, requirement_id, company_id)

    existing = (
        db.query(BidReadinessConfirmation)
        .filter(BidReadinessConfirmation.requirement_id == requirement_id)
        .one_or_none()
    )
    if existing is not None:
        raise ConflictError(f"Requirement '{requirement_id}' is already confirmed.")

    confirmation = BidReadinessConfirmation(
        requirement_id=requirement_id, confirmed_by=confirmed_by, note=note
    )
    db.add(confirmation)
    db.commit()
    db.refresh(confirmation)
    return confirmation


def unconfirm_requirement(
    db: Session, mission_id: uuid.UUID, requirement_id: uuid.UUID, company_id: uuid.UUID
) -> None:
    _get_owned_requirement(db, mission_id, requirement_id, company_id)

    existing = (
        db.query(BidReadinessConfirmation)
        .filter(BidReadinessConfirmation.requirement_id == requirement_id)
        .one_or_none()
    )
    if existing is None:
        raise NotFoundError(f"Requirement '{requirement_id}' is not currently confirmed.")

    db.delete(existing)
    db.commit()


def get_confirmations_by_requirement_id(
    db: Session, requirement_ids: list[uuid.UUID]
) -> dict[uuid.UUID, BidReadinessConfirmation]:
    """
    Used by app/api/v1/evaluation.py to wire confirmed state into
    decision_engine.compute_bid_readiness()/classify_remediation() (via
    the set of keys) and into each GapAnalysisEntry's confirmed/
    confirmed_at fields (via the full row). Keyed by requirement_id.
    """
    if not requirement_ids:
        return {}
    rows = (
        db.query(BidReadinessConfirmation)
        .filter(BidReadinessConfirmation.requirement_id.in_(requirement_ids))
        .all()
    )
    return {row.requirement_id: row for row in rows}
