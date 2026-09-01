"""
Qualification override service.

Persistence + ownership checks for the "Administrator Override" action on
qualification gaps (mandatory CAPABILITY_CLAIM requirements not yet MET)
-- see app/models/qualification_override.py's docstring for what a
QualificationOverride row represents and how it differs from
BidReadinessConfirmation. Structurally mirrors bid_readiness_service.py
exactly (same ownership-check shape, same confirm/unconfirm-style
override/remove pair) -- kept as a separate module rather than merged
with bid_readiness_service.py because the two represent genuinely
different concepts (a confirmed fact vs. an explicit risk acceptance) and
the frozen architecture treats them as separate axes
(compute_bid_readiness() vs. compute_qualification()).
"""

import uuid

from sqlalchemy.orm import Session

from app.models import QualificationOverride, Requirement, Tender, User
from app.services import mission_service
from app.services.exceptions import ConflictError, NotFoundError


def _get_owned_requirement(
    db: Session, mission_id: uuid.UUID, requirement_id: uuid.UUID, company_id: uuid.UUID
) -> Requirement:
    """Same ownership check as bid_readiness_service._get_owned_requirement
    -- see that function's docstring for the full reasoning."""
    mission_service.get_mission(db, mission_id, company_id)  # raises NotFoundError if not owned by this company

    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise NotFoundError(f"Requirement '{requirement_id}' not found.")

    tender = db.query(Tender).filter(Tender.id == requirement.tender_id).one_or_none()
    if tender is None or tender.mission_id != mission_id:
        raise NotFoundError(f"Requirement '{requirement_id}' does not belong to mission '{mission_id}'.")

    return requirement


def override_requirement(
    db: Session,
    mission_id: uuid.UUID,
    requirement_id: uuid.UUID,
    company_id: uuid.UUID,
    overridden_by: uuid.UUID,
    note: str,
) -> QualificationOverride:
    _get_owned_requirement(db, mission_id, requirement_id, company_id)

    existing = (
        db.query(QualificationOverride)
        .filter(QualificationOverride.requirement_id == requirement_id)
        .one_or_none()
    )
    if existing is not None:
        raise ConflictError(f"Requirement '{requirement_id}' is already overridden.")

    override = QualificationOverride(
        requirement_id=requirement_id, overridden_by=overridden_by, note=note
    )
    db.add(override)
    db.commit()
    db.refresh(override)
    return override


def remove_override(
    db: Session, mission_id: uuid.UUID, requirement_id: uuid.UUID, company_id: uuid.UUID
) -> None:
    _get_owned_requirement(db, mission_id, requirement_id, company_id)

    existing = (
        db.query(QualificationOverride)
        .filter(QualificationOverride.requirement_id == requirement_id)
        .one_or_none()
    )
    if existing is None:
        raise NotFoundError(f"Requirement '{requirement_id}' is not currently overridden.")

    db.delete(existing)
    db.commit()


def get_overrides_by_requirement_id(
    db: Session, requirement_ids: list[uuid.UUID]
) -> dict[uuid.UUID, QualificationOverride]:
    """
    Used by app/api/v1/evaluation.py to wire overridden state into
    decision_engine.compute_qualification()/classify_remediation() (via
    the set of keys) and into each GapAnalysisEntry's overridden/
    overridden_at/override_note fields (via the full row). Keyed by
    requirement_id.
    """
    if not requirement_ids:
        return {}
    rows = (
        db.query(QualificationOverride)
        .filter(QualificationOverride.requirement_id.in_(requirement_ids))
        .all()
    )
    return {row.requirement_id: row for row in rows}


def resolve_overrider_names(db: Session, overrides: list[QualificationOverride]) -> dict[uuid.UUID, str]:
    """Resolves each override's overridden_by (a User id) into that
    user's display name -- same shape as decision_service.resolve_verifier_names()."""
    overrider_ids = {o.overridden_by for o in overrides}
    if not overrider_ids:
        return {}
    users = db.query(User).filter(User.id.in_(overrider_ids)).all()
    return {user.id: user.name for user in users}
