"""
Bidder verification orchestration -- SIH26100 Phase 1.

Deliberately thin: Phase 1 has no document-extraction/OCR pipeline yet
(explicitly deferred to a later phase), so `declared_facts_by_category`
is supplied directly by the caller (a seed/test harness today) rather
than derived from an uploaded document. This module's job is only to run
the deterministic registry adapters and persist the result, insert-only
-- mirroring decision_service.run_evaluation()'s "only write once every
result is known" pattern (see app/models/sih/compliance.py's
VerificationResult docstring).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.sih.bidder import BidderSubmission
from app.models.sih.compliance import ComplianceCategory, VerificationResult
from app.models.sih.enums import ComplianceVerificationStatus
from app.services.exceptions import NotFoundError
from app.services.sih.registry_adapters import get_adapter


def verify_submission(
    db: Session,
    submission_id: uuid.UUID,
    bidder_identity: dict,
    declared_facts_by_category: dict[str, dict],
    source_document_by_category: dict[str, uuid.UUID] | None = None,
) -> list[VerificationResult]:
    """
    Runs every active ComplianceCategory's adapter against this
    submission's declared facts, and inserts one fresh VerificationResult
    row per category. A category the bidder declared nothing for is
    recorded as MISSING (if mandatory_by_default) or NOT_CLAIMED (if
    not) -- never silently skipped, so "we never checked this" and "we
    checked and it's missing" are never conflated.

    source_document_by_category is optional (Phase 5, additive, default
    None so every pre-existing caller/test is unaffected) -- when the
    caller is app/services/sih/document_service's document-driven path,
    it records which confirmed BidderDocument each category's declared
    facts came from, purely for officer-facing evidence linking. The
    adapters themselves never see or use it; it changes no verification
    logic or outcome, only what's persisted alongside the result.
    """
    submission = db.get(BidderSubmission, submission_id)
    if submission is None:
        raise NotFoundError(f"BidderSubmission '{submission_id}' not found.")

    categories = db.query(ComplianceCategory).filter(ComplianceCategory.is_active.is_(True)).all()
    results: list[VerificationResult] = []
    source_document_by_category = source_document_by_category or {}

    for category in categories:
        declared = declared_facts_by_category.get(category.code)

        if declared is None:
            status = (
                ComplianceVerificationStatus.MISSING
                if category.mandatory_by_default
                else ComplianceVerificationStatus.NOT_CLAIMED
            )
            result = VerificationResult(
                submission_id=submission_id,
                category_id=category.id,
                status=status,
                declared_value=None,
                registry_value=None,
                discrepancies=[],
                source="N/A -- nothing declared",
                reason=(
                    "Bidder did not declare anything for this category."
                    if status == ComplianceVerificationStatus.NOT_CLAIMED
                    else "Mandatory category was not declared by the bidder."
                ),
                checked_at=datetime.now(timezone.utc),
            )
            db.add(result)
            results.append(result)
            continue

        adapter = get_adapter(category.adapter_key)
        outcome = adapter.verify(db, bidder_identity, declared)
        source_document_id = source_document_by_category.get(category.code)
        # Confidence (additive metadata only -- never changes status/PASS-
        # FAIL logic above): 1.0 when this category's declared facts came
        # from an officer-CONFIRMED BidderDocument (grounding_guard_
        # service's "document_evidence" origin), 0.5 when they came only
        # from a manual declared_facts entry with no document behind it
        # ("manual_declaration"). outcome.confidence (the adapter's own,
        # currently-unused identity-resolution confidence -- see
        # ComplianceCategory/VerificationResult's docstrings) is
        # deliberately not consulted here: no adapter populates it today,
        # and if one later does, that would be a genuinely different
        # signal (match confidence) from this one (evidence-origin
        # confidence) -- conflating them would silently change what this
        # field means for existing callers.
        confidence = 1.0 if source_document_id is not None else 0.5
        result = VerificationResult(
            submission_id=submission_id,
            category_id=category.id,
            status=outcome.status,
            declared_value=declared,
            registry_value=outcome.registry_value,
            discrepancies=outcome.discrepancies,
            confidence=confidence,
            source=outcome.source,
            reason=outcome.reason,
            checked_at=outcome.checked_at,
            source_document_id=source_document_id,
        )
        db.add(result)
        results.append(result)

    db.commit()
    for result in results:
        db.refresh(result)
    return results


def get_latest_results(db: Session, submission_id: uuid.UUID) -> list[VerificationResult]:
    """
    One row per category -- the most recent VerificationResult for each
    (submission, category) pair, since verify_submission() is
    insert-only and a submission may have been re-verified more than
    once.
    """
    all_results = (
        db.query(VerificationResult)
        .filter(VerificationResult.submission_id == submission_id)
        .order_by(VerificationResult.checked_at.desc())
        .all()
    )
    latest_by_category: dict[uuid.UUID, VerificationResult] = {}
    for result in all_results:
        if result.category_id not in latest_by_category:
            latest_by_category[result.category_id] = result
    return list(latest_by_category.values())
