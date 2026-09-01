"""
Capability service — the persistence layer for capability entities.

Owns the Document.processing_status lifecycle (PENDING -> PROCESSING ->
COMPLETED/FAILED) and translates agent-layer failures into the
established domain-exception pattern (ExtractionError), consistent with
every other service in this codebase.
"""

import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.agents import capability_builder
from app.core import storage
from app.models import Certification, Employee, Equipment, FinancialRecord, Project
from app.models.enums import CapabilityEntityType, DocumentProcessingStatus, VerificationStatus
from app.services.document_service import get_document
from app.services.exceptions import ConflictError, ExtractionError

logger = logging.getLogger(__name__)

# Used only by build_capability_from_document (M3) — deliberately just
# the three MVP document types with an extraction agent. Do not add
# Equipment/FinancialRecord here; no agent exists for them yet.
ENTITY_MODELS = {
    CapabilityEntityType.CERTIFICATION: Certification,
    CapabilityEntityType.EMPLOYEE: Employee,
    CapabilityEntityType.PROJECT: Project,
}

# Used by the read/graph functions below (M4) — all five domains, since
# the capability graph represents the full company capability model
# even where a domain has no extraction agent yet and stays empty.
ALL_CAPABILITY_MODELS = {
    **ENTITY_MODELS,
    CapabilityEntityType.EQUIPMENT: Equipment,
    CapabilityEntityType.FINANCIAL_RECORD: FinancialRecord,
}

# Fields on the extraction result that need conversion before assignment
# to the SQLAlchemy model (date strings -> real dates). Everything else
# maps 1:1 by field name.
DATE_FIELDS = {"issue_date", "expiry_date"}


def document_has_active_capabilities(db: Session, document_id: uuid.UUID) -> bool:
    """
    True if any of the 5 capability entity tables has a live (not
    soft-removed) row whose source_document_id is this document —
    regardless of which entity_type it was built as. One document
    produces one capability record; a second build attempt without
    deleting the first would just create a duplicate, so this is the
    "one document, one-time capability" guard build_capability_from_document
    checks before running (real) extraction.
    """
    for model_cls in ALL_CAPABILITY_MODELS.values():
        exists = (
            db.query(model_cls.id)
            .filter(model_cls.source_document_id == document_id, model_cls.removed_at.is_(None))
            .first()
        )
        if exists is not None:
            return True
    return False


async def build_capability_from_document(
    db: Session,
    document_id: uuid.UUID,
    company_id: uuid.UUID,
    entity_type: CapabilityEntityType,
):
    # Raises NotFoundError (company-scoped) if the document doesn't
    # belong to this company — propagates as-is, the router already
    # knows how to map it to a 404.
    document = get_document(db, document_id, company_id)

    if document_has_active_capabilities(db, document_id):
        raise ConflictError(
            f"Document '{document_id}' already has capabilities built from it. "
            "Delete the existing capability entry first to rebuild."
        )

    document.processing_status = DocumentProcessingStatus.PROCESSING
    db.commit()

    extension = Path(document.storage_path).suffix.lower()

    try:
        # local_file_for_read() is backend-agnostic (Phase 3: GCP
        # deployment) -- see tender_service.run_analysis() for the same
        # pattern and the full reasoning.
        with storage.local_file_for_read(document.storage_path) as file_path:
            result = await capability_builder.build_capability(file_path, extension, entity_type)
    except Exception as exc:
        # Covers both document_parser failures and LLM call failures --
        # build_capability() calls both, and either can land here.
        logger.exception(
            "Capability extraction failed: document_id=%s entity_type=%s", document_id, entity_type.value
        )
        document.processing_status = DocumentProcessingStatus.FAILED
        document.processed_at = datetime.now(timezone.utc)
        db.commit()
        raise ExtractionError(f"Extraction failed for document '{document_id}': {exc}") from exc

    entity_fields = _prepare_fields(result.fields)
    model_cls = ENTITY_MODELS[entity_type]
    entity = model_cls(
        company_id=company_id,
        confidence_score=result.confidence_score,
        source_document_id=document.id,
        verification_status=VerificationStatus.PENDING,  # never auto-verified, regardless of confidence
        **entity_fields,
    )
    db.add(entity)

    document.processing_status = DocumentProcessingStatus.COMPLETED
    document.extraction_confidence = result.confidence_score
    document.processed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(entity)
    return entity_type, entity


