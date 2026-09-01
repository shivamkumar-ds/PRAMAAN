import { apiClient } from "./client";
import type {
  ApprovalDecisionRequest,
  ApprovalHistoryResponse,
  AuthenticityScanRead,
  BidderCreateRequest,
  BidderDocumentRead,
  BidderRead,
  BidderUpdateRequest,
  ConfirmDocumentExtractionRequest,
  BidReadinessConfirmationRead,
  CapabilityGraphResponse,
  CollusionReportRead,
  ComplianceCategoryRead,
  ComplianceMatrixEntryRead,
  ComplianceSummaryRead,
  CompanyRead,
  CompanyUpdate,
  ContactRequest,
  ContactResponse,
  DeclaredFactsByCategory,
  DecisionRequest,
  DocumentRead,
  EvaluationResponse,
  GoogleLoginRequest,
  GroundingReportRead,
  LoginRequest,
  ManualCapabilityCreateRequest,
  MissionRead,
  NetworkGraphReportRead,
  OfficerDecisionRead,
  ProcurementCreateRequest,
  ProcurementDocumentRead,
  ProcurementDocumentUploadResponse,
  ProcurementRead,
  ProcurementRequirementRead,
  QualificationOverrideRead,
  RequirementEvidenceMapEntryRead,
  RegisterRequest,
  RevalidationResult,
  SetDocumentCategoryRequest,
  SubmissionRead,
  TenderDocumentRead,
  TenderMetadataGuess,
  TenderUploadResponse,
  TenderWithRequirements,
  TokenResponse,
  UserRead,
  VerificationResultRead,
  VerifyComplianceRequest,
} from "./types";

// --- auth ---

export const registerCompany = (payload: RegisterRequest) =>
  apiClient.post<TokenResponse>("/api/v1/auth/register", payload).then((r) => r.data);

export const login = (payload: LoginRequest) =>
  apiClient.post<TokenResponse>("/api/v1/auth/login", payload).then((r) => r.data);

export const getProfile = () => apiClient.get<UserRead>("/api/v1/auth/profile").then((r) => r.data);

// Login/link only -- fails cleanly (extractErrorMessage-surfaced) if no
// PRAMAAN account exists yet for the Google account's email. Never creates
// a Company; see backend/app/services/auth_service.py::login_with_google
// for the full reasoning.
export const googleLogin = (payload: GoogleLoginRequest) =>
  apiClient.post<TokenResponse>("/api/v1/auth/google", payload).then((r) => r.data);

// --- contact ---

// Public landing page "Contact Us" form -- no auth token required (and
// none is sent even if a stale one happens to be in localStorage; the
// backend endpoint ignores it either way).
export const submitContactForm = (payload: ContactRequest) =>
  apiClient.post<ContactResponse>("/api/v1/contact", payload).then((r) => r.data);

// --- company ---

export const getCompany = (companyId: string) =>
  apiClient.get<CompanyRead>(`/api/v1/company/${companyId}`).then((r) => r.data);

// Administrator-only server-side (403 for any other role) -- the frontend
// also gates the UI action to Administrator so a non-admin never sees an
// edit affordance that would just fail, but the real enforcement is the
// backend's require_administrator dependency.
export const updateCompany = (companyId: string, payload: CompanyUpdate) =>
  apiClient.patch<CompanyRead>(`/api/v1/company/${companyId}`, payload).then((r) => r.data);

// --- documents ---

export const listDocuments = () => apiClient.get<DocumentRead[]>("/api/v1/documents").then((r) => r.data);

