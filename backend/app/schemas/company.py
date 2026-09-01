"""
Pydantic schemas for Company — the request/response contract for the API layer.

CompanyCreate was removed as part of RC-1 audit finding A1 (POST /company
removed — see app/api/v1/company.py's module docstring). Company creation
now only happens atomically with its first Administrator, via
RegisterRequest (app/schemas/auth.py) and auth_service.register().
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    industry: str | None
    registration_number: str
    country: str | None
    created_at: datetime
    updated_at: datetime


class CompanyUpdate(BaseModel):
    """
    PATCH /company/{id} — Administrator-only (see api/v1/company.py).

    Deliberately excludes `registration_number`: unlike name/industry/
    country (ordinary organizational details), the registration number is
    the company's legal/uniqueness identity (unique=True on the model,
    used as the tenant's real-world anchor). Changing it isn't a typo fix
    — it's a different legal entity — so it's out of scope for this
    endpoint entirely rather than merely discouraged; a client that sends
    it is simply ignored (BaseModel drops unknown fields by default; no
    `registration_number` field exists on this schema to bind to).

    All fields optional and unset by default (not `None`-defaulted to a
    value that would clear the field) — company_service.update_company()
    applies `model_dump(exclude_unset=True)`, so a partial payload (e.g.
    just `{"industry": "Construction"}`) only touches the field(s) the
    client actually sent, never silently blanking the others.
    """

    name: str | None = Field(default=None, min_length=1)
    industry: str | None = None
    country: str | None = None