# --- Manual capability creation (no document, no LLM extraction). Writes
# into the exact same five tables build_capability_from_document() uses —
# same Capability Library, same matching pipeline, no parallel system.
# Deliberately keyed off ALL_CAPABILITY_MODELS (all five domains), NOT
# ENTITY_MODELS above — ENTITY_MODELS is specifically "which domains have
# a document-extraction agent" and stays exactly as-is (three entries);
# manual entry is a completely separate creation path that has never
# required an extraction agent, so it covers all five domains including
# Equipment and FinancialRecord, which have had zero creation path until
# now. This deliberately does NOT change EvaluationCoverage/
# decision_engine.get_evaluation_coverage()'s notion of "supported
# domains" (still == ENTITY_MODELS.keys(), i.e. document-extraction
# coverage only) — that is a distinct concept from "can a capability
# record of this type exist at all," and conflating the two here would
# silently change decision_engine.py's coverage-gap behavior as a side
# effect of an unrelated feature. ---

# Required fields per entity type for manual creation — mirrors each
# model's own NOT NULL columns (app/models/capability.py) PLUS one
# additional business rule: financial_year is not a NOT NULL DB column,
# but is required here anyway. Reasoning (found via a real user report —
# a manually-created FinancialRecord with every field except
# financial_year filled in can never satisfy a year-specific eligibility
# requirement like "attach Income Tax Returns for the three years ending
# 31.03.2026", since match_requirement() has no year to reason about and
# correctly refuses to credit an undated record — the requirement stays
# NOT_MET even though a capability record exists, which looks like a bug
# from the outside but is actually the matcher being honest about
# genuinely unverifiable evidence. Making financial_year required at
# creation time prevents entering data that can structurally never
# resolve a year-specific gap. Project remains the only type with no
# required domain field beyond what CapabilityMetadataMixin provides.
MANUAL_REQUIRED_FIELDS: dict[CapabilityEntityType, set[str]] = {
    CapabilityEntityType.CERTIFICATION: {"certification_name"},
    CapabilityEntityType.EMPLOYEE: {"name"},
    CapabilityEntityType.PROJECT: set(),
    CapabilityEntityType.EQUIPMENT: {"equipment_name"},
    CapabilityEntityType.FINANCIAL_RECORD: {"financial_year"},
}

# Settable fields per entity type for manual creation — every real domain
# column on that entity's model (excludes the CapabilityMetadataMixin
# fields, which manual creation never lets the caller set directly: no
# source_document_id since there's no document, confidence_score stays
# None, verification_status stays PENDING — same "never auto-verified"
# rule build_capability_from_document already follows).
MANUAL_CREATE_FIELDS: dict[CapabilityEntityType, set[str]] = {
    CapabilityEntityType.CERTIFICATION: {
        "certification_name", "issuing_authority", "issue_date", "expiry_date", "status",
    },
    CapabilityEntityType.EMPLOYEE: {
        "name", "position", "qualification", "experience", "availability", "skills",
    },
    CapabilityEntityType.PROJECT: {
        "client", "industry", "contract_value", "duration", "completion_status", "similarity_tags",
    },
    CapabilityEntityType.EQUIPMENT: {
        "equipment_name", "category", "quantity", "availability", "specifications",
    },
    CapabilityEntityType.FINANCIAL_RECORD: {
        "financial_year", "revenue", "net_worth", "working_capital", "credit_rating",
    },
}


