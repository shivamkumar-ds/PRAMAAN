"""
Bidder CRUD -- SIH26100 Phase 2. A Bidder is deliberately independent of
any Procurement (see app/models/sih/bidder.py's docstring) -- its own
GST/Udyam/PAN identity is meant to be created once and reused across
multiple BidderSubmission rows against different Procurements.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.sih.bidder import Bidder
from app.services.exceptions import NotFoundError


def create_bidder(
    db: Session,
    company_id: uuid.UUID,
    *,
    legal_name: str,
    trade_name: str | None = None,
    pan: str | None = None,
    registered_address: str | None = None,
    director_name: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
) -> Bidder:
    bidder = Bidder(
        company_id=company_id,
        legal_name=legal_name,
        trade_name=trade_name,
        pan=pan,
        registered_address=registered_address,
        director_name=director_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
    )
    db.add(bidder)
    db.commit()
    db.refresh(bidder)
    return bidder


def list_bidders(db: Session, company_id: uuid.UUID) -> list[Bidder]:
    return db.query(Bidder).filter(Bidder.company_id == company_id).order_by(Bidder.created_at.desc()).all()


def get_bidder(db: Session, bidder_id: uuid.UUID, company_id: uuid.UUID) -> Bidder:
    bidder = db.get(Bidder, bidder_id)
    if bidder is None or bidder.company_id != company_id:
        raise NotFoundError(f"Bidder '{bidder_id}' not found.")
    return bidder


# Every field a caller may update -- deliberately whitelisted rather than
# setattr-everything, same defensive pattern as the rest of this domain
# (e.g. document_service.set_document_category only ever touches named
# columns). update_bidder(**fields) only applies keys that were actually
# provided by the caller (see schemas.sih.BidderUpdateRequest, which
# excludes unset fields via model_dump(exclude_unset=True)) -- a field
# left out of the request is never overwritten with None.
_UPDATABLE_FIELDS = (
    "legal_name",
    "trade_name",
    "pan",
    "registered_address",
    "director_name",
    "contact_email",
    "contact_phone",
)


def update_bidder(db: Session, bidder_id: uuid.UUID, company_id: uuid.UUID, **fields) -> Bidder:
    bidder = get_bidder(db, bidder_id, company_id)
    for key, value in fields.items():
        if key in _UPDATABLE_FIELDS:
            setattr(bidder, key, value)
    db.commit()
    db.refresh(bidder)
    return bidder
