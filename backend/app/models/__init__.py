"""
Importing this package registers every model with Base.metadata.

Anything that needs the full schema (Alembic autogenerate, app startup)
must import app.models, not an individual model module, or tables will
be silently missing from what SQLAlchemy knows about.
"""

from app.models.audit import AuditLog
from app.models.bid_readiness import BidReadinessConfirmation
from app.models.capability import Certification, Employee, Equipment, FinancialRecord, Project
from app.models.company import Company, User
from app.models.contact import ContactSubmission
from app.models.document import Document
from app.models.mission import CapabilitySnapshot, Mission
from app.models.qualification_override import QualificationOverride
from app.models.recommendation import ComplianceMatrix, Recommendation
from app.models.telemetry import LLMCallEvent
from app.models.tender import CapabilityMapping, Requirement, Tender

# SIH26100 -- Bidder Verification, a new independent sibling domain (see
# app/models/sih/__init__.py). Imported here, same as every other model
# module, so Alembic autogenerate / app startup see these tables too.
# Does not touch, extend, or depend on anything above this line.
from app.models.sih import (
    Bidder,
    BidderDocument,
    BidderSubmission,
    ComplianceCategory,
    OfficerDecision,
    Procurement,
    RegistryRecord,
    VerificationResult,
)

__all__ = [
    "AuditLog",
    "BidReadinessConfirmation",
    "Certification",
    "Employee",
    "Equipment",
    "FinancialRecord",
    "Project",
    "Company",
    "User",
    "ContactSubmission",
    "Document",
    "CapabilitySnapshot",
    "Mission",
    "QualificationOverride",
    "ComplianceMatrix",
    "Recommendation",
    "LLMCallEvent",
    "CapabilityMapping",
    "Requirement",
    "Tender",
    "Procurement",
    "Bidder",
    "BidderSubmission",
    "ComplianceCategory",
    "RegistryRecord",
    "VerificationResult",
    "OfficerDecision",
    "BidderDocument",
]