def build_capability_manual(
    db: Session, company_id: uuid.UUID, entity_type: CapabilityEntityType, fields: dict
):
    """
    Creates one capability entity directly from caller-supplied fields —
    no Document, no LLM extraction. Raises ValueError (mapped to 422 by
    the router, same convention as capability_service's PATCH path) for
    an unknown field name or a missing required field; both are caller
    input errors, not domain/persistence failures.

    verification_status stays at the model's own PENDING default (never
    auto-verified, matching build_capability_from_document's explicit
    comment) — VerificationStatus (app/models/enums.py) has no member
    that distinguishes "human-entered" from "AI-extracted" today; adding
    one was considered out of scope for this change (see the manual
    capability creation completion report) and flagged as a possible
    follow-up rather than invented here.
    """
    allowed = MANUAL_CREATE_FIELDS[entity_type]
    unknown = set(fields.keys()) - allowed
    if unknown:
        raise ValueError(f"Field(s) not settable for {entity_type.value}: {', '.join(sorted(unknown))}")

    required = MANUAL_REQUIRED_FIELDS[entity_type]
    provided_non_empty = {k for k, v in fields.items() if v not in (None, "")}
    missing = required - provided_non_empty
    if missing:
        raise ValueError(f"Missing required field(s) for {entity_type.value}: {', '.join(sorted(missing))}")

    prepared = _prepare_fields(fields)
    model_cls = ALL_CAPABILITY_MODELS[entity_type]
    entity = model_cls(
        company_id=company_id,
        confidence_score=None,
        source_document_id=None,
        verification_status=VerificationStatus.PENDING,
        **prepared,
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity_type, entity


def _prepare_fields(fields: dict) -> dict:
    prepared = dict(fields)
    for field_name in DATE_FIELDS:
        if field_name in prepared and prepared[field_name]:
            prepared[field_name] = date.fromisoformat(prepared[field_name])
    return prepared


def list_capabilities(db: Session, company_id: uuid.UUID) -> list[tuple[CapabilityEntityType, object]]:
    """
    Excludes soft-removed entities (removed_at IS NOT NULL) — this is the
    one shared function feeding both M4's capability graph view and
    M6/M9's matching candidate pool, so filtering here means a removed
    entity genuinely stops being considered everywhere at once, not just
    hidden from one view.
    """
    results: list[tuple[CapabilityEntityType, object]] = []
    for entity_type, model_cls in ALL_CAPABILITY_MODELS.items():
        rows = (
            db.query(model_cls)
            .filter(model_cls.company_id == company_id, model_cls.removed_at.is_(None))
            .all()
        )
        results.extend((entity_type, row) for row in rows)
    return results


def find_capability_by_id(
    db: Session, entity_id: uuid.UUID, company_id: uuid.UUID
) -> tuple[CapabilityEntityType, object] | None:
    """
    Deliberately NOT filtered by removed_at, unlike list_capabilities —
    PATCH/DELETE need to look up an entity regardless of its current
    removed state (e.g. to correctly report "already removed" on a
    second DELETE attempt), and a direct lookup by known ID is a
    different operation from browsing the active graph.
    """
    for entity_type, model_cls in ALL_CAPABILITY_MODELS.items():
        row = (
            db.query(model_cls)
            .filter(model_cls.id == entity_id, model_cls.company_id == company_id)
            .one_or_none()
        )
        if row is not None:
            return entity_type, row
    return None


# --- M9: plain capability mutation. No revalidation awareness here at
# all — that orchestration lives in revalidation_service.py, which calls
# these as pure CRUD, consistent with keeping this module focused on
# capability persistence only. ---

PATCHABLE_FIELDS = {
    CapabilityEntityType.CERTIFICATION: {
        "certification_name", "issuing_authority", "issue_date", "expiry_date", "status",
    },
    CapabilityEntityType.EMPLOYEE: {
        "name", "position", "qualification", "experience", "availability", "skills",
    },
    CapabilityEntityType.PROJECT: {
        "client", "industry", "contract_value", "duration", "completion_status", "similarity_tags",
    },
    # Equipment/FinancialRecord were left out of the original M9 PATCH
    # rollout (predates manual creation, when neither type had any
    # creation path at all -- see build_capability_manual's own comment).
    # Added here for a real user-reported case: a manually-created
    # FinancialRecord submitted before financial_year became a required
    # field (see MANUAL_REQUIRED_FIELDS above) has no way to be corrected
    # in place -- PATCH /capabilities/{id} already exists and is fully
    # entity-type-agnostic (revalidation_service.handle_capability_update
    # doesn't branch on entity_type), so this is just closing a field
    # whitelist gap, not new plumbing.
    CapabilityEntityType.EQUIPMENT: {
        "equipment_name", "category", "quantity", "availability", "specifications",
    },
    CapabilityEntityType.FINANCIAL_RECORD: {
        "financial_year", "revenue", "net_worth", "working_capital", "credit_rating",
    },
}


def update_capability_fields(entity_type: CapabilityEntityType, entity, updates: dict) -> dict:
    """
    Applies whitelisted field updates in-place (caller commits).
    Returns {field: (old_value, new_value)} for only the fields that
    genuinely changed — an update that resends identical values changes
    nothing and returns an empty dict, which is exactly what makes a
    repeated identical PATCH a real no-op upstream, not just a policy.
    """
    allowed = PATCHABLE_FIELDS.get(entity_type, set())
    unknown = set(updates.keys()) - allowed
    if unknown:
        raise ValueError(f"Field(s) not patchable for {entity_type.value}: {', '.join(sorted(unknown))}")

    changed = {}
    for field, new_value in updates.items():
        if field in DATE_FIELDS and isinstance(new_value, str):
            new_value = date.fromisoformat(new_value)
        old_value = getattr(entity, field)
        if old_value != new_value:
            changed[field] = (old_value, new_value)
            setattr(entity, field, new_value)
    return changed


def soft_remove_capability(entity) -> None:
    """Sets removed_at — caller is responsible for the 'already removed' conflict check."""
    entity.removed_at = datetime.now(timezone.utc)
