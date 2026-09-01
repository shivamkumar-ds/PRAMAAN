"""
Procurement CRUD -- SIH26100 Phase 2. Company-scoped ownership checks
mirror mission_service.get_mission()'s pattern exactly (never leak
cross-tenant existence -- a Procurement belonging to another company
looks identical to a nonexistent one).
"""

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.sih.bidder import Bidder, BidderSubmission
from app.models.sih.officer_decision import OfficerDecision
from app.models.sih.procurement import Procurement
from app.services.exceptions import ConflictError, NotFoundError


def create_procurement(
    db: Session,
    company_id: uuid.UUID,
    *,
    title: str,
    organization: str | None = None,
    reference_number: str | None = None,
    category: str | None = None,
    closing_date: date | None = None,
) -> Procurement:
    procurement = Procurement(
        company_id=company_id,
        title=title,
        organization=organization,
        reference_number=reference_number,
        category=category,
        closing_date=closing_date,
    )
    db.add(procurement)
    db.commit()
    db.refresh(procurement)
    return procurement


def list_procurements(db: Session, company_id: uuid.UUID) -> list[Procurement]:
    return (
        db.query(Procurement)
        .filter(Procurement.company_id == company_id)
        .order_by(Procurement.created_at.desc())
        .all()
    )


def get_procurement(db: Session, procurement_id: uuid.UUID, company_id: uuid.UUID) -> Procurement:
    procurement = db.get(Procurement, procurement_id)
    if procurement is None or procurement.company_id != company_id:
        raise NotFoundError(f"Procurement '{procurement_id}' not found.")
    return procurement


def set_awarded_bidder(
    db: Session, procurement_id: uuid.UUID, company_id: uuid.UUID, bidder_id: uuid.UUID
) -> Procurement:
    """
    Records which Bidder won this Procurement -- see
    app/models/sih/procurement.py's Procurement.awarded_bidder_id
    docstring for why this is never inferred automatically. Two honest
    guards, both raising the same ConflictError family the rest of this
    package uses (never a silent no-op or a bare IntegrityError):

    1. The awarded bidder must actually have a BidderSubmission against
       this procurement -- awarding a bidder who never submitted would be
       a data-entry error, not a real award.
    2. At least one OfficerDecision must already be recorded against one
       of this procurement's submissions -- an award is the conclusion of
       a review process that produced at least one recorded decision, not
       a substitute for one. This mirrors the task brief's requirement
       that awarding is "settable by an officer only after decisions
       exist for that procurement."

    Company-scoped throughout: the procurement, the bidder, and every
    submission/decision consulted are all resolved through this same
    company_id, so an award can never reference or be inferred from
    another tenant's data.
    """
    procurement = get_procurement(db, procurement_id, company_id)

    bidder = db.get(Bidder, bidder_id)
    if bidder is None or bidder.company_id != company_id:
        raise NotFoundError(f"Bidder '{bidder_id}' not found.")

    has_submission = (
        db.query(BidderSubmission.id)
        .filter(BidderSubmission.procurement_id == procurement_id, BidderSubmission.bidder_id == bidder_id)
        .first()
    )
    if has_submission is None:
        raise ConflictError(
            f"Bidder '{bidder_id}' has no submission against procurement '{procurement_id}' and cannot be "
            "recorded as its awarded bidder."
        )

    has_decision = (
        db.query(OfficerDecision.id)
        .join(BidderSubmission, BidderSubmission.id == OfficerDecision.submission_id)
        .filter(BidderSubmission.procurement_id == procurement_id)
        .first()
    )
    if has_decision is None:
        raise ConflictError(
            f"Procurement '{procurement_id}' has no recorded officer decision yet -- an award can only be "
            "set after at least one submission has been reviewed and decided on."
        )

    procurement.awarded_bidder_id = bidder_id
    db.commit()
    db.refresh(procurement)
    return procurement
