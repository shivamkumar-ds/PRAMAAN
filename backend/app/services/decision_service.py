"""
Decision service — persistence layer for Decision Intelligence.

Ordering matters here and is worth stating explicitly: ComplianceMatrix.
recommendation_id is NOT NULL, so the Recommendation row must exist
before any ComplianceMatrix row can be written. All reasoning (LLM
matching, freshness overrides, confidence propagation) happens first,
entirely in memory via decision_engine — only once every result is known
do we start writing to the database, in this order: CapabilitySnapshot,
Recommendation, CapabilityMapping (per cited entity), ComplianceMatrix,
then Mission is updated last to point at the finished Recommendation
and Snapshot.
"""

import asyncio
import logging
import uuid

from sqlalchemy.orm import Session

from app.agents import decision_engine
from app.core.config import get_settings
from app.models import (
    CapabilityMapping,
    CapabilitySnapshot,
    Certification,
    ComplianceMatrix,
    Document,
    Employee,
    Equipment,
    FinancialRecord,
    Project,
    Recommendation,
    Tender,
)
from app.models.enums import (
    CapabilityEntityType,
    ComplianceMatrixVerificationStatus,
    MissionStatus,
    RequirementNature,
)
from app.schemas.capability import (
    CertificationRead,
    EmployeeRead,
    EquipmentRead,
    FinancialRecordRead,
    ProjectRead,
)
from app.schemas.decision import EvidenceSourceRead
from app.services import capability_service, mission_service
from app.services.exceptions import ExtractionError, NotFoundError

settings = get_settings()

# entity_type -> (ORM model, display-label function). Same polymorphic shape
# revalidation_service.py already relies on (CapabilityMapping.capability_entity_type
# + capability_entity_id), just resolved to a human-readable label here instead of
# used for dependency traversal. FinancialRecord has no name-ish field, so it gets a
# synthesized label instead of a real fallback name.
_ENTITY_LABEL_RESOLVERS = {
    CapabilityEntityType.CERTIFICATION: (Certification, lambda e: e.certification_name),
    CapabilityEntityType.EMPLOYEE: (Employee, lambda e: e.name),
    CapabilityEntityType.PROJECT: (Project, lambda e: e.client or "Project record"),
    CapabilityEntityType.EQUIPMENT: (Equipment, lambda e: e.equipment_name),
    CapabilityEntityType.FINANCIAL_RECORD: (
        FinancialRecord,
        lambda e: f"Financial record ({e.financial_year})" if e.financial_year else "Financial record",
    ),
}

logger = logging.getLogger(__name__)

_READ_SCHEMAS_FOR_SNAPSHOT = {
    "certification": CertificationRead,
    "employee": EmployeeRead,
    "project": ProjectRead,
    "equipment": EquipmentRead,
    "financial_record": FinancialRecordRead,
}


def _serialize_capability_graph(entities: list[tuple]) -> dict:
    """JSON-able snapshot of the full capability graph at evaluation time —
    every entity, not just the ones cited as evidence (matches 07's own
    description of what a Capability Snapshot contains)."""
    grouped: dict[str, list[dict]] = {key: [] for key in _READ_SCHEMAS_FOR_SNAPSHOT}
    for entity_type, entity in entities:
        schema_cls = _READ_SCHEMAS_FOR_SNAPSHOT[entity_type.value]
        grouped[entity_type.value].append(schema_cls.model_validate(entity).model_dump(mode="json"))
    return grouped


