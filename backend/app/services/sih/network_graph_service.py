"""
Bidder Network Graph -- SIH26100 minimal-real engine (Phase 3 of the
governing directive).

SQLAlchemy-only, over the existing sih_bidders table -- no Neo4j, no
graph database, no new persisted table. A "relationship" here is exactly
what the brief asked for: two Bidder rows (within the same company/
tenant -- multi-tenant isolation is never crossed) that share a real,
non-null identifier -- registered_address, director_name, contact_email,
or contact_phone (added alongside this engine; see
app/models/sih/bidder.py). A bidder with none of these fields filled in
simply has no relationships to find -- nothing here is inferred or
fabricated from absent data.

This is computed live on every call (same "recompute from persisted
facts" discipline as compliance_summary_service.py), never cached --
Bidder rows can be edited, and a stale graph would be worse than a
slightly slower one.

Explicitly descriptive, never accusatory: the result is "these bidders
share this identifier," never "these bidders are colluding" or any
other judgment. An officer decides what a shared identifier means for
their own review -- see also collusion_radar_service.py, which is a
separate, procurement-scoped engine and deliberately does not reuse this
module's bidder-level comparisons directly (different question: "does
this bidder look connected to another bidder" vs. "does this specific
procurement's bid pattern look coordinated").
"""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.sih.bidder import Bidder
from app.services.sih import bidder_service

# (field attribute name, human-readable label) -- the four dimensions a
# relationship can be found on. Order matters only for stable output.
_RELATIONSHIP_FIELDS: tuple[tuple[str, str], ...] = (
    ("director_name", "Shared director"),
    ("registered_address", "Shared registered address"),
    ("contact_email", "Shared contact email"),
    ("contact_phone", "Shared contact phone"),
)


def _normalize(value: str | None, *, digits_only: bool = False) -> str | None:
    """Deliberately conservative normalization -- lowercase + collapsed
    whitespace (and digit-only comparison for phone numbers, so
    '+91 98765-43210' and '9876543210' still match). Never fuzzy-matches
    across genuinely different values -- a network graph making false
    connections would be worse than missing a real one in this prototype."""
    if not value or not value.strip():
        return None
    if digits_only:
        digits = re.sub(r"\D", "", value)
        return digits or None
    return re.sub(r"\s+", " ", value.strip().lower())


@dataclass
class RelatedBidder:
    bidder_id: uuid.UUID
    legal_name: str
    trade_name: str | None
    reasons: list[str]


@dataclass
class NetworkGraphReport:
    bidder_id: uuid.UUID
    bidder_legal_name: str
    related_bidders: list[RelatedBidder]


def get_related_bidders(db: Session, bidder_id: uuid.UUID, company_id: uuid.UUID) -> NetworkGraphReport:
    """
    Finds every other Bidder in the same company/tenant that shares at
    least one non-null identifier with this bidder, and why. Tenant
    isolation is enforced the same way as everywhere else in this
    domain -- bidder_service.get_bidder raises NotFoundError on a
    cross-tenant id, and every candidate is filtered to the same
    company_id.
    """
    subject = bidder_service.get_bidder(db, bidder_id, company_id)

    subject_values: dict[str, str | None] = {
        field: _normalize(getattr(subject, field), digits_only=(field == "contact_phone"))
        for field, _label in _RELATIONSHIP_FIELDS
    }
    if not any(subject_values.values()):
        # No identifiers on file for this bidder at all -- honestly
        # nothing to compare, not an error, not a fabricated "no
        # relationships found after analysis."
        return NetworkGraphReport(bidder_id=bidder_id, bidder_legal_name=subject.legal_name, related_bidders=[])

    candidates = (
        db.query(Bidder)
        .filter(Bidder.company_id == company_id, Bidder.id != bidder_id)
        .all()
    )

    related: list[RelatedBidder] = []
    for candidate in candidates:
        reasons: list[str] = []
        for field, label in _RELATIONSHIP_FIELDS:
            subject_value = subject_values[field]
            if subject_value is None:
                continue
            candidate_value = _normalize(getattr(candidate, field), digits_only=(field == "contact_phone"))
            if candidate_value is not None and candidate_value == subject_value:
                raw_value = getattr(candidate, field)
                reasons.append(f"{label}: {raw_value}")
        if reasons:
            related.append(
                RelatedBidder(
                    bidder_id=candidate.id,
                    legal_name=candidate.legal_name,
                    trade_name=candidate.trade_name,
                    reasons=reasons,
                )
            )

    related.sort(key=lambda r: r.legal_name)
    return NetworkGraphReport(bidder_id=bidder_id, bidder_legal_name=subject.legal_name, related_bidders=related)
