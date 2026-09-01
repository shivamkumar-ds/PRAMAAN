"""
Pydantic schemas for the SIH26100 Bidder Verification API (Phase 2).

Deliberately a new, SIH-vocabulary schema module -- never reuses Tender/
Requirement/Evaluation schemas even where a field superficially looks
similar (e.g. `status`, `note`, `reason`), because the underlying
domains and their guarantees are different (see the Phase 0/1 reports).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.sih.compliance import VerificationResult
from app.models.sih.enums import (
    ComplianceVerificationStatus,
    DocumentExtractionStatus,
    OfficerDecisionType,
    ProcurementDocumentExtractionStatus,
    ProcurementStatus,
    SubmissionStatus,
)

# --- Procurement ---


class ProcurementCreateRequest(BaseModel):
    title: str
    organization: str | None = None
    reference_number: str | None = None
    category: str | None = None
    closing_date: date | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title is required.")
        return v.strip()


class ProcurementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    title: str
    organization: str | None
    reference_number: str | None
    category: str | None
    closing_date: date | None
    status: ProcurementStatus
    # SIH26100 demo-scope expansion (Collusion Radar repeat-winner
    # indicator) -- which Bidder (if any) this Procurement was awarded to.
    # None until an officer explicitly sets it via
    # PATCH .../procurements/{id}/award -- never inferred.
    awarded_bidder_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class SetAwardedBidderRequest(BaseModel):
    bidder_id: uuid.UUID


# --- Bidder ---


class BidderCreateRequest(BaseModel):
    legal_name: str
    trade_name: str | None = None
    pan: str | None = None
    # SIH26100 demo-scope expansion (Bidder Network Graph) -- optional at
    # creation, same as trade_name/pan; a bidder with none of these filled
    # in simply contributes no relationships (see network_graph_service.py).
    registered_address: str | None = None
    director_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None

    @field_validator("legal_name")
    @classmethod
    def legal_name_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("legal_name is required.")
        return v.strip()


class BidderUpdateRequest(BaseModel):
    """
    Partial update -- every field optional, only fields explicitly
    provided are changed. Exists specifically so an officer can fill in
    the Network Graph identifiers (director/address/contact) for a
    bidder created before this engine existed, without needing a
    separate re-creation flow.
    """

    legal_name: str | None = None
    trade_name: str | None = None
    pan: str | None = None
    registered_address: str | None = None
    director_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None

    @field_validator("legal_name")
    @classmethod
    def legal_name_must_not_be_blank_if_provided(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("legal_name cannot be blank.")
        return v.strip() if v is not None else v


class BidderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    legal_name: str
    trade_name: str | None
    pan: str | None
    registered_address: str | None
    director_name: str | None
    contact_email: str | None
    contact_phone: str | None
    created_at: datetime
    updated_at: datetime


# --- BidderSubmission ---


class SubmissionCreateRequest(BaseModel):
    bidder_id: uuid.UUID
    # SIH26100 demo-scope expansion (Collusion Radar) -- optional at
    # creation; no bid_value field existed anywhere in this domain
    # before this. A submission with no bid_amount is simply excluded
    # from value-based collusion heuristics (see collusion_radar_service.py).
    bid_amount: Decimal | None = None


class SubmissionBidAmountRequest(BaseModel):
    bid_amount: Decimal | None = None


class SubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    procurement_id: uuid.UUID
    bidder_id: uuid.UUID
    status: SubmissionStatus
    bid_amount: Decimal | None
    created_at: datetime
    updated_at: datetime


# --- ComplianceCategory ---


class ComplianceCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    mandatory_by_default: bool
    risk_weight: float
    is_active: bool


# --- Verification ---


class VerifySubmissionRequest(BaseModel):
    """
    declared_facts is keyed by ComplianceCategory.code (e.g. "udyam",
    "gst") -- Phase 2 has no document-upload/OCR pipeline yet
    (explicitly deferred), so the caller supplies what the bidder
    declared directly, the same shape
    verification_service.verify_submission()'s
    declared_facts_by_category parameter already expects. Omitted
    categories are recorded as MISSING (mandatory) or NOT_CLAIMED
    (optional) -- never silently skipped.
    """

    declared_facts: dict[str, dict[str, Any]] = Field(default_factory=dict)


class VerificationResultRead(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    category_id: uuid.UUID
    category_code: str
    category_name: str
    mandatory: bool
    status: ComplianceVerificationStatus
    critical: bool
    declared_value: dict | None
    registry_value: dict | None
    discrepancies: list | None
    confidence: float | None
    source: str
    reason: str | None
    checked_at: datetime
    # Phase 5 evidence linking -- which confirmed BidderDocument (if any)
    # this row's declared_value came from. Both None for the manual-entry
    # verify path and for document-independent categories (blacklisting).
    source_document_id: uuid.UUID | None = None
    source_document_name: str | None = None

    @classmethod
    def from_model(cls, result: VerificationResult) -> "VerificationResultRead":
        return cls(
            id=result.id,
            submission_id=result.submission_id,
            category_id=result.category_id,
            category_code=result.category.code,
            category_name=result.category.name,
            mandatory=result.category.mandatory_by_default,
            status=result.status,
            critical=result.status == ComplianceVerificationStatus.CRITICAL_FAIL,
            declared_value=result.declared_value,
            registry_value=result.registry_value,
            discrepancies=result.discrepancies,
            confidence=result.confidence,
            source=result.source,
            reason=result.reason,
            checked_at=result.checked_at,
            source_document_id=result.source_document_id,
            source_document_name=result.source_document.file_name if result.source_document else None,
        )


class MandatoryComplianceIssueRead(BaseModel):
    """
    One MANDATORY category currently MISSING or MISMATCH -- named
    individually so the officer decision view can list each one, rather
    than only showing the aggregate risk_level="high" it already
    contributes to. See compliance_summary_service.MandatoryComplianceIssue.
    """

    model_config = ConfigDict(from_attributes=True)

    category_code: str
    category_name: str
    status: ComplianceVerificationStatus
    reason: str | None
    source_document_id: uuid.UUID | None
    source_document_name: str | None


class ComplianceSummaryRead(BaseModel):
    total_applicable: int
    verified_count: int
    failed_count: int
    missing_count: int
    critical_count: int
    review_count: int
    compliance_score: float
    risk_level: str
    critical_categories: list[str]
    mandatory_issues: list[MandatoryComplianceIssueRead] = Field(default_factory=list)


# --- Officer decision ---


class DecisionRequest(BaseModel):
    decision: OfficerDecisionType
    note: str

    @field_validator("note")
    @classmethod
    def note_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("A note explaining the decision is required.")
        return v.strip()


class OfficerDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    submission_id: uuid.UUID
    officer_id: uuid.UUID
    decision: OfficerDecisionType
    note: str
    decided_at: datetime


# --- Bidder documents (Phase 4) ---


class BidderDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    submission_id: uuid.UUID
    category_code: str | None
    category_source: str
    file_name: str
    uploaded_at: datetime
    extraction_status: DocumentExtractionStatus
    extracted_data: dict[str, Any] | None
    extraction_confidence: float | None
    extraction_error: str | None
    extracted_at: datetime | None
    # Phase 5 -- see app/models/sih/document.py's module docstring. Only
    # ever True when extraction_status == EXTRACTED; confirmed_data is
    # the (possibly officer-corrected) value actually used for
    # verification, never extracted_data directly.
    is_confirmed: bool
    confirmed_data: dict[str, Any] | None
    confirmed_at: datetime | None
    manually_corrected: bool


class SetDocumentCategoryRequest(BaseModel):
    category_code: str


# --- Collusion Radar (Phase 4) ---


class CollusionIndicatorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    detail: str
    severity: str


class CollusionReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    procurement_id: uuid.UUID
    indicators: list[CollusionIndicatorRead]
    score: int
    disclaimer: str


# --- Bidder Network Graph (Phase 3) ---


class RelatedBidderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bidder_id: uuid.UUID
    legal_name: str
    trade_name: str | None
    reasons: list[str]


class NetworkGraphReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bidder_id: uuid.UUID
    bidder_legal_name: str
    related_bidders: list[RelatedBidderRead]


# --- Authenticity Scanner (Phase 2) ---


class AuthenticityIndicatorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    detail: str
    severity: str


class AuthenticityScanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    indicators: list[AuthenticityIndicatorRead]
    summary_label: str
    scanned_by: uuid.UUID
    scanned_at: datetime


# --- Evidence Grounding Guard (Phase 1b) ---


class CategoryGroundingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_code: str
    category_name: str
    status: ComplianceVerificationStatus
    origin: str
    source_document_id: uuid.UUID | None
    source_document_name: str | None


class GroundingReportRead(BaseModel):
    """
    Read model for grounding_guard_service.GroundingReport -- classifies
    every latest verification result by where its evidence actually came
    from (a confirmed document, an officer's manual declaration, or
    nothing yet), so an officer can see at a glance how much of a
    submission's verdict rests on traceable evidence versus what's still
    outstanding. See app/services/sih/grounding_guard_service.py.
    """

    model_config = ConfigDict(from_attributes=True)

    submission_id: uuid.UUID
    categories: list[CategoryGroundingRead]
    document_evidenced_count: int
    manual_declaration_count: int
    no_evidence_count: int


class ConfirmDocumentExtractionRequest(BaseModel):
    """
    corrected_fields is a partial override merged over the AI's
    extracted_data before being re-validated against the category's
    extraction schema (app/schemas/sih_extraction.py) -- omit or send {}
    to confirm the AI's output as-is. Only fields the schema recognizes
    are accepted; anything else fails validation rather than being
    silently absorbed.
    """

    corrected_fields: dict[str, Any] | None = None


# --- Requirement-to-Evidence Mapping engine ---


class ProcurementDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    procurement_id: uuid.UUID
    original_filename: str
    mime_type: str | None
    file_size_bytes: int | None
    extraction_status: ProcurementDocumentExtractionStatus
    extraction_error: str | None
    uploaded_at: datetime
    uploaded_by: uuid.UUID | None


class ProcurementRequirementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    procurement_id: uuid.UUID
    source_document_id: uuid.UUID | None
    requirement_text: str
    # Advisory only -- the AI's best-guess mapping to a fixed
    # ComplianceCategory.code, or None when it found no confident match.
    # Never authoritative; see app/models/sih/procurement_requirement.py.
    category_hint: str | None
    is_mandatory: bool
    created_at: datetime


class ProcurementDocumentUploadResponse(BaseModel):
    """Response for POST .../tender-document -- the stored document plus
    every requirement extracted from it in this same request."""

    document: ProcurementDocumentRead
    requirements: list[ProcurementRequirementRead]


class RequirementEvidenceMapEntryRead(BaseModel):
    """
    Read model for procurement_requirement_service.RequirementEvidenceMapEntry
    -- a read-only, honestly-labeled view of whether a bidder submission's
    already-persisted verification results actually cover each extracted
    requirement. Never a new persisted verdict -- see that service
    module's docstring.
    """

    model_config = ConfigDict(from_attributes=True)

    requirement_id: uuid.UUID
    requirement_text: str
    category_hint: str | None
    is_mandatory: bool
    status: str
    verification_status: ComplianceVerificationStatus | None
    source_verification_result_id: uuid.UUID | None
    source_document_id: uuid.UUID | None
    source_document_name: str | None