async def run_evaluation(
    db: Session,
    mission_id: uuid.UUID,
    company_id: uuid.UUID,
    preserve_mission_state: bool = False,
    provider: str | None = None,
) -> Recommendation:
    """
    preserve_mission_state=True (M9 only): every step below still happens
    identically — new CapabilitySnapshot, new Recommendation, new
    CapabilityMapping/ComplianceMatrix rows — but the final Mission
    mutation is skipped. Used specifically when revalidating a mission
    that a human has already decided on: the new Recommendation exists
    for current operational awareness, but Mission.status/recommendation_id
    must keep pointing at whatever was actually approved/rejected.
    Default (False) is the original M6/M7/M8 behavior, unchanged.
    """
    logger.info("Evaluation run starting: mission_id=%s", mission_id)
    mission = mission_service.get_mission(db, mission_id, company_id)

    tender = db.query(Tender).filter(Tender.mission_id == mission.id).one_or_none()
    if tender is None:
        raise NotFoundError(f"No tender found for mission '{mission_id}'.")

    from app.models import Requirement

    requirements = db.query(Requirement).filter(Requirement.tender_id == tender.id).all()
    if not requirements:
        raise ExtractionError(
            f"Tender '{tender.id}' has no extracted requirements — run tender analysis first."
        )

    all_entities = capability_service.list_capabilities(db, company_id)

    # Action Center V-next follow-up: "supported domain" used to mean
    # capability_service.ENTITY_MODELS (only CERTIFICATION/EMPLOYEE/PROJECT
    # — "has a document-extraction agent"), which predates manual capability
    # creation. Now that build_capability_manual() writes real rows into
    # Equipment/FinancialRecord too, "supported for matching" must mean "can
    # a candidate row of this domain exist at all" (ALL_CAPABILITY_MODELS),
    # not "can it be auto-extracted from a document." Document-based
    # building for Equipment/FinancialRecord still doesn't exist — only
    # manual entry does — but manually-entered ones now correctly count as
    # real candidates instead of being permanently coverage-gapped. Computed
    # once here (decision_service already imports capability_service) and
    # passed into decision_engine.match_requirement() as a plain parameter
    # rather than importing capability_service into decision_engine.py —
    # keeps the "reasoning only, no persistence" layering decision_engine.py's
    # own module docstring states, since capability_service.py is a
    # stateful, Session-requiring module for every other function on it.
    supported_domains = set(capability_service.ALL_CAPABILITY_MODELS.keys())

    entity_confidences: list[float] = []
    document_ids_cited: set[uuid.UUID] = set()

    # RC-2 remediation (finding H-3): per-requirement LLM matching used to
    # run fully sequentially -- one `await` per requirement, one at a time.
    # For a realistic 30-50 requirement tender that's 30-150+ seconds of
    # pure sequential LLM latency inside one synchronous request. This
    # parallelizes the independent matches with a bounded semaphore
    # (settings.decision_engine_max_concurrency, default 5) rather than
    # unlimited concurrency, so a large tender can't hammer the LLM
    # provider with dozens of simultaneous requests at once.
    #
    # Candidates are computed up front, outside the coroutine, so every
    # concurrent task only ever reads `all_entities` (never mutates it) --
    # no shared-state race between tasks. `asyncio.gather()` preserves the
    # order of its input list in its output list regardless of completion
    # order, so `results` ends up in the exact same requirement order the
    # old sequential loop produced -- ordering is preserved by construction,
    # not by extra bookkeeping. Error handling is unchanged in effect: by
    # default `gather()` (no `return_exceptions=True`) re-raises the first
    # exception encountered, exactly matching the old loop's "one failure
    # fails the whole evaluation" behavior, still caught by the same
    # try/except below and converted to the same ExtractionError.
    semaphore = asyncio.Semaphore(settings.decision_engine_max_concurrency)

    async def _match_one(requirement):
        # Architecture debate Phase 2: gate is now requirement_nature, not
        # requirement_type — see decision_engine.resolve_evaluation_nature()
        # and build_non_capability_result()'s docstring for why (an EMD or
        # PPE clause filed under an otherwise-matchable requirement_type
        # must still skip capability matching entirely; no capability
        # entity could ever satisfy it).
        if decision_engine.resolve_evaluation_nature(requirement) != RequirementNature.CAPABILITY_CLAIM:
            candidates = []
        else:
            # Architecture debate Phase 3: base CATEGORY_DOMAINS mapping
            # widened (never narrowed) by deterministic keyword hints from
            # the requirement text — see decision_engine.resolve_candidate_domains().
            domains = decision_engine.resolve_candidate_domains(requirement)
            candidates = [
                (entity_type, entity) for entity_type, entity in all_entities if entity_type in domains
            ]
        async with semaphore:
            result = await decision_engine.match_requirement(
                requirement, candidates, provider=provider, supported_domains=supported_domains
            )
        return result, candidates

    try:
        matched = await asyncio.gather(*(_match_one(requirement) for requirement in requirements))
    except Exception as exc:
        logger.exception("Evaluation run failed: mission_id=%s", mission_id)
        raise ExtractionError(f"Decision evaluation failed for mission '{mission_id}': {exc}") from exc

    results = []
    for result, candidates in matched:
        results.append(result)
        if result.matched_entity_id is not None:
            matched_entity = next(e for t, e in candidates if e.id == result.matched_entity_id)
            if matched_entity.confidence_score is not None:
                entity_confidences.append(float(matched_entity.confidence_score))
            if matched_entity.source_document_id is not None:
                document_ids_cited.add(matched_entity.source_document_id)

    document_confidences = _document_confidences(db, document_ids_cited)

    recommendation_type = decision_engine.compute_recommendation_type(results)
    confidence = decision_engine.compute_confidence_propagation(results, entity_confidences, document_confidences)
    executive_summary = decision_engine.build_executive_summary(recommendation_type, results, confidence)
    recommendation_risk = decision_engine.RECOMMENDATION_RISK_MAP[recommendation_type]

    existing_snapshot_count = (
        db.query(CapabilitySnapshot).filter(CapabilitySnapshot.mission_id == mission.id).count()
    )
    snapshot = CapabilitySnapshot(
        mission_id=mission.id,
        snapshot_version=existing_snapshot_count + 1,
        snapshot_data=_serialize_capability_graph(all_entities),
        generated_by="decision_engine",
    )
    db.add(snapshot)
    db.flush()

    recommendation = Recommendation(
        mission_id=mission.id,
        recommendation_type=recommendation_type,
        executive_summary=executive_summary,
        risk_level=recommendation_risk,
        document_confidence=confidence["document_confidence"],
        entity_confidence=confidence["entity_confidence"],
        matching_confidence=confidence["matching_confidence"],
        recommendation_confidence=confidence["recommendation_confidence"],
        overall_confidence=confidence["overall_confidence"],
        snapshot_id=snapshot.id,
    )
    db.add(recommendation)
    db.flush()

    for result in results:
        mapping_id = None
        if result.matched_entity_id is not None:
            mapping = CapabilityMapping(
                requirement_id=result.requirement_id,
                capability_entity_type=result.matched_entity_type,
                capability_entity_id=result.matched_entity_id,
                match_status=result.status,
                evidence=result.notes,
                confidence=result.matching_confidence,
            )
            db.add(mapping)
            db.flush()
            mapping_id = mapping.id

        risk_level = decision_engine.compute_risk_level(result.mandatory, result.status)
        requires_verification, verification_reason = decision_engine.compute_requires_verification(
            result.mandatory, result.status, result.matching_confidence
        )

        compliance_row = ComplianceMatrix(
            recommendation_id=recommendation.id,
            requirement_id=result.requirement_id,
            status=result.status,
            supporting_evidence=result.supporting_evidence,
            notes=result.notes,
            requires_verification=requires_verification,
            verification_reason=verification_reason,
            risk_level=risk_level,
            verification_status=ComplianceMatrixVerificationStatus.PENDING,
            matching_confidence=result.matching_confidence,
            evidence_reference=mapping_id,
        )
        db.add(compliance_row)

    if not preserve_mission_state:
        mission.recommendation_id = recommendation.id
        mission.capability_snapshot_id = snapshot.id
        mission.status = MissionStatus.AWAITING_APPROVAL

    db.commit()
    db.refresh(recommendation)
    logger.info(
        "Evaluation run completed: mission_id=%s recommendation_type=%s",
        mission_id,
        recommendation_type.value,
    )
    return recommendation


