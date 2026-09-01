"""Pydantic read schemas for capability entities (Certification, Employee, Project)."""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import CapabilityEntityType, VerificationStatus


class CertificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    certification_name: str
    issuing_authority: str | None
    issue_date: date | None
    expiry_date: date | None
    confidence_score: float | None
    source_document_id: uuid.UUID | None
    verification_status: VerificationStatus
    last_verified_at: datetime | None
    removed_at: datetime | None
    created_at: datetime


class EmployeeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    position: str | None
    qualification: str | None
    experience: str | None
    availability: str | None
    skills: list[str] | None
    confidence_score: float | None
    source_document_id: uuid.UUID | None
    verification_status: VerificationStatus
    last_verified_at: datetime | None
    removed_at: datetime | None
    created_at: datetime


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    client: str | None
    industry: str | None
    contract_value: float | None
    duration: str | None
    completion_status: str | None
    similarity_tags: list[str] | None
    confidence_score: float | None
    source_document_id: uuid.UUID | None
    verification_status: VerificationStatus
    last_verified_at: datetime | None
    removed_at: datetime | None
    created_at: datetime


class EquipmentRead(BaseModel):
    """No extraction agent populates this yet (out of M3's three MVP document types) —
    the schema exists so the M4 capability graph can represent this domain, even empty."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    equipment_name: str
    category: str | None
    quantity: int | None
    availability: str | None
    specifications: str | None
    confidence_score: float | None
    source_document_id: uuid.UUID | None
    verification_status: VerificationStatus
    last_verified_at: datetime | None
    removed_at: datetime | None
    created_at: datetime


class FinancialRecordRead(BaseModel):
    """Same status as EquipmentRead — schema exists for the graph; nothing populates it yet."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    financial_year: int | None
    revenue: float | None
    net_worth: float | None
    working_capital: float | None
    credit_rating: str | None
    confidence_score: float | None
    source_document_id: uuid.UUID | None
    verification_status: VerificationStatus
    last_verified_at: datetime | None
    removed_at: datetime | None
    created_at: datetime


class CapabilityBuildResult(BaseModel):
    """Response schema for POST /capabilities/build.

    Added during the BidOps_Final consolidation (99_DECISIONS_LOG.md D-144).
    The endpoint only ever returns one of the three M3 MVP entity types
    (certification, employee, project — see READ_SCHEMAS in
    app/api/v1/capabilities.py), so the union is scoped to exactly those
    three, not all five CapabilityEntityType members. Verified empirically
    (scratch script, not committed) that Pydantic v2's default union
    validation preserves the exact concrete type — including through a full
    JSON serialize/reparse round trip — rather than misidentifying, e.g., a
    ProjectRead (whose domain fields are all Optional) as some other member.
    """

    entity_type: CapabilityEntityType
    entity: CertificationRead | EmployeeRead | ProjectRead


class ManualCapabilityCreateRequest(BaseModel):
    """
    Request body for POST /capabilities/manual — manual capability
    creation, no document required. `fields` is intentionally a loose
    dict[str, Any] (same shape as CapabilityUpdateRequest.fields in
    app/schemas/revalidation.py, the existing PATCH path) rather than one
    Pydantic model per entity type: capability_service.build_capability_manual()
    is the single source of truth for which fields are allowed/required
    per entity_type (MANUAL_CREATE_FIELDS/MANUAL_REQUIRED_FIELDS), so
    validation isn't duplicated in two places that could drift apart.
    """

    entity_type: CapabilityEntityType
    fields: dict[str, Any]


class ManualCapabilityCreateResult(BaseModel):
    """
    Response schema for POST /capabilities/manual — covers all five
    entity types (unlike CapabilityBuildResult, which is deliberately
    scoped to the three document-extraction MVP types only), since manual
    creation is the one path that has always supported all five.
    """

    entity_type: CapabilityEntityType
    entity: CertificationRead | EmployeeRead | ProjectRead | EquipmentRead | FinancialRecordRead
