"""
BidderSubmission CRUD -- SIH26100 Phase 2.

get_owned_submission() is the shared ownership-check helper every other
Phase 2 submission-scoped endpoint (verification, summary, officer
decision) calls first -- a BidderSubmission has no company_id column of
its own (see app/models/sih/bidder.py), so ownership is resolved via its
Procurement, the same one-hop pattern
qualification_override_service._get_owned_requirement() already uses
for Requirement -> Tender -> Mission -> company_id.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.sih.bidder import Bidder, BidderSubmission
from app.models.sih.procurement import Procurement
from app.services.exceptions import ConflictError, NotFoundError
from app.services.sih import bidder_service, procurement_service


def create_submission(
    db: Session,
    procurement_id: uuid.UUID,
    bidder_id: uuid.UUID,
    company_id: uuid.UUID,
    bid_amount=None,
) -> BidderSubmission:
    # Both raise NotFoundError if not owned by this company -- a
    # submission can never be created linking a procurement/bidder that
    # doesn't belong to the caller's own company.
    procurement_service.get_procurement(db, procurement_id, company_id)
    bidder_service.get_bidder(db, bidder_id, company_id)

    existing = (
        db.query(BidderSubmission)
        .filter(BidderSubmission.procurement_id == procurement_id, BidderSubmission.bidder_id == bidder_id)
        .one_or_none()
    )
    if existing is not None:
        raise ConflictError(
            f"Bidder '{bidder_id}' already has a submission against procurement '{procurement_id}'."
        )

    submission = BidderSubmission(procurement_id=procurement_id, bidder_id=bidder_id, bid_amount=bid_amount)
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


def set_bid_amount(db: Session, submission_id: uuid.UUID, company_id: uuid.UUID, bid_amount) -> BidderSubmission:
    """
    Lets an officer enter/correct a submission's bid_amount after
    creation -- e.g. once the bid opening has actually happened. Never
    required; a submission with no bid_amount is simply excluded from
    value-based Collusion Radar heuristics (collusion_radar_service.py).
    """
    submission = get_owned_submission(db, submission_id, company_id)
    submission.bid_amount = bid_amount
    db.commit()
    db.refresh(submission)
    return submission


def list_submissions_for_procurement(
    db: Session, procurement_id: uuid.UUID, company_id: uuid.UUID
) -> list[BidderSubmission]:
    procurement_service.get_procurement(db, procurement_id, company_id)
    return (
        db.query(BidderSubmission)
        .filter(BidderSubmission.procurement_id == procurement_id)
        .order_by(BidderSubmission.created_at.desc())
        .all()
    )


def get_owned_submission(db: Session, submission_id: uuid.UUID, company_id: uuid.UUID) -> BidderSubmission:
    submission = db.get(BidderSubmission, submission_id)
    if submission is None:
        raise NotFoundError(f"BidderSubmission '{submission_id}' not found.")
    procurement = db.get(Procurement, submission.procurement_id)
    if procurement is None or procurement.company_id != company_id:
        raise NotFoundError(f"BidderSubmission '{submission_id}' not found.")
    return submission


def get_submission_bidder(db: Session, submission: BidderSubmission) -> Bidder:
    """Every submission has exactly one Bidder -- resolved fresh, never
    duplicated onto BidderSubmission itself (see create_submission's docstring)."""
    bidder = db.get(Bidder, submission.bidder_id)
    if bidder is None:
        raise NotFoundError(f"Bidder for submission '{submission.id}' not found.")
    return bidder