def _document_confidences(db: Session, document_ids: set[uuid.UUID]) -> list[float]:
    if not document_ids:
        return []
    from app.models import Document

    rows = db.query(Document).filter(Document.id.in_(document_ids)).all()
    return [float(d.extraction_confidence) for d in rows if d.extraction_confidence is not None]


def get_recommendations_for_mission(db: Session, mission_id: uuid.UUID) -> list[Recommendation]:
    """Ordered oldest-first. Mission.recommendation_id is NOT a reliable 'latest' pointer
    once a mission has been revalidated after completion (M9) — it deliberately keeps
    pointing at whatever was actually decided on. This is the real way to see everything."""
    return (
        db.query(Recommendation)
        .filter(Recommendation.mission_id == mission_id)
        .order_by(Recommendation.generated_at)
        .all()
    )


def get_latest_recommendation_for_mission(db: Session, mission_id: uuid.UUID) -> Recommendation | None:
    return (
        db.query(Recommendation)
        .filter(Recommendation.mission_id == mission_id)
        .order_by(Recommendation.generated_at.desc())
        .first()
    )


def get_evaluation(db: Session, mission_id: uuid.UUID, company_id: uuid.UUID) -> Recommendation:
    mission = mission_service.get_mission(db, mission_id, company_id)
    if mission.recommendation_id is None:
        raise NotFoundError(f"Mission '{mission_id}' has no evaluation yet — run /evaluation/run first.")
    recommendation = db.get(Recommendation, mission.recommendation_id)
    return recommendation


