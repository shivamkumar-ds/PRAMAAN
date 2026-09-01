"""
Missions API.

GET/DELETE fill genuine gaps in 06_API_Design.md's Mission section
(never built until now). POST .../execute is a new endpoint — nothing
in the frozen doc names an execution trigger, same precedent as
/auth/register in M1.
"""

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_administrator
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models import Document, Mission, Tender, User
from app.schemas.bid_readiness import BidReadinessConfirmationRead, ConfirmRequirementRequest
from app.schemas.decision import RecommendationRead
from app.schemas.mission import ExecuteMissionRequest, MissionRead
from app.schemas.qualification_override import OverrideRequirementRequest, QualificationOverrideRead
from app.services import bid_readiness_service, decision_service, mission_service, qualification_override_service

router = APIRouter(prefix="/missions", tags=["missions"])


def _attach_tender_info(db: Session, missions: list[Mission]) -> list[MissionRead]:
    """Enrich MissionRead with the real tender identity (see MissionRead's
    tender_id/tender_name comment). One batched query for both Tender and
    Document, regardless of how many missions are being listed, to avoid
    N+1 queries on the Dashboard/Tender Workspace list views."""
    if not missions:
        return []

    mission_ids = [m.id for m in missions]
    tenders = db.query(Tender).filter(Tender.mission_id.in_(mission_ids)).all()
    tender_by_mission = {t.mission_id: t for t in tenders}

    doc_ids = [t.uploaded_document for t in tenders if t.uploaded_document]
    doc_by_id = {}
    if doc_ids:
        doc_by_id = {d.id: d for d in db.query(Document).filter(Document.id.in_(doc_ids)).all()}

    results = []
    for mission in missions:
        read = MissionRead.model_validate(mission)
        tender = tender_by_mission.get(mission.id)
        if tender is not None:
            read.tender_id = tender.id
            document = doc_by_id.get(tender.uploaded_document) if tender.uploaded_document else None
            # Prefer the name the user actually typed at upload; fall back
            # to the real uploaded file name -- never mission_type, which
            # is always the same fixed constant, not a tender identifier.
            read.tender_name = tender.tender_name or (document.file_name if document else None)
        results.append(read)
    return results


@router.get("", response_model=list[MissionRead])
def list_missions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MissionRead]:
    return _attach_tender_info(db, mission_service.list_missions(db, current_user.company_id))


@router.get("/{mission_id}", response_model=MissionRead)
def get_mission(
    mission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MissionRead:
    mission = mission_service.get_mission(db, mission_id, current_user.company_id)
    return _attach_tender_info(db, [mission])[0]


@router.delete("/{mission_id}", response_model=MissionRead)
def archive_mission(
    mission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MissionRead:
    """Archives (soft-delete), never a real DELETE — see mission_service.archive_mission."""
    return mission_service.archive_mission(db, mission_id, current_user.company_id)


@router.delete("/{mission_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_mission(
    mission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Real, permanent deletion — only reachable for an already-archived
    Mission (see mission_service.purge_mission's ConflictError). A
    separate path from DELETE /missions/{id} (which stays the existing
    soft-delete/archive action) rather than a query param on it, so the
    two very different operations ("hide it, recoverable" vs "destroy it,
    irreversible") are never one accidental flag away from each other.
    """
    mission_service.purge_mission(db, mission_id, current_user.company_id)


# 10/minute per IP (Phase 1.5 finding #2) -- this is the Mission
# Orchestrator's own trigger for the full Decision Engine LLM run
# (mission_service.execute_mission -> decision_service.run_evaluation),
# the same cost profile /evaluation/run already carries a limit for.
# Left unrated until now was an oversight, not a deliberate exemption --
# every other cost-incurring endpoint already has this rate.
@router.post("/{mission_id}/execute", response_model=MissionRead)
@limiter.limit("10/minute")
async def execute_mission(
    request: Request,
    mission_id: uuid.UUID,
    payload: ExecuteMissionRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MissionRead:
    provider = payload.provider if payload else None
    return await mission_service.execute_mission(
        db, mission_id, current_user.company_id, current_user.id, provider=provider
    )


@router.get("/{mission_id}/recommendations", response_model=list[RecommendationRead])
def list_mission_recommendations(
    mission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RecommendationRead]:
    """
    All Recommendations for this mission, oldest first — including any
    created by M9 revalidation after the mission was already completed.
    Mission.recommendation_id alone is not enough to see this: it
    deliberately keeps pointing at whatever was actually decided on.
    """
    mission_service.get_mission(db, mission_id, current_user.company_id)  # scoping check
    recommendations = decision_service.get_recommendations_for_mission(db, mission_id)
    return [RecommendationRead.model_validate(r) for r in recommendations]


# Bid-readiness confirmation (Path to GO / Action Center). Admin-gated,
# same require_administrator dependency used for capability delete —
# confirming "this SUBMISSION_GATING/FUTURE_CONTRACTUAL_COMMITMENT item is
# actually prepared" is an administrative action on the bid, matching that
# precedent. See app/services/bid_readiness_service.py for the ownership
# check (requirement's tender's mission_id must match the path's
# mission_id, and the mission's company_id must match the authenticated
# user's company) and app/models/bid_readiness.py for the boundary rule
# (never affects compute_qualification()).
@router.post(
    "/{mission_id}/requirements/{requirement_id}/confirm",
    response_model=BidReadinessConfirmationRead,
    status_code=status.HTTP_201_CREATED,
)
def confirm_requirement(
    mission_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: ConfirmRequirementRequest | None = None,
    current_user: User = Depends(require_administrator),
    db: Session = Depends(get_db),
) -> BidReadinessConfirmationRead:
    note = payload.note if payload else None
    confirmation = bid_readiness_service.confirm_requirement(
        db, mission_id, requirement_id, current_user.company_id, current_user.id, note=note
    )
    return BidReadinessConfirmationRead.model_validate(confirmation)


@router.delete(
    "/{mission_id}/requirements/{requirement_id}/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unconfirm_requirement(
    mission_id: uuid.UUID,
    requirement_id: uuid.UUID,
    current_user: User = Depends(require_administrator),
    db: Session = Depends(get_db),
) -> None:
    bid_readiness_service.unconfirm_requirement(db, mission_id, requirement_id, current_user.company_id)


# Qualification override (Action Center). Admin-gated, same
# require_administrator dependency used for bid-readiness confirmation and
# capability delete/PATCH. Distinct from confirm/unconfirm above -- see
# app/models/qualification_override.py's docstring for exactly how this
# differs (an explicit, audited risk acceptance on a mandatory
# CAPABILITY_CLAIM qualification gap, not a confirmation of an
# already-true fact) and app/services/qualification_override_service.py
# for the ownership check.
@router.post(
    "/{mission_id}/requirements/{requirement_id}/override",
    response_model=QualificationOverrideRead,
    status_code=status.HTTP_201_CREATED,
)
def override_requirement(
    mission_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: OverrideRequirementRequest,
    current_user: User = Depends(require_administrator),
    db: Session = Depends(get_db),
) -> QualificationOverrideRead:
    override = qualification_override_service.override_requirement(
        db, mission_id, requirement_id, current_user.company_id, current_user.id, note=payload.note
    )
    return QualificationOverrideRead.model_validate(override)


@router.delete(
    "/{mission_id}/requirements/{requirement_id}/override",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_qualification_override(
    mission_id: uuid.UUID,
    requirement_id: uuid.UUID,
    current_user: User = Depends(require_administrator),
    db: Session = Depends(get_db),
) -> None:
    qualification_override_service.remove_override(db, mission_id, requirement_id, current_user.company_id)
