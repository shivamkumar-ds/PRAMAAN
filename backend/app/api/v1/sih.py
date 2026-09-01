"""
SIH26100 Bidder Verification API.

Auth policy (Phase 2 initially mapped every SIH write to
require_administrator, the smallest-safe default when no dedicated
"Procurement Officer" role existed -- see git history for that original
reasoning). This router now uses the full 5-role RBAC pass instead:
app/models/user.py's UserRole is ADMINISTRATOR, EXECUTIVE, BID_MANAGER,
REVIEWER, AUDITOR, and every endpoint here is gated by exactly one of:
  - get_current_user: any authenticated user in the company -- every read.
  - require_sih_write_role (app/api/deps.py): every ADMINISTRATOR/
    EXECUTIVE/BID_MANAGER/REVIEWER, EXCLUDING AUDITOR -- the day-to-day
    evidence-gathering writes (create/update procurement/bidder/
    submission, upload/extract/confirm a document, run verification).
    AUDITOR being unable to write anything here is the one rule
    deliberately made airtight: "read-only auditor" is the entire point
    of that role, per the PRD's role definitions.
  - require_sih_decision_role: ADMINISTRATOR/EXECUTIVE/REVIEWER/
    BID_MANAGER -- recording an officer decision.
  - require_sih_award_role: ADMINISTRATOR/EXECUTIVE only -- setting a
    Procurement's awarded bidder (a business decision, not day-to-day
    evidence gathering; see collusion_radar_service.py's repeat-winner
    indicator, which depends on this being set responsibly).
"""

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    require_sih_award_role,
    require_sih_decision_role,
    require_sih_write_role,
)
from app.core.database import get_db
from app.models import User
from app.models.sih.compliance import ComplianceCategory
from app.schemas.sih import (
    AuthenticityScanRead,
    BidderCreateRequest,
    BidderDocumentRead,
    BidderRead,
    BidderUpdateRequest,
    CollusionReportRead,
    ComplianceCategoryRead,
    ComplianceSummaryRead,
    ConfirmDocumentExtractionRequest,
    DecisionRequest,
    GroundingReportRead,
    NetworkGraphReportRead,
    OfficerDecisionRead,
    ProcurementCreateRequest,
    ProcurementDocumentRead,
    ProcurementDocumentUploadResponse,
    ProcurementRead,
    ProcurementRequirementRead,
    RequirementEvidenceMapEntryRead,
    SetDocumentCategoryRequest,
    SubmissionBidAmountRequest,
    SetAwardedBidderRequest,
    SubmissionCreateRequest,
    SubmissionRead,
    VerificationResultRead,
)
from app.services.sih import (
    authenticity_service,
    bidder_service,
    collusion_radar_service,
    compliance_summary_service,
    document_service,
    grounding_guard_service,
    network_graph_service,
    officer_decision_service,
    procurement_requirement_service,
    procurement_service,
    submission_service,
    verification_service,
)

router = APIRouter(prefix="/sih", tags=["sih"])


# --- Procurements ---