export const uploadDocument = (file: File, documentType: string) => {
  const form = new FormData();
  form.append("document_type", documentType);
  form.append("file", file);
  return apiClient
    .post<DocumentRead>("/api/v1/documents/upload", form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

// Soft-delete (removed_at) + real file removal server-side. Blocked with a
// 409 if an active tender or an active capability entity still references
// this document -- extractErrorMessage() surfaces that reason to the user.
export const deleteDocument = (documentId: string) =>
  apiClient.delete<DocumentRead>(`/api/v1/documents/${documentId}`).then((r) => r.data);

// --- capabilities ---

export const getCapabilityGraph = () =>
  apiClient.get<CapabilityGraphResponse>("/api/v1/capabilities").then((r) => r.data);

export const buildCapability = (documentId: string, entityType: string) =>
  apiClient
    .post("/api/v1/capabilities/build", { document_id: documentId, entity_type: entityType })
    .then((r) => r.data);

// Admin-only server-side (require_administrator) -- already-existing
// endpoint (M9 revalidation), just not previously called from the
// frontend. Soft-removes the entity and re-runs the Decision Engine for
// any mission whose current recommendation cited it.
export const deleteCapability = (entityId: string) =>
  apiClient.delete(`/api/v1/capabilities/${entityId}`).then((r) => r.data);

// Manual capability creation -- no document, no LLM extraction. Admin-only
// server-side (require_administrator), supports all five entity types
// including Equipment and FinancialRecord (POST /build cannot create
// those two -- no extraction agent exists for them).
export const createCapabilityManual = (payload: ManualCapabilityCreateRequest) =>
  apiClient.post("/api/v1/capabilities/manual", payload).then((r) => r.data);

// Admin-only server-side (require_administrator) -- already-existing M9
// endpoint, now also whitelisted for Equipment/FinancialRecord fields (was
// previously Certification/Employee/Project only). Re-runs the Decision
// Engine for any mission whose current recommendation cites this entity,
// same as delete.
export const updateCapability = (entityId: string, fields: Record<string, unknown>) =>
  apiClient
    .patch<RevalidationResult>(`/api/v1/capabilities/${entityId}`, { fields })
    .then((r) => r.data);

// --- tenders ---

export const uploadTender = (
  file: File,
  fields: { tender_name?: string; organization?: string; category?: string; closing_date?: string }
) => {
  const form = new FormData();
  form.append("file", file);
  if (fields.tender_name) form.append("tender_name", fields.tender_name);
  if (fields.organization) form.append("organization", fields.organization);
  if (fields.category) form.append("category", fields.category);
  if (fields.closing_date) form.append("closing_date", fields.closing_date);
  return apiClient
    .post<TenderUploadResponse>("/api/v1/tenders/upload", form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

// Best-effort, heuristic-only prefill read of a just-selected PDF -- never
// persisted server-side. Any/all fields can come back null.
export const extractTenderMetadata = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return apiClient
    .post<TenderMetadataGuess>("/api/v1/tenders/extract-metadata", form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

export const getTender = (tenderId: string) =>
  apiClient.get<TenderWithRequirements>(`/api/v1/tenders/${tenderId}`).then((r) => r.data);

export const runAnalysis = (tenderId: string) =>
  apiClient
    .post<TenderWithRequirements>("/api/v1/analysis/run", { tender_id: tenderId })
    .then((r) => r.data);

// Attaches an additional source document (e.g. a technical bid detail
// spreadsheet, a BOQ) to an existing Tender -- multi-document Tender
// support. document_role is optional: the backend infers it from the
// filename ("boq"/"financial"/"price"/"commercial" -> financial, "tech"
// -> technical, else -> annexure) when omitted.
export const addTenderDocument = (tenderId: string, file: File, documentRole?: string) => {
  const form = new FormData();
  form.append("file", file);
  if (documentRole) form.append("document_role", documentRole);
  return apiClient
    .post<TenderDocumentRead>(`/api/v1/tenders/${tenderId}/documents`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

// --- evaluation / decision engine ---

export const runEvaluation = (missionId: string) =>
  apiClient.post<EvaluationResponse>("/api/v1/evaluation/run", { mission_id: missionId }).then((r) => r.data);

export const getEvaluation = (missionId: string) =>
  apiClient.get<EvaluationResponse>(`/api/v1/evaluation/${missionId}`).then((r) => r.data);

// --- missions ---

export const listMissions = () => apiClient.get<MissionRead[]>("/api/v1/missions").then((r) => r.data);

export const getMission = (missionId: string) =>
  apiClient.get<MissionRead>(`/api/v1/missions/${missionId}`).then((r) => r.data);

// Mission Orchestrator -- runs Tender Analysis (if not already done) and then
// Decision Intelligence evaluation, in one call, deciding what's needed from
// the mission/tender's own authoritative status. One action instead of two.
// `provider` selects which LLM engine runs this analysis -- only
// "openai" is accepted server-side right now (see ExecuteMissionRequest
// in the backend's mission schema); omitted falls back to the server's
// configured default, unchanged from before this parameter existed.
export const executeMission = (missionId: string, provider?: "openai") =>
  apiClient
    .post<MissionRead>(`/api/v1/missions/${missionId}/execute`, provider ? { provider } : undefined)
    .then((r) => r.data);

// Soft-delete (archive_mission -- flips status to "archived", never a real
// DELETE per the codebase's own Active/Archived/Deleted convention). This
// is what "delete tender" means in the UI: the mission/tender pair
// disappears from active views (Tender Workspace, Dashboard, Reports)
// but the row and its evaluation history survive.
export const archiveMission = (missionId: string) =>
  apiClient.delete<MissionRead>(`/api/v1/missions/${missionId}`).then((r) => r.data);

// Real, permanent deletion -- only succeeds server-side for an already-
// archived mission (mission_service.purge_mission's own ConflictError
// otherwise). Deliberately a separate call from archiveMission() above,
// not a flag on it: "hide it, recoverable" and "destroy it, irreversible"
// should never be one accidental parameter apart.
export const purgeMission = (missionId: string) =>
  apiClient.delete<void>(`/api/v1/missions/${missionId}/purge`).then(() => undefined);

// --- approval / Bid Decision ---
// "AI advises, human decides" -- this is the write path for the Bid
// Decision feature (docs/BID_DECISION_DESIGN.md). Backed by the existing
// Human Approval Layer (POST/GET /api/v1/approval), not a new endpoint --
// see that doc's §4 for why.

export const recordDecision = (payload: ApprovalDecisionRequest) =>
  apiClient.post<MissionRead>("/api/v1/approval", payload).then((r) => r.data);

export const getApprovalHistory = (missionId: string) =>
  apiClient.get<ApprovalHistoryResponse>(`/api/v1/approval/${missionId}`).then((r) => r.data);

// Atomic-layer override (CORE_ARCHITECTURE.md §7): a human verifying or
// rejecting one compliance row, independent of the mission-level Business
// Decision above. Returns the updated row so the caller can merge it back
// into local state without a full page refetch.
export const verifyComplianceRow = (complianceId: string, payload: VerifyComplianceRequest) =>
  apiClient
    .post<ComplianceMatrixEntryRead>(`/api/v1/compliance/${complianceId}/verify`, payload)
    .then((r) => r.data);

// --- bid-readiness confirmation ---
// Admin-only server-side (require_administrator) -- "Confirm Prepared" on
// a bid-readiness gap item (SUBMISSION_GATING/FUTURE_CONTRACTUAL_COMMITMENT
// nature). Never affects qualification -- see decision_engine.compute_qualification()'s
// boundary rule. Caller should refetch the evaluation after either call.
export const confirmRequirement = (missionId: string, requirementId: string, note?: string) =>
  apiClient
    .post<BidReadinessConfirmationRead>(
      `/api/v1/missions/${missionId}/requirements/${requirementId}/confirm`,
      note ? { note } : undefined
    )
    .then((r) => r.data);

export const unconfirmRequirement = (missionId: string, requirementId: string) =>
  apiClient
    .delete<void>(`/api/v1/missions/${missionId}/requirements/${requirementId}/confirm`)
    .then(() => undefined);

// --- qualification override ---
// Admin-only server-side (require_administrator) -- an explicit, audited
// risk acceptance on a mandatory CAPABILITY_CLAIM qualification gap,
// distinct from bid-readiness confirmation (see decision_engine.
// compute_qualification()'s overridden_requirement_ids boundary rule).
// note is REQUIRED (backend 422s on a blank one) -- this is a real
// decision, not a checkbox, and must always carry a reason. Caller
// should refetch the evaluation after either call.
export const overrideQualificationGap = (missionId: string, requirementId: string, note: string) =>
  apiClient
    .post<QualificationOverrideRead>(
      `/api/v1/missions/${missionId}/requirements/${requirementId}/override`,
      { note }
    )
    .then((r) => r.data);

export const removeQualificationOverride = (missionId: string, requirementId: string) =>
  apiClient
    .delete<void>(`/api/v1/missions/${missionId}/requirements/${requirementId}/override`)
    .then(() => undefined);

// ---------------------------------------------------------------------------
// SIH26100 -- Bidder Verification (Procurement Officer workflow, Phase 3).
// Reads use the same JWT auth as everything above; writes (create
// procurement/bidder/submission, run verification, record a decision) are
// require_administrator server-side -- see backend/app/api/v1/sih.py's own
// docstring on why ADMINISTRATOR stands in for a not-yet-modeled
// "Procurement Officer" role.
// ---------------------------------------------------------------------------

export const listProcurements = () =>
  apiClient.get<ProcurementRead[]>("/api/v1/sih/procurements").then((r) => r.data);

export const getProcurement = (procurementId: string) =>
  apiClient.get<ProcurementRead>(`/api/v1/sih/procurements/${procurementId}`).then((r) => r.data);

export const createProcurement = (payload: ProcurementCreateRequest) =>
  apiClient.post<ProcurementRead>("/api/v1/sih/procurements", payload).then((r) => r.data);

// Records this Procurement's awarded bidder -- Administrator/Executive
// only server-side (require_sih_award_role), since this feeds the
// Collusion Radar's repeated-winner indicator and is a business decision,
// not routine evidence-gathering. Requires at least one officer decision
// already recorded for this procurement (backend-enforced, 409 otherwise).
export const setProcurementAwardedBidder = (procurementId: string, bidderId: string) =>
  apiClient
    .patch<ProcurementRead>(`/api/v1/sih/procurements/${procurementId}/award`, { bidder_id: bidderId })
    .then((r) => r.data);

export const listBidders = () => apiClient.get<BidderRead[]>("/api/v1/sih/bidders").then((r) => r.data);

export const getBidder = (bidderId: string) =>
  apiClient.get<BidderRead>(`/api/v1/sih/bidders/${bidderId}`).then((r) => r.data);

export const createBidder = (payload: BidderCreateRequest) =>
  apiClient.post<BidderRead>("/api/v1/sih/bidders", payload).then((r) => r.data);

// Partial update -- primarily to fill in Bidder Network Graph identifiers
// (director/address/contact) for a bidder created before this engine
// existed. See backend/app/schemas/sih.py's BidderUpdateRequest.
export const updateBidder = (bidderId: string, payload: BidderUpdateRequest) =>
  apiClient.patch<BidderRead>(`/api/v1/sih/bidders/${bidderId}`, payload).then((r) => r.data);

// Bidder Network Graph (Phase 3) -- other bidders in this tenant sharing a
// real identifier with this one, and why. Never implies wrongdoing.
export const getBidderNetwork = (bidderId: string) =>
  apiClient.get<NetworkGraphReportRead>(`/api/v1/sih/bidders/${bidderId}/network`).then((r) => r.data);

export const listSubmissionsForProcurement = (procurementId: string) =>
  apiClient
    .get<SubmissionRead[]>(`/api/v1/sih/procurements/${procurementId}/submissions`)
    .then((r) => r.data);

export const createSubmission = (procurementId: string, bidderId: string, bidAmount?: number | null) =>
  apiClient
    .post<SubmissionRead>(`/api/v1/sih/procurements/${procurementId}/submissions`, {
      bidder_id: bidderId,
      bid_amount: bidAmount ?? null,
    })
    .then((r) => r.data);

export const setSubmissionBidAmount = (submissionId: string, bidAmount: number | null) =>
  apiClient
    .patch<SubmissionRead>(`/api/v1/sih/submissions/${submissionId}/bid-amount`, { bid_amount: bidAmount })
    .then((r) => r.data);

// Collusion Radar (Phase 4) -- transparent heuristic indicators over a
// procurement's bid values and bidder participation history. Never states
// collusion as confirmed; always carries CollusionReportRead.disclaimer.
export const getProcurementCollusionRadar = (procurementId: string) =>
  apiClient
    .get<CollusionReportRead>(`/api/v1/sih/procurements/${procurementId}/collusion-radar`)
    .then((r) => r.data);

export const getSubmission = (submissionId: string) =>
  apiClient.get<SubmissionRead>(`/api/v1/sih/submissions/${submissionId}`).then((r) => r.data);

export const listComplianceCategories = () =>
  apiClient.get<ComplianceCategoryRead[]>("/api/v1/sih/compliance-categories").then((r) => r.data);

// declaredFacts is keyed by ComplianceCategory.code -- the officer
// supplies what the bidder declared directly. The request is
// multipart/form-data (not a plain JSON body) so an officer can
// optionally attach one supporting document to a single declared
// category in the same request -- see backend app/api/v1/sih.py's
// verify_submission for why (a file part can't ride along with a JSON
// body). attachment/attachmentCategoryCode are both optional and must
// be provided together; omitting them declares facts exactly as before
// (backward compatible), with no document evidence attached.
export const runVerification = (
  submissionId: string,
  declaredFacts: DeclaredFactsByCategory,
  attachment?: { file: File; categoryCode: string }
) => {
  const form = new FormData();
  form.append("declared_facts", JSON.stringify(declaredFacts));
  if (attachment) {
    form.append("attachment", attachment.file);
    form.append("attachment_category_code", attachment.categoryCode);
  }
  return apiClient
    .post<VerificationResultRead[]>(`/api/v1/sih/submissions/${submissionId}/verify`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

export const getSubmissionVerification = (submissionId: string) =>
  apiClient
    .get<VerificationResultRead[]>(`/api/v1/sih/submissions/${submissionId}/verification`)
    .then((r) => r.data);

export const getSubmissionSummary = (submissionId: string) =>
  apiClient.get<ComplianceSummaryRead>(`/api/v1/sih/submissions/${submissionId}/summary`).then((r) => r.data);

// Evidence Grounding Guard (Phase 1b) -- classifies every latest
// verification result by where its evidence actually came from. See
// backend/app/services/sih/grounding_guard_service.py.
export const getSubmissionGrounding = (submissionId: string) =>
  apiClient.get<GroundingReportRead>(`/api/v1/sih/submissions/${submissionId}/grounding`).then((r) => r.data);

// note is REQUIRED -- backend rejects a blank/whitespace-only note with a
// 422 (same discipline as qualification override's note above).
export const recordOfficerDecision = (submissionId: string, payload: DecisionRequest) =>
  apiClient
    .post<OfficerDecisionRead>(`/api/v1/sih/submissions/${submissionId}/decision`, payload)
    .then((r) => r.data);

export const getLatestOfficerDecision = (submissionId: string) =>
  apiClient
    .get<OfficerDecisionRead | null>(`/api/v1/sih/submissions/${submissionId}/decision`)
    .then((r) => r.data);

export const getOfficerDecisionHistory = (submissionId: string) =>
  apiClient
    .get<OfficerDecisionRead[]>(`/api/v1/sih/submissions/${submissionId}/decision/history`)
    .then((r) => r.data);

// --- Bidder documents (Phase 4) ---
//
// Same FormData/multipart convention as uploadDocument/uploadTender above.
// categoryCode is optional -- an officer may leave it unset and let
// extract() classify it (see BidderDocumentRead.category_source).

export const uploadBidderDocument = (submissionId: string, file: File, categoryCode?: string | null) => {
  const form = new FormData();
  form.append("file", file);
  if (categoryCode) form.append("category_code", categoryCode);
  return apiClient
    .post<BidderDocumentRead>(`/api/v1/sih/submissions/${submissionId}/documents`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

export const listBidderDocuments = (submissionId: string) =>
  apiClient.get<BidderDocumentRead[]>(`/api/v1/sih/submissions/${submissionId}/documents`).then((r) => r.data);

// Hard delete (row + stored file) -- for the common "wrong file uploaded"
// case. Backend blocks (409) if the document is already the recorded
// evidence source for a VerificationResult; see document_service.delete_bidder_document.
export const deleteBidderDocument = (submissionId: string, documentId: string) =>
  apiClient.delete<void>(`/api/v1/sih/submissions/${submissionId}/documents/${documentId}`).then(() => undefined);

export const setBidderDocumentCategory = (submissionId: string, documentId: string, payload: SetDocumentCategoryRequest) =>
  apiClient
    .patch<BidderDocumentRead>(`/api/v1/sih/submissions/${submissionId}/documents/${documentId}/category`, payload)
    .then((r) => r.data);

export const extractBidderDocument = (submissionId: string, documentId: string) =>
  apiClient
    .post<BidderDocumentRead>(`/api/v1/sih/submissions/${submissionId}/documents/${documentId}/extract`)
    .then((r) => r.data);

// The Phase 5 gate: an EXTRACTED document's fields only become
// verification input once the officer confirms them here (optionally
// with corrected_fields). See backend document_service.confirm_document().
export const confirmBidderDocument = (submissionId: string, documentId: string, payload: ConfirmDocumentExtractionRequest) =>
  apiClient
    .post<BidderDocumentRead>(`/api/v1/sih/submissions/${submissionId}/documents/${documentId}/confirm`, payload)
    .then((r) => r.data);

// Builds declared_facts server-side from the submission's latest EXTRACTED
// documents and runs the SAME verify_submission() the manual-entry
// runVerification() above calls -- no second verification result shape.
export const verifyFromDocuments = (submissionId: string) =>
  apiClient
    .post<VerificationResultRead[]>(`/api/v1/sih/submissions/${submissionId}/documents/verify`)
    .then((r) => r.data);

// Authenticity Scanner (Phase 2) -- inspects the document's actual stored
// file (metadata/basic consistency only). Never a forensic verdict. See
// backend/app/services/sih/authenticity_service.py.
export const scanDocumentAuthenticity = (submissionId: string, documentId: string) =>
  apiClient
    .post<AuthenticityScanRead>(`/api/v1/sih/submissions/${submissionId}/documents/${documentId}/authenticity-scan`)
    .then((r) => r.data);

export const listDocumentAuthenticityScans = (submissionId: string, documentId: string) =>
  apiClient
    .get<AuthenticityScanRead[]>(`/api/v1/sih/submissions/${submissionId}/documents/${documentId}/authenticity-scans`)
    .then((r) => r.data);

// --- Requirement-to-Evidence Mapping engine ---
// See backend/app/services/sih/procurement_requirement_service.py.

export const uploadTenderDocument = (procurementId: string, file: File) => {
  const form = new FormData();
  form.append("file", file);
  return apiClient
    .post<ProcurementDocumentUploadResponse>(`/api/v1/sih/procurements/${procurementId}/tender-document`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

export const listProcurementRequirements = (procurementId: string) =>
  apiClient
    .get<ProcurementRequirementRead[]>(`/api/v1/sih/procurements/${procurementId}/requirements`)
    .then((r) => r.data);

export const listTenderDocuments = (procurementId: string) =>
  apiClient
    .get<ProcurementDocumentRead[]>(`/api/v1/sih/procurements/${procurementId}/tender-documents`)
    .then((r) => r.data);

export const deleteTenderDocument = (procurementId: string, documentId: string) =>
  apiClient
    .delete<void>(`/api/v1/sih/procurements/${procurementId}/tender-documents/${documentId}`)
    .then(() => undefined);

export const deleteProcurementRequirement = (procurementId: string, requirementId: string) =>
  apiClient
    .delete<void>(`/api/v1/sih/procurements/${procurementId}/requirements/${requirementId}`)
    .then(() => undefined);

// Read-only derived view -- never a new persisted verdict. See
// procurement_requirement_service.get_requirement_evidence_map().
export const getRequirementEvidenceMapping = (procurementId: string, submissionId: string) =>
  apiClient
    .get<RequirementEvidenceMapEntryRead[]>(
      `/api/v1/sih/procurements/${procurementId}/submissions/${submissionId}/requirement-mapping`
    )
    .then((r) => r.data);