def get_compliance_matrix(db: Session, recommendation_id: uuid.UUID) -> list[ComplianceMatrix]:
    return db.query(ComplianceMatrix).filter(ComplianceMatrix.recommendation_id == recommendation_id).all()


def build_remediation_results(
    compliance_rows: list[ComplianceMatrix], requirements_by_id: dict[uuid.UUID, "Requirement"]
) -> list[decision_engine.MatchResult]:
    """
    Architecture debate Phase 5: reconstructs one MatchResult-equivalent
    object per ComplianceMatrix row, for the read-time endpoints (GET
    /evaluation/{mission_id}, GET /recommendations/{mission_id}) that
    never re-run matching — the real MatchResult objects produced during
    run_evaluation() are gone from memory by the time a later GET comes
    in. See decision_engine.reconstruct_match_result() for why this
    reconstruction is exact, not an approximation.

    capability_service.ALL_CAPABILITY_MODELS is read here (the service
    layer), not inside decision_engine.py — same layering reasoning as
    run_evaluation()'s own supported_domains computation above: keeps
    decision_engine.py free of any import on the stateful,
    Session-requiring capability_service module. Must stay in lockstep
    with run_evaluation()'s own supported_domains value (both derive from
    ALL_CAPABILITY_MODELS now, not just ENTITY_MODELS) — otherwise a
    persisted ComplianceMatrix row from a live run_evaluation() call could
    reconstruct with different unsupported_domains than it was actually
    evaluated with.
    """
    supported_domains = set(capability_service.ALL_CAPABILITY_MODELS.keys())
    return [
        decision_engine.reconstruct_match_result(
            requirements_by_id[row.requirement_id], row, supported_domains
        )
        for row in compliance_rows
    ]


def get_evaluation_bundle(db: Session, mission_id: uuid.UUID, company_id: uuid.UUID):
    """
    Everything an API response needs, assembled here rather than in the
    router — thin routers, business logic inside services.

    Returns (recommendation, compliance_rows, requirements_by_id).
    """
    from app.models import Requirement

    recommendation = get_evaluation(db, mission_id, company_id)
    compliance_rows = get_compliance_matrix(db, recommendation.id)
    requirement_ids = [row.requirement_id for row in compliance_rows]
    requirements = db.query(Requirement).filter(Requirement.id.in_(requirement_ids)).all()
    requirements_by_id = {r.id: r for r in requirements}
    return recommendation, compliance_rows, requirements_by_id


