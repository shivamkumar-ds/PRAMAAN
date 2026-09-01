"""
SIH26100 -- Bidder Verification domain enums.

Deliberately a separate module from app/models/enums.py: this whole
package is a new, independent sibling domain, not an extension of
BidOps' existing Tender/Requirement/Capability vocabulary. See
app/models/sih/__init__.py and the Phase 0 inspection report.

Enum column values are serialized by member NAME (uppercase), not
member value -- same convention as every existing enum in
app/models/enums.py, and the same lesson Bug #005 (docs/BUG_BUCKET.md)
already paid for once (the auth_provider enum was created with lowercase
Postgres labels while SQLAlchemy's Enum(SomePythonEnum) column type
serializes via member.name). The Alembic migration for this package
creates each Postgres ENUM type with uppercase labels matching these
member names exactly -- see
alembic/versions/<this_migration>_add_sih_bidder_verification_domain.py.
"""

import enum


class ProcurementStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    ARCHIVED = "archived"


class SubmissionStatus(str, enum.Enum):
    """Lifecycle of one Bidder's submission against one Procurement."""

    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    DECIDED = "decided"


class ComplianceVerificationStatus(str, enum.Enum):
    """
    The verdict for one (BidderSubmission, ComplianceCategory) check --
    deliberately a richer vocabulary than BidOps' MatchStatus, because
    the SIH UI needs to distinguish "the bidder never claimed this"
    (neutral, not a red mark) and "a critical, non-negotiable failure"
    (e.g. blacklist=true, PAN mismatch) from an ordinary mismatch/missing
    item. CRITICAL_FAIL is the one status that must always force a
    submission's overall risk to the highest tier regardless of the
    numeric compliance score -- see the Phase 0 report's score/risk
    architecture proposal (a later phase; not computed anywhere yet).
    """

    VERIFIED = "verified"
    MISMATCH = "mismatch"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    NOT_CLAIMED = "not_claimed"
    CRITICAL_FAIL = "critical_fail"


class DocumentExtractionStatus(str, enum.Enum):
    """
    Lifecycle of one BidderDocument's AI extraction (Phase 4) -- a
    distinct, richer vocabulary from app.models.enums.DocumentProcessingStatus
    (PENDING/PROCESSING/COMPLETED/FAILED) because a SIH bidder document has
    a state that domain doesn't: REVIEW_REQUIRED, for a document whose
    compliance category could not be confidently determined (see
    app/agents/sih_document_extractor.py's classify_document()) -- the
    system must never silently guess and file it under the wrong
    category. A new, separate enum rather than extending the existing one,
    so nothing about the existing Document/capability-extraction pipeline
    changes.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


class ProcurementDocumentExtractionStatus(str, enum.Enum):
    """
    Lifecycle of one ProcurementDocument's AI extraction (Requirement-to-
    Evidence Mapping engine) -- deliberately a narrower vocabulary than
    DocumentExtractionStatus (no PROCESSING, no REVIEW_REQUIRED): a
    ProcurementDocument is never classified into a compliance category
    the way a BidderDocument is (there's nothing to classify -- it's the
    officer's own tender, not third-party evidence for one specific
    category), and upload_and_extract() runs extraction synchronously
    inline with the upload request rather than as a separately-triggered
    step, so there is no meaningfully observable PROCESSING window to
    persist. PENDING exists only as the row's initial value before the
    synchronous extraction call completes (or, if the request handler
    ever changes to run extraction out-of-band later, as the state
    between upload and that later run).
    """

    PENDING = "pending"
    EXTRACTED = "extracted"
    FAILED = "failed"


class OfficerDecisionType(str, enum.Enum):
    """
    The Procurement Officer's final call on one BidderSubmission --
    deliberately a 3-way vocabulary, not a 2-state override like
    QualificationOverride. REQUEST_CLARIFICATION is a real, distinct
    outcome (the officer needs more information before deciding), not a
    variant of REJECT.
    """

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CLARIFICATION = "request_clarification"
