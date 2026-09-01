"""
Decision Intelligence API.

Two routers, matching 06_API_Design.md's two separate top-level paths
(/evaluation/... and /recommendations/...) — both describe nearly the
same response bundle under different names (a genuine doc ambiguity,
flagged during the implementation strategy and left unresolved rather
than guessed at). Both are implemented, backed by the same underlying
assembly function, since both are in the frozen, approved spec.
"""

import uuid

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents import decision_engine
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models import User
from app.schemas.decision import (
    ComplianceMatrixEntryRead,
    EvaluationResponse,
    GapAnalysisEntry,
    RecommendationRead,
    RemediationSummary,
)
from app.services import bid_readiness_service, decision_service, qualification_override_service

evaluation_router = APIRouter(prefix="/evaluation", tags=["evaluation"])
recommendations_router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class RunEvaluationRequest(BaseModel):
    mission_id: uuid.UUID


def _build_response(db: Session, recommendation, compliance_rows, requirements_by_id) -> EvaluationResponse:
    # Evidence trail resolution (DESIGN_SYSTEM.md §10: Recommendation ->
    # Evidence -> Source Clause -> Company Document) — source_page comes
    # from the already-fetched Requirement, evidence_source is resolved
    # via decision_service.resolve_evidence_sources(). Both are attached
    # with model_copy(update=...) rather than passed into model_validate(),
    # since neither lives on the ComplianceMatrix ORM row itself.
    evidence_sources = decision_service.resolve_evidence_sources(db, compliance_rows)
    verifier_names = decision_service.resolve_verifier_names(db, compliance_rows)
    compliance_matrix = [
        ComplianceMatrixEntryRead.model_validate(row).model_copy(
            update={
                "source_page": requirements_by_id[row.requirement_id].source_page,
                "evidence_source": evidence_sources.get(row.evidence_reference),
                "verified_by_name": verifier_names.get(row.verified_by),
            }
        )
        for row in compliance_rows
    ]

    # Bid-readiness confirmation feature: fetched once here and threaded
    # through both `gap_analysis` and `remediation_summary` below, so a
    # confirmed item's confirmed/confirmed_at fields are populated
    # identically in both places rather than only one. Keyed by
    # requirement_id — see bid_readiness_service.get_confirmations_by_requirement_id().
    confirmations = bid_readiness_service.get_confirmations_by_requirement_id(
        db, list(requirements_by_id.keys())
    )
    confirmed_requirement_ids = frozenset(confirmations.keys())

    # Qualification override feature: same fetch-once-thread-everywhere
    # shape as confirmations above, so an overridden item's overridden/
    # overridden_by/overridden_at/override_note fields are populated
    # identically in gap_analysis and remediation_summary rather than
    # only one. Keyed by requirement_id — see
    # qualification_override_service.get_overrides_by_requirement_id().
    overrides = qualification_override_service.get_overrides_by_requirement_id(
        db, list(requirements_by_id.keys())
    )
    overridden_requirement_ids = frozenset(overrides.keys())
    overrider_names = qualification_override_service.resolve_overrider_names(db, list(overrides.values()))

    gap_analysis = [
        GapAnalysisEntry(
            requirement_id=row.requirement_id,
            requirement_type=requirements_by_id[row.requirement_id].requirement_type,
            description=requirements_by_id[row.requirement_id].description,
            mandatory=requirements_by_id[row.requirement_id].mandatory,
            status=row.status,
            reason=row.verification_reason or row.notes,
            source_page=requirements_by_id[row.requirement_id].source_page,
            confirmed=row.requirement_id in confirmed_requirement_ids,
            confirmed_at=confirmations[row.requirement_id].confirmed_at
            if row.requirement_id in confirmations
            else None,
            overridden=row.requirement_id in overridden_requirement_ids,
            overridden_by=overrides[row.requirement_id].overridden_by
            if row.requirement_id in overrides
            else None,
            overridden_by_name=overrider_names.get(overrides[row.requirement_id].overridden_by)
            if row.requirement_id in overrides
            else None,
            overridden_at=overrides[row.requirement_id].overridden_at
            if row.requirement_id in overrides
            else None,
            override_note=overrides[row.requirement_id].note if row.requirement_id in overrides else None,
        )
        for row in compliance_rows
        if row.status.value != "met"
    ]

    # Architecture debate Phase 5: one deterministic classification, built
    # from reconstructed MatchResult-equivalents (decision_service.
    # build_remediation_results — exact reconstruction, see its and
    # decision_engine.reconstruct_match_result()'s docstrings) and the
    # same decision_engine.compute_qualification()/compute_bid_readiness()
    # functions that already produced `recommendation.recommendation_type`.
    # No independent re-derivation of qualification/readiness logic here —
    # see decision_engine.classify_remediation()'s docstring for the exact
    # per-item bucketing rules. confirmed_requirement_ids is forwarded only
    # as far as classify_remediation()/compute_bid_readiness() themselves
    # forward it (never into compute_qualification()) — see the boundary
    # rule in both docstrings.
    remediation_results = decision_service.build_remediation_results(compliance_rows, requirements_by_id)
    classification = decision_engine.classify_remediation(
        remediation_results, confirmed_requirement_ids, overridden_requirement_ids
    )

    # Bug fix: `recommendation` below is the PERSISTED Recommendation row
    # from the last actual POST /evaluation/run — its recommendation_type
    # was frozen at run time, before any confirmation existed, and a
    # confirm/unconfirm action never re-runs evaluation (deliberately —
    # see run_evaluation()'s own rate-limit comment: matching is
    # expensive/LLM-driven and must not fire on a cheap confirm click).
    # So the persisted recommendation_type can go stale relative to
    # remediation_summary (which IS correctly recomputed live above via
    # classify_remediation()). Fix: recompute recommendation_type live,
    # the same way, from the same remediation_results +
    # confirmed_requirement_ids already assembled here, and override it
    # on the response object only — never written back to the `recommendations`
    # table, preserving the insert-only history design (Recommendation/
    # ComplianceMatrix rows are never updated, only ever inserted fresh by
    # POST /evaluation/run).
    live_recommendation_type = decision_engine.compute_recommendation_type(
        remediation_results, confirmed_requirement_ids, overridden_requirement_ids
    )

    remediation_summary = RemediationSummary(
        qualification=classification.qualification,
        qualification_gaps=[
            _to_gap_entry(r, requirements_by_id, confirmations, overrides, overrider_names)
            for r in classification.qualification_gaps
        ],
        bid_readiness=classification.bid_readiness,
        blocked_items=[
            _to_gap_entry(r, requirements_by_id, confirmations, overrides, overrider_names)
            for r in classification.blocked_items
        ],
        action_required_items=[
            _to_gap_entry(r, requirements_by_id, confirmations, overrides, overrider_names)
            for r in classification.action_required_items
        ],
        coverage_gaps=[
            _to_gap_entry(r, requirements_by_id, confirmations, overrides, overrider_names)
            for r in classification.coverage_gaps
        ],
        human_review_items=[
            _to_gap_entry(r, requirements_by_id, confirmations, overrides, overrider_names)
            for r in classification.human_review_items
        ],
        optional_capability_gaps=[
            _to_gap_entry(r, requirements_by_id, confirmations, overrides, overrider_names)
            for r in classification.optional_capability_gaps
        ],
    )

    return EvaluationResponse(
        recommendation=RecommendationRead.model_validate(recommendation).model_copy(
            update={"recommendation_type": live_recommendation_type}
        ),
        compliance_matrix=compliance_matrix,
        gap_analysis=gap_analysis,
        remediation_summary=remediation_summary,
    )