def resolve_verifier_names(db: Session, compliance_rows: list[ComplianceMatrix]) -> dict[uuid.UUID, str]:
    """
    Resolves each row's verified_by (a User id) into that user's display
    name -- the one piece of verification metadata not already sitting on
    the ComplianceMatrix ORM row itself. Same shape as
    resolve_evidence_sources() below: read-time only, nothing persisted,
    tolerant of a verifier whose account no longer resolves (skipped, not
    raised). Returns keyed by user id so callers can do
    `names.get(row.verified_by)`.
    """
    from app.models import User

    verifier_ids = {row.verified_by for row in compliance_rows if row.verified_by is not None}
    if not verifier_ids:
        return {}
    users = db.query(User).filter(User.id.in_(verifier_ids)).all()
    return {user.id: user.name for user in users}


def resolve_evidence_sources(
    db: Session, compliance_rows: list[ComplianceMatrix]
) -> dict[uuid.UUID, EvidenceSourceRead]:
    """
    Resolves each row's evidence_reference (a CapabilityMapping id) into the
    actual company record and source document that grounds it — the
    "Source Clause -> Company Document" half of the Decision Screen's
    signature evidence trail (DESIGN_SYSTEM.md §10). This is a read-time
    resolution only, nothing new is persisted.

    Two-hop lookup: CapabilityMapping -> the one of five entity tables it
    polymorphically points at -> that entity's source Document. Same shape
    revalidation_service.py already uses for dependency traversal
    (CapabilityMapping.capability_entity_type/capability_entity_id); this
    just resolves to a display label instead of using it to find affected
    missions.

    Deliberately tolerant of a mapping whose cited entity no longer
    resolves (e.g. removed) — skips it rather than raising, since a
    resolution gap here must never break the evaluation response itself.
    Returns keyed by CapabilityMapping.id (== ComplianceMatrix.evidence_reference).
    """
    mapping_ids = [row.evidence_reference for row in compliance_rows if row.evidence_reference is not None]
    if not mapping_ids:
        return {}

    mappings = db.query(CapabilityMapping).filter(CapabilityMapping.id.in_(mapping_ids)).all()
    if not mappings:
        return {}

    ids_by_type: dict[CapabilityEntityType, list[uuid.UUID]] = {}
    for mapping in mappings:
        ids_by_type.setdefault(mapping.capability_entity_type, []).append(mapping.capability_entity_id)

    # (entity_type, entity_id) -> (label, source_document_id)
    entities: dict[tuple[CapabilityEntityType, uuid.UUID], tuple[str, uuid.UUID | None]] = {}
    for entity_type, entity_ids in ids_by_type.items():
        model_cls, label_fn = _ENTITY_LABEL_RESOLVERS[entity_type]
        for row in db.query(model_cls).filter(model_cls.id.in_(entity_ids)).all():
            entities[(entity_type, row.id)] = (label_fn(row), row.source_document_id)

    document_ids = {doc_id for _, doc_id in entities.values() if doc_id is not None}
    document_names: dict[uuid.UUID, str] = {}
    if document_ids:
        for document in db.query(Document).filter(Document.id.in_(document_ids)).all():
            document_names[document.id] = document.file_name

    resolved: dict[uuid.UUID, EvidenceSourceRead] = {}
    for mapping in mappings:
        key = (mapping.capability_entity_type, mapping.capability_entity_id)
        if key not in entities:
            continue
        label, source_document_id = entities[key]
        resolved[mapping.id] = EvidenceSourceRead(
            entity_type=mapping.capability_entity_type,
            label=label,
            source_document_id=source_document_id,
            source_document_name=document_names.get(source_document_id) if source_document_id else None,
        )
    return resolved
