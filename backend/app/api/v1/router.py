"""Aggregates all v1 routers. New versioned endpoints register here, not in main.py."""

from fastapi import APIRouter

from app.api.v1 import (
    approval,
    auth,
    capabilities,
    company,
    contact,
    documents,
    evaluation,
    missions,
    sih,
    tenders,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(contact.router)
api_router.include_router(company.router)
api_router.include_router(users.router)
api_router.include_router(documents.router)
api_router.include_router(capabilities.router)
api_router.include_router(tenders.tenders_router)
api_router.include_router(tenders.analysis_router)
api_router.include_router(evaluation.evaluation_router)
api_router.include_router(evaluation.recommendations_router)
api_router.include_router(missions.router)
api_router.include_router(approval.compliance_router)
api_router.include_router(approval.approval_router)
# SIH26100 -- separate sibling domain (Phase 1/2), not part of the frozen
# Tender/Requirement/Capability API surface above.
api_router.include_router(sih.router)