@router.post("/procurements", response_model=ProcurementRead)
def create_procurement(
    payload: ProcurementCreateRequest,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> ProcurementRead:
    procurement = procurement_service.create_procurement(
        db,
        current_user.company_id,
        title=payload.title,
        organization=payload.organization,
        reference_number=payload.reference_number,
        category=payload.category,
        closing_date=payload.closing_date,
    )
    return ProcurementRead.model_validate(procurement)


@router.get("/procurements", response_model=list[ProcurementRead])
def list_procurements(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProcurementRead]:
    return [
        ProcurementRead.model_validate(p) for p in procurement_service.list_procurements(db, current_user.company_id)
    ]


@router.get("/procurements/{procurement_id}", response_model=ProcurementRead)
def get_procurement(
    procurement_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProcurementRead:
    procurement = procurement_service.get_procurement(db, procurement_id, current_user.company_id)
    return ProcurementRead.model_validate(procurement)


@router.patch("/procurements/{procurement_id}/award", response_model=ProcurementRead)
def set_procurement_awarded_bidder(
    procurement_id: uuid.UUID,
    payload: SetAwardedBidderRequest,
    # Administrator/Executive only -- awarding is a business decision, not
    # day-to-day evidence-gathering work; see
    # app.api.deps.require_sih_award_role's docstring.
    current_user: User = Depends(require_sih_award_role),
    db: Session = Depends(get_db),
) -> ProcurementRead:
    """
    Records this Procurement's awarded bidder -- feeds the Collusion
    Radar's repeated-winner indicator (see
    app/services/sih/collusion_radar_service.py). See
    procurement_service.set_awarded_bidder()'s docstring for the two
    guards enforced before this succeeds (bidder actually submitted;
    at least one officer decision already recorded for this procurement).
    """
    procurement = procurement_service.set_awarded_bidder(
        db, procurement_id, current_user.company_id, payload.bidder_id
    )
    return ProcurementRead.model_validate(procurement)


# --- Bidders ---


@router.post("/bidders", response_model=BidderRead)
def create_bidder(
    payload: BidderCreateRequest,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> BidderRead:
    bidder = bidder_service.create_bidder(
        db,
        current_user.company_id,
        legal_name=payload.legal_name,
        trade_name=payload.trade_name,
        pan=payload.pan,
        registered_address=payload.registered_address,
        director_name=payload.director_name,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
    )
    return BidderRead.model_validate(bidder)


@router.get("/bidders", response_model=list[BidderRead])
def list_bidders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[BidderRead]:
    return [BidderRead.model_validate(b) for b in bidder_service.list_bidders(db, current_user.company_id)]


@router.get("/bidders/{bidder_id}", response_model=BidderRead)
def get_bidder(
    bidder_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BidderRead:
    bidder = bidder_service.get_bidder(db, bidder_id, current_user.company_id)
    return BidderRead.model_validate(bidder)


@router.patch("/bidders/{bidder_id}", response_model=BidderRead)
def update_bidder(
    bidder_id: uuid.UUID,
    payload: BidderUpdateRequest,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> BidderRead:
    """
    Partial update -- primarily so an officer can fill in the Bidder
    Network Graph identifiers (director/address/contact) for an existing
    bidder. Only fields explicitly present in the request body are
    changed (exclude_unset), never overwritten with None by omission.
    """
    bidder = bidder_service.update_bidder(
        db, bidder_id, current_user.company_id, **payload.model_dump(exclude_unset=True)
    )
    return BidderRead.model_validate(bidder)


@router.get("/bidders/{bidder_id}/network", response_model=NetworkGraphReportRead)
def get_bidder_network(
    bidder_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NetworkGraphReportRead:
    """
    Bidder Network Graph (Phase 3) -- other bidders in this company/tenant
    sharing a real identifier (director/address/contact) with this one,
    and why. See app/services/sih/network_graph_service.py; never implies
    wrongdoing, only reports a factual shared identifier.
    """
    report = network_graph_service.get_related_bidders(db, bidder_id, current_user.company_id)
    return NetworkGraphReportRead.model_validate(report)


# --- Submissions ---


@router.post("/procurements/{procurement_id}/submissions", response_model=SubmissionRead)
def create_submission(
    procurement_id: uuid.UUID,
    payload: SubmissionCreateRequest,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> SubmissionRead:
    submission = submission_service.create_submission(
        db, procurement_id, payload.bidder_id, current_user.company_id, bid_amount=payload.bid_amount
    )
    return SubmissionRead.model_validate(submission)


@router.patch("/submissions/{submission_id}/bid-amount", response_model=SubmissionRead)
def set_submission_bid_amount(
    submission_id: uuid.UUID,
    payload: SubmissionBidAmountRequest,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> SubmissionRead:
    submission = submission_service.set_bid_amount(
        db, submission_id, current_user.company_id, payload.bid_amount
    )
    return SubmissionRead.model_validate(submission)


@router.get("/procurements/{procurement_id}/collusion-radar", response_model=CollusionReportRead)
def get_procurement_collusion_radar(
    procurement_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CollusionReportRead:
    """
    Collusion Radar (Phase 4) -- transparent heuristic indicators over
    this procurement's bid values and bidder participation history. See
    app/services/sih/collusion_radar_service.py; never states collusion
    as confirmed, always includes CollusionReport.disclaimer.
    """
    report = collusion_radar_service.get_collusion_indicators(db, procurement_id, current_user.company_id)
    return CollusionReportRead.model_validate(report)


@router.get("/procurements/{procurement_id}/submissions", response_model=list[SubmissionRead])
def list_submissions_for_procurement(
    procurement_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SubmissionRead]:
    return [
        SubmissionRead.model_validate(s)
        for s in submission_service.list_submissions_for_procurement(db, procurement_id, current_user.company_id)
    ]


@router.get("/submissions/{submission_id}", response_model=SubmissionRead)
def get_submission(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubmissionRead:
    submission = submission_service.get_owned_submission(db, submission_id, current_user.company_id)
    return SubmissionRead.model_validate(submission)


# --- Compliance categories (read-only reference data) ---


@router.get("/compliance-categories", response_model=list[ComplianceCategoryRead])
def list_compliance_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ComplianceCategoryRead]:
    categories = db.query(ComplianceCategory).order_by(ComplianceCategory.code.asc()).all()
    return [ComplianceCategoryRead.model_validate(c) for c in categories]


# --- Verification ---


@router.post("/submissions/{submission_id}/verify", response_model=list[VerificationResultRead])
async def verify_submission(
    submission_id: uuid.UUID,
    # declared_facts arrives as a JSON-encoded string field, not a JSON
    # body -- multipart/form-data (required so `attachment` below can be a
    # real file part) can't mix with a JSON request body in the same
    # request. This is the one behavior change from the pre-evidence-
    # attachment version of this endpoint; every other request field and
    # every response shape is unchanged, and calling without `attachment`
    # still declares facts exactly as before -- see
    # app/services/sih/document_service.attach_manual_evidence's docstring
    # for what happens when it IS provided.
    declared_facts: str = Form(...),
    attachment: UploadFile | None = File(None),
    # Which single category (a key already present in declared_facts)
    # `attachment` is evidence for -- required together with attachment,
    # since one manual-declare request can cover many categories but an
    # officer attaches one supporting file at a time.
    attachment_category_code: str | None = Form(None),
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> list[VerificationResultRead]:
    try:
        parsed_declared_facts = json.loads(declared_facts)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"declared_facts must be valid JSON: {exc}") from exc
    if not isinstance(parsed_declared_facts, dict):
        raise HTTPException(status_code=422, detail="declared_facts must be a JSON object keyed by category code.")

    submission = submission_service.get_owned_submission(db, submission_id, current_user.company_id)
    bidder = submission_service.get_submission_bidder(db, submission)
    bidder_identity = {"pan": bidder.pan, "legal_name": bidder.legal_name, "trade_name": bidder.trade_name}

    source_document_by_category: dict[str, uuid.UUID] | None = None
    if attachment is not None:
        if not attachment_category_code:
            raise HTTPException(
                status_code=422, detail="attachment_category_code is required when an attachment is provided."
            )
        if attachment_category_code not in parsed_declared_facts:
            raise HTTPException(
                status_code=422,
                detail="attachment_category_code must be one of the categories declared in declared_facts.",
            )
        document = await document_service.attach_manual_evidence(
            db,
            submission_id,
            current_user.company_id,
            current_user.id,
            attachment_category_code,
            parsed_declared_facts[attachment_category_code],
            attachment,
        )
        source_document_by_category = {attachment_category_code: document.id}

    results = verification_service.verify_submission(
        db, submission_id, bidder_identity, parsed_declared_facts, source_document_by_category
    )
    return [VerificationResultRead.from_model(r) for r in results]


@router.get("/submissions/{submission_id}/verification", response_model=list[VerificationResultRead])
def get_submission_verification(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[VerificationResultRead]:
    submission_service.get_owned_submission(db, submission_id, current_user.company_id)
    results = verification_service.get_latest_results(db, submission_id)
    return [VerificationResultRead.from_model(r) for r in results]


@router.get("/submissions/{submission_id}/summary", response_model=ComplianceSummaryRead)
def get_submission_summary(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ComplianceSummaryRead:
    submission_service.get_owned_submission(db, submission_id, current_user.company_id)
    summary = compliance_summary_service.get_compliance_summary(db, submission_id)
    return ComplianceSummaryRead.model_validate(summary.__dict__)


@router.get("/submissions/{submission_id}/grounding", response_model=GroundingReportRead)
def get_submission_grounding(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroundingReportRead:
    """
    Evidence Grounding Guard (Phase 1b) -- classifies every latest
    verification result by where its evidence actually came from
    (confirmed document / manual officer declaration / no evidence yet).
    See app/services/sih/grounding_guard_service.py.
    """
    submission_service.get_owned_submission(db, submission_id, current_user.company_id)
    report = grounding_guard_service.get_grounding_report(db, submission_id)
    return GroundingReportRead.model_validate(report)


# --- Officer decisions ---


@router.post("/submissions/{submission_id}/decision", response_model=OfficerDecisionRead)
def record_decision(
    submission_id: uuid.UUID,
    payload: DecisionRequest,
    # ADMINISTRATOR/EXECUTIVE/REVIEWER/BID_MANAGER -- see
    # app.api.deps.require_sih_decision_role's docstring.
    current_user: User = Depends(require_sih_decision_role),
    db: Session = Depends(get_db),
) -> OfficerDecisionRead:
    submission_service.get_owned_submission(db, submission_id, current_user.company_id)
    decision = officer_decision_service.record_decision(
        db, submission_id, current_user.id, payload.decision, payload.note
    )
    return OfficerDecisionRead.model_validate(decision)


@router.get("/submissions/{submission_id}/decision", response_model=OfficerDecisionRead | None)
def get_latest_decision(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OfficerDecisionRead | None:
    submission_service.get_owned_submission(db, submission_id, current_user.company_id)
    decision = officer_decision_service.get_latest_decision(db, submission_id)
    return OfficerDecisionRead.model_validate(decision) if decision is not None else None


@router.get("/submissions/{submission_id}/decision/history", response_model=list[OfficerDecisionRead])
def get_decision_history(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[OfficerDecisionRead]:
    submission_service.get_owned_submission(db, submission_id, current_user.company_id)
    history = officer_decision_service.get_decision_history(db, submission_id)
    return [OfficerDecisionRead.model_validate(d) for d in history]


# --- Bidder documents (Phase 4) ---
#
# Upload/list/category-correction/extraction/document-based verification
# all use the same require_sih_write_role / get_current_user split as
# every other write/read pair above -- see this module's docstring.


@router.post("/submissions/{submission_id}/documents", response_model=BidderDocumentRead)
async def upload_bidder_document(
    submission_id: uuid.UUID,
    file: UploadFile = File(...),
    category_code: str | None = Form(None),
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> BidderDocumentRead:
    document = await document_service.upload_bidder_document(
        db, submission_id, current_user.company_id, current_user.id, file, category_code
    )
    return BidderDocumentRead.model_validate(document)


@router.get("/submissions/{submission_id}/documents", response_model=list[BidderDocumentRead])
def list_bidder_documents(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[BidderDocumentRead]:
    documents = document_service.list_bidder_documents(db, submission_id, current_user.company_id)
    return [BidderDocumentRead.model_validate(d) for d in documents]


@router.delete("/submissions/{submission_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bidder_document(
    submission_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> None:
    """Removes a wrongly-uploaded document (row + stored file). Blocked if
    it's already the recorded evidence source for a verification result --
    see document_service.delete_bidder_document for the exact reasoning."""
    document_service.delete_bidder_document(db, submission_id, document_id, current_user.company_id)


@router.patch("/submissions/{submission_id}/documents/{document_id}/category", response_model=BidderDocumentRead)
def set_bidder_document_category(
    submission_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: SetDocumentCategoryRequest,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> BidderDocumentRead:
    document = document_service.set_document_category(
        db, submission_id, document_id, current_user.company_id, payload.category_code
    )
    return BidderDocumentRead.model_validate(document)


@router.post("/submissions/{submission_id}/documents/{document_id}/extract", response_model=BidderDocumentRead)
async def extract_bidder_document(
    submission_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> BidderDocumentRead:
    document = await document_service.extract_document(db, submission_id, document_id, current_user.company_id)
    return BidderDocumentRead.model_validate(document)


@router.post("/submissions/{submission_id}/documents/{document_id}/confirm", response_model=BidderDocumentRead)
def confirm_bidder_document(
    submission_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: ConfirmDocumentExtractionRequest,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> BidderDocumentRead:
    """
    The Phase 5 gate between "AI extracted this" and "this is now
    verification input" -- see document_service.confirm_document()'s
    docstring. Only an EXTRACTED document can be confirmed.
    """
    document = document_service.confirm_document(
        db, submission_id, document_id, current_user.company_id, current_user.id, payload.corrected_fields
    )
    return BidderDocumentRead.model_validate(document)


@router.post(
    "/submissions/{submission_id}/documents/{document_id}/authenticity-scan",
    response_model=AuthenticityScanRead,
)
def scan_document_authenticity(
    submission_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> AuthenticityScanRead:
    """
    Authenticity Scanner (Phase 2) -- inspects the document's actual
    stored file (metadata/basic consistency only, see
    app/services/sih/authenticity_service.py) and persists a new scan
    row. Gated require_sih_write_role like every other write here.
    """
    scan = authenticity_service.scan_document(
        db, submission_id, document_id, current_user.company_id, current_user.id
    )
    return AuthenticityScanRead.model_validate(scan)


@router.get(
    "/submissions/{submission_id}/documents/{document_id}/authenticity-scans",
    response_model=list[AuthenticityScanRead],
)
def list_document_authenticity_scans(
    submission_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AuthenticityScanRead]:
    # Ownership check via the same document lookup every other
    # document-scoped read uses -- raises NotFoundError if the document
    # isn't reachable from this caller's own company.
    document_service.get_owned_document(db, submission_id, document_id, current_user.company_id)
    scans = authenticity_service.list_scans(db, document_id)
    return [AuthenticityScanRead.model_validate(s) for s in scans]


@router.post("/submissions/{submission_id}/documents/verify", response_model=list[VerificationResultRead])
def verify_from_documents(
    submission_id: uuid.UUID,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> list[VerificationResultRead]:
    """
    Builds declared_facts from the submission's latest CONFIRMED documents
    (document_service.build_verification_inputs_from_documents -- never
    merely-EXTRACTED, unconfirmed documents; see that function and
    confirm_document's docstrings) and calls the SAME
    verification_service.verify_submission() the manual-entry
    POST .../verify endpoint already uses -- no second verification
    engine, per the Phase 4/5 briefs.
    """
    submission = submission_service.get_owned_submission(db, submission_id, current_user.company_id)
    bidder = submission_service.get_submission_bidder(db, submission)
    bidder_identity = {"pan": bidder.pan, "legal_name": bidder.legal_name, "trade_name": bidder.trade_name}
    declared_facts, source_documents = document_service.build_verification_inputs_from_documents(db, submission_id)
    results = verification_service.verify_submission(
        db, submission_id, bidder_identity, declared_facts, source_documents
    )
    return [VerificationResultRead.from_model(r) for r in results]


# --- Requirement-to-Evidence Mapping engine ---
#
# Upload/list gated the same require_sih_write_role / get_current_user
# split as every other write/read pair above: uploading a tender document
# runs a real LLM extraction call (same cost/risk profile as bidder
# document extraction), reads are open to any authenticated user in the
# company.


@router.post("/procurements/{procurement_id}/tender-document", response_model=ProcurementDocumentUploadResponse)
async def upload_tender_document(
    procurement_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> ProcurementDocumentUploadResponse:
    document, requirements = await procurement_requirement_service.upload_and_extract(
        db, procurement_id, current_user.company_id, file, current_user.id
    )
    return ProcurementDocumentUploadResponse(
        document=ProcurementDocumentRead.model_validate(document),
        requirements=[ProcurementRequirementRead.model_validate(r) for r in requirements],
    )


@router.get("/procurements/{procurement_id}/tender-documents", response_model=list[ProcurementDocumentRead])
def list_tender_documents(
    procurement_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProcurementDocumentRead]:
    documents = procurement_requirement_service.list_documents(db, procurement_id, current_user.company_id)
    return [ProcurementDocumentRead.model_validate(d) for d in documents]


@router.delete(
    "/procurements/{procurement_id}/tender-documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_tender_document(
    procurement_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> None:
    """Removes an uploaded tender document (row + stored file). Any
    ProcurementRequirement rows extracted from it survive with
    source_document_id cleared -- see
    procurement_requirement_service.delete_document for the exact
    reasoning."""
    procurement_requirement_service.delete_document(db, procurement_id, document_id, current_user.company_id)


@router.get("/procurements/{procurement_id}/requirements", response_model=list[ProcurementRequirementRead])
def list_procurement_requirements(
    procurement_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProcurementRequirementRead]:
    requirements = procurement_requirement_service.list_requirements(db, procurement_id, current_user.company_id)
    return [ProcurementRequirementRead.model_validate(r) for r in requirements]


@router.delete(
    "/procurements/{procurement_id}/requirements/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_procurement_requirement(
    procurement_id: uuid.UUID,
    requirement_id: uuid.UUID,
    current_user: User = Depends(require_sih_write_role),
    db: Session = Depends(get_db),
) -> None:
    """Removes a single extracted requirement row (e.g. an officer
    clearing a duplicate or mis-extracted line). No downstream rows
    reference a requirement's id, so this is a plain delete -- see
    procurement_requirement_service.delete_requirement."""
    procurement_requirement_service.delete_requirement(db, procurement_id, requirement_id, current_user.company_id)


@router.get(
    "/procurements/{procurement_id}/submissions/{submission_id}/requirement-mapping",
    response_model=list[RequirementEvidenceMapEntryRead],
)
def get_requirement_evidence_mapping(
    procurement_id: uuid.UUID,
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RequirementEvidenceMapEntryRead]:
    """
    Read-only derived view -- see
    procurement_requirement_service.get_requirement_evidence_map()'s
    docstring for exactly what each status means and why this never
    persists a new verdict.
    """
    entries = procurement_requirement_service.get_requirement_evidence_map(
        db, procurement_id, submission_id, current_user.company_id
    )
    return [RequirementEvidenceMapEntryRead.model_validate(e) for e in entries]
