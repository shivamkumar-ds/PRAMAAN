"""
Capabilities API.

POST /build triggers the Capability Builder Agent (M3, unchanged — still
only the three MVP document types with an extraction agent).

GET endpoints (M4) return the Company Capability Graph: a structured
view grouped by capability domain, with freshness computed fresh on
every request. This is a read-time view over the existing relational
tables, not a new storage model — see 99_DECISIONS_LOG.md (D-112).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_administrator
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models import User
from app.models.enums import CapabilityEntityType
from app.schemas.capability import (
    CapabilityBuildResult,
    CertificationRead,
    EmployeeRead,
    EquipmentRead,
    FinancialRecordRead,
    ManualCapabilityCreateRequest,
    ManualCapabilityCreateResult,
    ProjectRead,
)
from app.schemas.revalidation import CapabilityUpdateRequest, FreshnessSweepResult, RevalidationResult
from app.services import revalidation_service
from app.schemas.capability_graph import (
    CapabilityGraphResponse,
    CapabilitySummary,
    CertificationGraphEntry,
    EmployeeGraphEntry,
    EquipmentGraphEntry,
    FinancialRecordGraphEntry,
    ProjectGraphEntry,
)
from app.services import capability_service
from app.services.freshness import evaluate_freshness

router = APIRouter(prefix="/capabilities", tags=["capabilities"])

# --- Used only by POST /build (M3, unchanged) ---
READ_SCHEMAS = {
    CapabilityEntityType.CERTIFICATION: CertificationRead,
    CapabilityEntityType.EMPLOYEE: EmployeeRead,
    CapabilityEntityType.PROJECT: ProjectRead,
}


class BuildCapabilityRequest(BaseModel):
    document_id: uuid.UUID
    entity_type: CapabilityEntityType


def _serialize(entity_type: CapabilityEntityType, entity) -> CapabilityBuildResult:
    schema_cls = READ_SCHEMAS[entity_type]
    return CapabilityBuildResult(entity_type=entity_type, entity=schema_cls.model_validate(entity))


# 20/minute per IP (RC-2 finding H-2) — real LLM extraction call per invocation.
@router.post("/build", response_model=CapabilityBuildResult, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def build_capability(
    request: Request,
    payload: BuildCapabilityRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CapabilityBuildResult:
    if payload.entity_type not in READ_SCHEMAS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{payload.entity_type.value}' is not supported by the Capability Builder in M3.",
        )
    entity_type, entity = await capability_service.build_capability_from_document(
        db, payload.document_id, current_user.company_id, payload.entity_type
    )

    return _serialize(entity_type, entity)


# --- Used by the M4 graph/read endpoints below ---
GRAPH_SCHEMAS = {
    CapabilityEntityType.CERTIFICATION: CertificationGraphEntry,
    CapabilityEntityType.EMPLOYEE: EmployeeGraphEntry,
    CapabilityEntityType.PROJECT: ProjectGraphEntry,
    CapabilityEntityType.EQUIPMENT: EquipmentGraphEntry,
    CapabilityEntityType.FINANCIAL_RECORD: FinancialRecordGraphEntry,
}

DOMAIN_KEYS = {
    CapabilityEntityType.CERTIFICATION: "certifications",
    CapabilityEntityType.EMPLOYEE: "employees",
    CapabilityEntityType.PROJECT: "projects",
    CapabilityEntityType.EQUIPMENT: "equipment",
    CapabilityEntityType.FINANCIAL_RECORD: "financial_records",
}

# The base Read schema for each type, explicit rather than derived via
# MRO reflection — simpler to read and doesn't depend on inheritance order.
GRAPH_BASE_SCHEMAS = {
    CapabilityEntityType.CERTIFICATION: CertificationRead,
    CapabilityEntityType.EMPLOYEE: EmployeeRead,
    CapabilityEntityType.PROJECT: ProjectRead,
    CapabilityEntityType.EQUIPMENT: EquipmentRead,
    CapabilityEntityType.FINANCIAL_RECORD: FinancialRecordRead,
}


# Manual capability creation — no document, no LLM extraction. Admin-gated
# (same require_administrator dependency used for DELETE /capabilities/{id}),
# supports all five entity types including Equipment and FinancialRecord,
# which POST /build cannot create (no extraction agent exists for them —
# see READ_SCHEMAS above, still exactly the three MVP document types).
# Writes into the same five tables /build uses — same Capability Library,
# same matching pipeline, no parallel system.
@router.post("/manual", response_model=ManualCapabilityCreateResult, status_code=status.HTTP_201_CREATED)
def create_capability_manual(
    payload: ManualCapabilityCreateRequest,
    current_user: User = Depends(require_administrator),
    db: Session = Depends(get_db),
) -> ManualCapabilityCreateResult:
    try:
        entity_type, entity = capability_service.build_capability_manual(
            db, current_user.company_id, payload.entity_type, payload.fields
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    schema_cls = GRAPH_BASE_SCHEMAS[entity_type]
    return ManualCapabilityCreateResult(entity_type=entity_type, entity=schema_cls.model_validate(entity))


def _to_graph_entry(entity_type: CapabilityEntityType, entity):
    base_fields = GRAPH_BASE_SCHEMAS[entity_type].model_validate(entity).model_dump()
    freshness = evaluate_freshness(entity)
    graph_schema_cls = GRAPH_SCHEMAS[entity_type]
    return graph_schema_cls(**base_fields, **freshness)


@router.get("", response_model=CapabilityGraphResponse)
def get_capability_graph(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CapabilityGraphResponse:
    results = capability_service.list_capabilities(db, current_user.company_id)

    grouped: dict[str, list] = {key: [] for key in DOMAIN_KEYS.values()}
    total_expired = total_stale = total_current = 0

    for entity_type, entity in results:
        entry = _to_graph_entry(entity_type, entity)
        grouped[DOMAIN_KEYS[entity_type]].append(entry)
        if entry.freshness_status == "expired":
            total_expired += 1
        elif entry.freshness_status == "stale":
            total_stale += 1
        else:
            total_current += 1

    summary = CapabilitySummary(
        total_entities=len(results),
        total_expired=total_expired,
        total_stale=total_stale,
        total_current=total_current,
        by_domain={key: len(items) for key, items in grouped.items()},
    )

    return CapabilityGraphResponse(summary=summary, **grouped)


@router.get("/{entity_id}")
def get_capability(
    entity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = capability_service.find_capability_by_id(db, entity_id, current_user.company_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability entity '{entity_id}' not found.",
        )
    entity_type, entity = result
    return {"entity_type": entity_type.value, "entity": _to_graph_entry(entity_type, entity)}


# --- M9: capability mutation + freshness sweep. Administrator-only —
# consistent with M1's precedent that mutating core company data is an
# administrative action. Business logic lives entirely in
# revalidation_service; these stay thin. ---


@router.patch("/{entity_id}", response_model=RevalidationResult)
async def update_capability(
    entity_id: uuid.UUID,
    payload: CapabilityUpdateRequest,
    current_user: User = Depends(require_administrator),
    db: Session = Depends(get_db),
) -> RevalidationResult:
    # ValueError (invalid field name/value) is local to this endpoint, not
    # part of the shared service-exception set -- NotFoundError/ConflictError
    # now propagate to the centralized handler (app/core/exception_handlers.py).
    try:
        result = await revalidation_service.handle_capability_update(
            db, entity_id, current_user.company_id, payload.fields
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return RevalidationResult(**result)


@router.delete("/{entity_id}", response_model=RevalidationResult)
async def remove_capability(
    entity_id: uuid.UUID,
    current_user: User = Depends(require_administrator),
    db: Session = Depends(get_db),
) -> RevalidationResult:
    result = await revalidation_service.handle_capability_removal(db, entity_id, current_user.company_id)
    return RevalidationResult(
        entity_id=result["entity_id"],
        changed_fields=[],
        affected_missions=result["affected_missions"],
        new_recommendations=result["new_recommendations"],
    )


@router.post("/check-freshness", response_model=FreshnessSweepResult)
async def check_freshness(
    current_user: User = Depends(require_administrator),
    db: Session = Depends(get_db),
) -> FreshnessSweepResult:
    result = await revalidation_service.run_freshness_sweep(db, current_user.company_id)
    return FreshnessSweepResult(**result)
