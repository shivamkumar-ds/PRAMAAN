"""
Company API — Read endpoint only.

RC-1 audit finding A1: this file used to also expose `POST /company`, a
leftover from the M0 vertical slice built before M1 introduced auth. It
created a bare Company row with no authentication dependency at all and no
associated user, duplicating (and bypassing) auth_service.register() —
the correct, atomic Company+Administrator creation path every real signup
actually uses. An unauthenticated endpoint that writes to the database is
a spam/resource-exhaustion vector, and every company it created was
permanently orphaned (no user could ever log into it). Removed rather
than fixed-in-place, since /auth/register already covers this need
correctly — confirmed via grep that the frontend never called this route.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_administrator
from app.core.database import get_db
from app.models import User
from app.schemas.company import CompanyRead, CompanyUpdate
from app.services import company_service

router = APIRouter(prefix="/company", tags=["company"])


def _ensure_own_company(company_id: uuid.UUID, current_user: User) -> None:
    """Shared tenant-isolation guard for both endpoints below — a 404,
    not 403, for any company that isn't the caller's own, consistent
    with never revealing whether something exists for a tenant that
    isn't yours (same principle used everywhere since M1)."""
    if company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Company '{company_id}' not found.")


@router.get("/{company_id}", response_model=CompanyRead)
def get_company(
    company_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CompanyRead:
    """
    M10 audit finding: this endpoint had no authentication at all — a
    real gap dating back to M0 (built before M1 introduced auth), never
    revisited since. Fixed to match the pattern every other endpoint in
    the system already follows: authenticated, and scoped so a user can
    only view their own company — a 404, not 403, for anything else,
    consistent with never revealing whether something exists for a
    tenant that isn't yours (same principle used everywhere since M1).
    """
    _ensure_own_company(company_id, current_user)
    return company_service.get_company(db, company_id)


@router.patch("/{company_id}", response_model=CompanyRead)
def update_company(
    company_id: uuid.UUID,
    payload: CompanyUpdate,
    admin: User = Depends(require_administrator),
    db: Session = Depends(get_db),
) -> CompanyRead:
    """
    Closes the gap Settings.tsx's OrganizationSection has documented
    since it was first built ("so that when a real PATCH /company
    endpoint exists, this same layout gains input elements instead of
    being rebuilt") — organization name/industry/country were readable
    everywhere but editable nowhere, for any role, since RC-1 audit
    finding A1 removed the old unauthenticated POST /company entirely.

    Administrator-only (same require_administrator dependency users.py's
    POST already uses) and tenant-scoped like GET above — an
    Administrator can only ever update their own company, never another
    tenant's, regardless of what company_id is in the URL.
    """
    _ensure_own_company(company_id, admin)
    updates = payload.model_dump(exclude_unset=True)
    return company_service.update_company(db, company_id, updates)
