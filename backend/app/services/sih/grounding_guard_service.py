"""
Evidence Grounding Guard -- SIH26100 minimal-real engine (Phase 1b of the
Requirement-to-Evidence / Grounding directive).

Formalizes, as an explicit, testable, reusable component, two invariants
that were previously enforced only implicitly/structurally across
verification_service.py and document_service.py:

  1. "Unconfirmed extraction can never become verification input." --
     already enforced structurally by
     document_service.build_verification_inputs_from_documents()'s
     `BidderDocument.is_confirmed.is_(True)` filter (see that function's
     own docstring). ensure_document_is_grounded() below re-asserts this
     defensively at the point of use -- defense in depth, not a second
     source of truth -- and is the seam any future caller that wants to
     treat a document's data as authoritative should go through, so a
     later addition can never silently bypass the confirmation gate the
     document pipeline already respects. document_service.py calls it
     inline before mapping each confirmed document (see the small
     addition there), which turns "was this ever accidentally skipped?"
     from a silent possibility into a raised, test-covered error.

  2. "A verification finding is never presented without a traceable
     origin." -- every VerificationResult already carries enough to
     answer "where did this come from?": either a source_document_id
     (an officer-confirmed document), or a populated declared_value with
     no source_document_id (an officer's manual entry via
     POST .../verify -- itself a traceable origin: which officer, and
     when, via checked_at/current_user), or neither (MISSING/
     NOT_CLAIMED -- an honest "we have nothing," never fabricated).
     get_grounding_report() below classifies every latest result into
     exactly one of these three buckets. It is what
     GET /sih/submissions/{id}/grounding and the officer-facing "Evidence
     Grounding" panel (BidderVerification.tsx) are built from.

This module never changes verification_service.verify_submission()'s
behavior or output -- it only *reports on and defends* an invariant that
was already there. It is deliberately NOT a RAG/self-reflection system
and never itself calls an LLM, per the governing brief.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.sih.document import BidderDocument
from app.services.sih import verification_service


class UngroundedEvidenceError(Exception):
    """
    Raised when code attempts to treat an unconfirmed (or otherwise
    non-authoritative) BidderDocument's extraction as verification
    input. Should never be raised by the normal document_service flow --
    a real occurrence means some code path tried to bypass the
    confirmation gate and must be fixed at that call site, not caught
    and swallowed here.
    """


def ensure_document_is_grounded(document: BidderDocument) -> None:
    """
    The one required check before any code treats a BidderDocument's
    extracted data as authoritative for verification. Raises
    UngroundedEvidenceError unless the document is_confirmed AND has
    confirmed_data -- i.e. an officer explicitly signed off on it (see
    document_service.confirm_document's docstring for what confirmation
    means and how confirmed_data differs from raw extracted_data).
    """
    if not document.is_confirmed or not document.confirmed_data:
        raise UngroundedEvidenceError(
            f"BidderDocument '{document.id}' has not been officer-confirmed "
            "(is_confirmed=False or confirmed_data is empty) and cannot be "
            "used as verification evidence. Only confirmed_data may ground a finding."
        )


@dataclass
class CategoryGrounding:
    category_code: str
    category_name: str
    status: str  # ComplianceVerificationStatus value of the latest result
    # "document_evidence": traces to an officer-confirmed BidderDocument.
    # "manual_declaration": an officer-entered declared_value with no
    #   document behind it (the manual-entry POST .../verify path).
    # "no_evidence": nothing declared for this category (MISSING/NOT_CLAIMED).
    origin: str
    source_document_id: uuid.UUID | None
    source_document_name: str | None


@dataclass
class GroundingReport:
    submission_id: uuid.UUID
    categories: list[CategoryGrounding]
    document_evidenced_count: int
    manual_declaration_count: int
    no_evidence_count: int


def get_grounding_report(db: Session, submission_id: uuid.UUID) -> GroundingReport:
    """
    Classifies every latest VerificationResult for this submission by
    where its declared_value actually came from -- purely a read over
    already-persisted VerificationResult rows
    (verification_service.get_latest_results()), never a second scoring
    or verification pass, and never invents an origin: a result with no
    declared_value and no source_document_id is honestly "no_evidence,"
    not silently omitted.
    """
    results = verification_service.get_latest_results(db, submission_id)
    categories: list[CategoryGrounding] = []
    for result in results:
        if result.source_document_id is not None:
            origin = "document_evidence"
        elif result.declared_value:
            origin = "manual_declaration"
        else:
            origin = "no_evidence"
        categories.append(
            CategoryGrounding(
                category_code=result.category.code,
                category_name=result.category.name,
                status=result.status.value,
                origin=origin,
                source_document_id=result.source_document_id,
                source_document_name=result.source_document.file_name if result.source_document else None,
            )
        )
    categories.sort(key=lambda c: c.category_code)
    return GroundingReport(
        submission_id=submission_id,
        categories=categories,
        document_evidenced_count=sum(1 for c in categories if c.origin == "document_evidence"),
        manual_declaration_count=sum(1 for c in categories if c.origin == "manual_declaration"),
        no_evidence_count=sum(1 for c in categories if c.origin == "no_evidence"),
    )
