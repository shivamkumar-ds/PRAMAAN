"""Pydantic schemas for the qualification override feature."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class OverrideRequirementRequest(BaseModel):
    # Unlike ConfirmRequirementRequest.note (optional), a note is
    # REQUIRED here -- an override is an explicit risk acceptance, not a
    # confirmation of an already-true fact, and must carry a real audit
    # trail explaining why an administrator chose to proceed without
    # evidence (e.g. "customer confirmed the ITR will be arranged before
    # award"). Enforced here, at the API boundary, not just as a UI hint.
    note: str

    @field_validator("note")
    @classmethod
    def note_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("A note explaining the override is required.")
        return v.strip()


class QualificationOverrideRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    requirement_id: uuid.UUID
    overridden_by: uuid.UUID
    overridden_at: datetime
    note: str | None
