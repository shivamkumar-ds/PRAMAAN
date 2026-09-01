"""Pydantic schemas for the bid-readiness confirmation feature."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConfirmRequirementRequest(BaseModel):
    note: str | None = None


class BidReadinessConfirmationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    requirement_id: uuid.UUID
    confirmed_by: uuid.UUID
    confirmed_at: datetime
    note: str | None
