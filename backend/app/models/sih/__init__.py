"""
SIH26100 -- Bidder Verification domain models.

A new, independent sibling domain alongside BidOps' existing bidder-side
self-assessment product (Tender/Requirement/Capability -- unchanged, not
touched by anything in this package). SIH26100 is the opposite actor: a
Procurement Officer verifying a third-party Bidder's claims against
government registries, not a bidder assessing its own readiness. See the
Phase 0 inspection report for the full architecture reasoning behind
keeping this a sibling domain rather than reusing Tender/Requirement.

Importing this package registers every SIH model with Base.metadata --
same convention as app/models/__init__.py itself, which imports from
here so Alembic autogenerate / app startup see the full schema, existing
and SIH combined.
"""

from app.models.sih.bidder import Bidder, BidderSubmission
from app.models.sih.compliance import ComplianceCategory, RegistryRecord, VerificationResult
from app.models.sih.document import AuthenticityScan, BidderDocument
from app.models.sih.officer_decision import OfficerDecision
from app.models.sih.procurement import Procurement
from app.models.sih.procurement_document import ProcurementDocument
from app.models.sih.procurement_requirement import ProcurementRequirement

__all__ = [
    "Procurement",
    "Bidder",
    "BidderSubmission",
    "ComplianceCategory",
    "RegistryRecord",
    "VerificationResult",
    "OfficerDecision",
    "BidderDocument",
    "AuthenticityScan",
    "ProcurementDocument",
    "ProcurementRequirement",
]