def _to_gap_entry(
    result: decision_engine.MatchResult,
    requirements_by_id: dict,
    confirmations: dict,
    overrides: dict,
    overrider_names: dict,
) -> GapAnalysisEntry:
    """Shared MatchResult -> GapAnalysisEntry conversion for every
    remediation_summary bucket — one place, so requirement_nature/
    unsupported_domains/confirmed/overridden state are populated
    identically everywhere rather than risking a second, slightly-
    different conversion per bucket. `confirmations`/`overrides` are
    keyed by requirement_id — an item stays visible in its existing
    bucket whether or not it's confirmed/overridden (see
    classify_remediation()'s docstring); this only attaches the
    display-facing fields."""
    requirement = requirements_by_id[result.requirement_id]
    confirmation = confirmations.get(result.requirement_id)
    override = overrides.get(result.requirement_id)
    return GapAnalysisEntry(
        requirement_id=result.requirement_id,
        requirement_type=requirement.requirement_type,
        description=requirement.description,
        mandatory=requirement.mandatory,
        status=result.status,
        reason=result.notes,
        source_page=requirement.source_page,
        requirement_nature=result.requirement_nature,
        unsupported_domains=sorted(result.unsupported_domains, key=lambda d: d.value),
        confirmed=confirmation is not None,
        confirmed_at=confirmation.confirmed_at if confirmation is not None else None,
        overridden=override is not None,
        overridden_by=override.overridden_by if override is not None else None,
        overridden_by_name=overrider_names.get(override.overridden_by) if override is not None else None,
        overridden_at=override.overridden_at if override is not None else None,
        override_note=override.note if override is not None else None,
    )


# 10/minute per IP (RC-2 finding H-2) — one call here is up to N sequential/
# parallelized LLM requests (one per tender requirement), the single most
# expensive endpoint in the product per invocation.
@evaluation_router.post("/run", response_model=EvaluationResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def run_evaluation(
    request: Request,
    payload: RunEvaluationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EvaluationResponse:
    await decision_service.run_evaluation(db, payload.mission_id, current_user.company_id)
    recommendation, compliance_rows, requirements_by_id = decision_service.get_evaluation_bundle(
        db, payload.mission_id, current_user.company_id
    )

    return _build_response(db, recommendation, compliance_rows, requirements_by_id)


@evaluation_router.get("/{mission_id}", response_model=EvaluationResponse)
def get_evaluation(
    mission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EvaluationResponse:
    recommendation, compliance_rows, requirements_by_id = decision_service.get_evaluation_bundle(
        db, mission_id, current_user.company_id
    )
    return _build_response(db, recommendation, compliance_rows, requirements_by_id)


@recommendations_router.get("/{mission_id}", response_model=EvaluationResponse)
def get_recommendation(
    mission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EvaluationResponse:
    # Same assembly as GET /evaluation/{mission_id} — see module docstring.
    recommendation, compliance_rows, requirements_by_id = decision_service.get_evaluation_bundle(
        db, mission_id, current_user.company_id
    )
    return _build_response(db, recommendation, compliance_rows, requirements_by_id)
