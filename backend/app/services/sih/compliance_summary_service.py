"""
Compliance score + risk summary -- SIH26100 Phase 2.

Deterministic only -- no LLM involvement, applying the Phase 0 design
principle ("AI extracts/normalizes/explains; deterministic rules decide
registry/status/identifier compliance and the compliance score/risk
itself") directly to scoring. Computed live off persisted
VerificationResult rows via verification_service.get_latest_results()
-- never a second, independently-cached score -- the same
recompute-from-persisted-facts discipline app/agents/decision_engine.py
already uses for the existing bidder-side product (this module does not
import or modify decision_engine.py; it is a new, independent
calculation over the SIH domain).

FORMULA (Phase 2's smallest deterministic version -- not a finalized/
tunable scoring engine; risk_weight-driven refinement and any later
AI-assisted explanation layer are explicitly out of scope here):

1. Only ComplianceCategory rows that are currently active are ever
   counted (roadmap/inactive categories are invisible to scoring, never
   silently penalized).
2. Within the active set, NOT_APPLICABLE / NOT_CLAIMED results are
   excluded from both the numerator and denominator entirely -- a
   bidder who never claimed a benefit is not marked down for it.
3. compliance_score (0-100, matching the SIH26100 problem statement's
   own scale) = 100 * (sum of risk_weight over VERIFIED results) /
   (sum of risk_weight over every counted result), rounded to 1 decimal.
   An empty counted set scores 0.0, not a divide-by-zero.
4. risk_level is a strict veto hierarchy, evaluated in this exact order
   and completely independent of the numeric score above -- a high
   compliance_score can never soften a CRITICAL finding:
     - "critical": any counted result is CRITICAL_FAIL (e.g. an active
       debarment, or a PAN mismatch). Per the Phase 0 report: a
       95/100 blacklisted bidder must never read as safe.
     - "high": no CRITICAL_FAIL, but at least one MANDATORY category is
       MISSING or MISMATCH.
     - "medium": no CRITICAL_FAIL and no mandatory MISSING/MISMATCH, but
       at least one non-mandatory category is MISMATCH.
     - "low": every counted category is VERIFIED.
5. critical_categories always lists the human-readable names behind a
   "critical" verdict, so the officer never has to infer why from the
   score alone.

Phase 1's ComplianceVerificationStatus has no separate "needs review"
state distinct from MISMATCH -- every MISMATCH is, by definition, an
item where the bidder's declaration and the registry disagree, which is
exactly what needs officer review. review_count is therefore reported
as the same count as failed_count (documented here rather than invented
as a fake, separately-tracked bucket that doesn't exist in the data).
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.sih.compliance import ComplianceCategory
from app.models.sih.enums import ComplianceVerificationStatus
from app.services.sih import verification_service


@dataclass
class MandatoryComplianceIssue:
    """
    One unresolved MANDATORY category -- the officer-facing "you cannot
    miss this" list. Deliberately a strict subset of what already drives
    risk_level="high" (see mandatory_unresolved below): this dataclass
    adds no new decision logic, it just names the specific categories
    that logic was already reacting to, so the UI can list them instead
    of only reporting the aggregate risk_level.
    """

    category_code: str
    category_name: str
    status: ComplianceVerificationStatus
    reason: str | None
    source_document_id: uuid.UUID | None
    source_document_name: str | None


@dataclass
class ComplianceSummary:
    total_applicable: int
    verified_count: int
    failed_count: int
    missing_count: int
    critical_count: int
    review_count: int
    compliance_score: float
    risk_level: str
    critical_categories: list[str] = field(default_factory=list)
    # Every MANDATORY category currently MISSING or MISMATCH -- the exact
    # set that drives risk_level="high" below, named individually so the
    # officer decision view can surface each one rather than just the
    # aggregate risk label. Empty when every mandatory category is
    # resolved (VERIFIED/NOT_APPLICABLE/NOT_CLAIMED).
    mandatory_issues: list[MandatoryComplianceIssue] = field(default_factory=list)


def get_compliance_summary(db: Session, submission_id: uuid.UUID) -> ComplianceSummary:
    results = verification_service.get_latest_results(db, submission_id)
    counted = [
        r
        for r in results
        if r.status
        not in (ComplianceVerificationStatus.NOT_APPLICABLE, ComplianceVerificationStatus.NOT_CLAIMED)
    ]

    category_ids = {r.category_id for r in counted}
    categories_by_id: dict[uuid.UUID, ComplianceCategory] = (
        {c.id: c for c in db.query(ComplianceCategory).filter(ComplianceCategory.id.in_(category_ids)).all()}
        if category_ids
        else {}
    )

    verified = [r for r in counted if r.status == ComplianceVerificationStatus.VERIFIED]
    critical = [r for r in counted if r.status == ComplianceVerificationStatus.CRITICAL_FAIL]
    missing = [r for r in counted if r.status == ComplianceVerificationStatus.MISSING]
    mismatch = [r for r in counted if r.status == ComplianceVerificationStatus.MISMATCH]

    total_weight = sum(categories_by_id[r.category_id].risk_weight for r in counted)
    verified_weight = sum(categories_by_id[r.category_id].risk_weight for r in verified)
    compliance_score = round((verified_weight / total_weight) * 100, 1) if total_weight > 0 else 0.0

    mandatory_unresolved = [
        r for r in (missing + mismatch) if categories_by_id[r.category_id].mandatory_by_default
    ]
    non_mandatory_mismatch = [r for r in mismatch if not categories_by_id[r.category_id].mandatory_by_default]

    if critical:
        risk_level = "critical"
    elif mandatory_unresolved:
        risk_level = "high"
    elif non_mandatory_mismatch:
        risk_level = "medium"
    else:
        risk_level = "low"

    return ComplianceSummary(
        total_applicable=len(counted),
        verified_count=len(verified),
        failed_count=len(mismatch),
        missing_count=len(missing),
        critical_count=len(critical),
        review_count=len(mismatch),
        compliance_score=compliance_score,
        risk_level=risk_level,
        critical_categories=[categories_by_id[r.category_id].name for r in critical],
        mandatory_issues=[
            MandatoryComplianceIssue(
                category_code=categories_by_id[r.category_id].code,
                category_name=categories_by_id[r.category_id].name,
                status=r.status,
                reason=r.reason,
                source_document_id=r.source_document_id,
                source_document_name=r.source_document.file_name if r.source_document else None,
            )
            for r in mandatory_unresolved
        ],
    )
