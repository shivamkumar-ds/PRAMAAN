"""
Company service — business logic layer for Company entities.

Even though this first slice is plain CRUD, it stays in the service
layer rather than inline in the router, so the router/service/model
separation exists from the first endpoint rather than being retrofitted
once real business logic (Capability Builder, Decision Intelligence)
arrives.

create_company() was removed as part of RC-1 audit finding A1 — it
duplicated auth_service.register()'s Company+Administrator creation but
had no way to attach a user, and was exposed through an unauthenticated
router endpoint. Company creation is now exclusively the atomic path in
auth_service.register().
"""

import uuid

from sqlalchemy.orm import Session

from app.models import Company
from app.services.exceptions import NotFoundError


def get_company(db: Session, company_id: uuid.UUID) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise NotFoundError(f"Company '{company_id}' not found.")
    return company


def update_company(db: Session, company_id: uuid.UUID, updates: dict) -> Company:
    """
    Partial update — `updates` is expected to already be
    `CompanyUpdate.model_dump(exclude_unset=True)` from the router, so a
    field genuinely absent from the request payload never appears here at
    all (never overwritten with a stale/default value).

    `name` is the one field on `updates` that is NOT nullable on the
    model (`Company.name: Mapped[str]`, not `str | None`) — a client
    that explicitly sends `{"name": null}` is defensively treated as a
    no-op for that field rather than allowed through to an IntegrityError
    at commit time. `industry`/`country` are genuinely nullable on the
    model, so an explicit null for either is applied as a real clear.
    """
    company = get_company(db, company_id)
    for field, value in updates.items():
        if field == "name" and value is None:
            continue
        setattr(company, field, value)
    db.commit()
    db.refresh(company)
    return company
