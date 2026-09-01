// Types mirror the real /openapi.json schema exactly (fetched and confirmed
// against the running backend, not guessed). Keep in sync if the backend
// contract changes -- per the MVP brief, that should be a rare, deliberate
// event, not a silent drift.

export type UserRole = "administrator" | "executive" | "bid_manager" | "reviewer" | "auditor";
export type UserStatus = "active" | "inactive";
export type DocumentProcessingStatus = "pending" | "processing" | "completed" | "failed";
export type RequirementType =
  | "eligibility"
  | "technical"
  | "certification"
  | "experience"
  | "evaluation_criteria"
  | "deadline"
  | "submission";
export type MatchStatus = "met" | "not_met" | "review_required" | "conditional";
export type RiskLevel = "low" | "medium" | "high" | "critical";
export type RecommendationType = "go" | "conditional_go" | "review" | "no_go";
// Architecture debate Phase 1 -- what KIND of unresolved requirement this
// is (orthogonal to RequirementType, which is what SECTION of the tender
// it came from). Nullable on older/legacy requirements extracted before
// this field existed; always present on anything extracted going forward.
export type RequirementNature =
  | "capability_claim"
  | "submission_gating"
  | "procedural"
  | "future_contractual_commitment";
// Architecture debate Phase 2/5 -- derived evaluation states computed
// server-side by decision_engine.compute_qualification()/
// compute_bid_readiness(); never independently recomputed on the frontend.
export type QualificationStatus = "pass" | "conditional" | "fail";
export type ReadinessStatus = "ready" | "action_required" | "blocked";
export type MissionStatus = "created" | "running" | "awaiting_approval" | "completed" | "archived";
// The human's Business Decision (Bid Decision feature) -- deliberately a
// separate vocabulary from RecommendationType (the AI's own output). "AI
// advises, human decides": these values are never the AI's to choose.
export type BusinessDecision = "proceed" | "rejected" | "needs_revision";
export type CapabilityEntityType = "certification" | "employee" | "project" | "equipment" | "financial_record";
export type VerificationStatus = "pending" | "verified" | "expired" | "review_required";

export interface UserRead {
  id: string;
  company_id: string;
  name: string;
  email: string;
  role: UserRole;
  status: UserStatus;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: UserRead;
}

export interface RegisterRequest {
  company_name: string;
  industry?: string | null;
  registration_number: string;
  country?: string | null;
  admin_name: string;
  admin_email: string;
  admin_password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

// POST /api/v1/auth/google -- id_token is the credential Google Identity
// Services hands back to the frontend after the user picks an account;
// verified server-side (signature, expiry, audience), never trusted as-is.
// Login/link only: fails with a clean error if no PRAMAAN account exists
// for the Google account's email -- this never creates a Company.
export interface GoogleLoginRequest {
  id_token: string;
}

// POST /api/v1/contact -- the public landing page's "Contact Us" form.
// Unauthenticated by design (a visitor submitting this has, by
// definition, no PRAMAAN account yet). `website` is a honeypot: a hidden
// field a real visitor never sees or fills (see ContactSection.tsx) --
// always sent as an empty string by the real form.
export interface ContactRequest {
  full_name: string;
  work_email: string;
  company_name?: string | null;
  job_title?: string | null;
  phone?: string | null;
  subject: string;
  message: string;
  website?: string;
}

export interface ContactResponse {
  id: string;
  created_at: string;
}

export interface CompanyRead {
  id: string;
  name: string;
  industry?: string | null;
  registration_number: string;
  country?: string | null;
  created_at: string;
  updated_at: string;
}

// PATCH /api/v1/company/{id} -- Administrator-only. Deliberately excludes
// registration_number: that's the tenant's legal/uniqueness identity, not
// an ordinary editable detail (see backend app/schemas/company.py's
// CompanyUpdate docstring). All fields optional -- only send what
// actually changed; omitted fields are left untouched server-side.
export interface CompanyUpdate {
  name?: string;
  industry?: string | null;
  country?: string | null;
}

export interface DocumentRead {
  id: string;
  company_id: string;
  uploaded_by: string;
  document_type: string;
  file_name: string;
  upload_time: string;
  version: number;
  processing_status: DocumentProcessingStatus;
}

export interface CapabilitySummary {
  total_entities: number;
  total_expired: number;
  total_stale: number;
  total_current: number;
  by_domain: Record<string, number>;
}

interface CapabilityCommon {
  id: string;
  company_id: string;
  confidence_score: number | null;
  source_document_id: string | null;
  verification_status: VerificationStatus;
  freshness_status: string;
  is_expired: boolean;
  is_stale: boolean;
  created_at: string;
}

export interface CertificationEntry extends CapabilityCommon {
  certification_name: string;
  issuing_authority: string | null;
  issue_date: string | null;
  expiry_date: string | null;
}

export interface EmployeeEntry extends CapabilityCommon {
  name: string;
  position: string | null;
  qualification: string | null;
  experience: string | null;
  skills: string[] | null;
}

export interface ProjectEntry extends CapabilityCommon {
  client: string | null;
  industry: string | null;
  contract_value: number | null;
  duration: string | null;
  completion_status: string | null;
  // Was already returned by the backend (ProjectRead.similarity_tags) but
  // missing from this type -- pre-existing drift, not a new field.
  similarity_tags: string[] | null;
}

export interface EquipmentEntry extends CapabilityCommon {
  equipment_name: string;
  category: string | null;
  quantity: number | null;
}

export interface FinancialRecordEntry extends CapabilityCommon {
  financial_year: number | null;
  revenue: number | null;
  net_worth: number | null;
  credit_rating: string | null;
}

export interface CapabilityGraphResponse {
  summary: CapabilitySummary;
  certifications: CertificationEntry[];
  employees: EmployeeEntry[];
  projects: ProjectEntry[];
  equipment: EquipmentEntry[];
  financial_records: FinancialRecordEntry[];
}

export interface RequirementRead {
  id: string;
  tender_id: string;
  requirement_type: RequirementType;
  description: string | null;
  mandatory: boolean;
  source_page: number | null;
  // Which attached document this requirement came from, and where in it
  // (e.g. "Sheet: Sheet1" for a spreadsheet-sourced requirement) --
  // multi-document Tender support. May be null for requirements extracted
  // before this feature existed.
  source_document_id: string | null;
  source_location: string | null;
  confidence: number | null;
}

export interface TenderRead {
  id: string;
  mission_id: string;
  tender_name: string | null;
  organization: string | null;
  category: string | null;
  closing_date: string | null;
  uploaded_document: string | null;
  processing_status: string | null;
}

// One document attached to a Tender -- the main PDF or any additional
// technical/financial/annexure document (multi-document Tender support).
export type TenderDocumentRole = "main" | "technical" | "financial" | "annexure" | string;

export interface TenderDocumentRead {
  id: string;
  file_name: string;
  document_role: TenderDocumentRole | null;
  upload_time: string;
}

export interface TenderWithRequirements {
  tender: TenderRead;
  requirements: RequirementRead[];
  documents: TenderDocumentRead[];
}

// Response for POST /tenders/extract-metadata -- heuristic-only (regex, no
// LLM call) best-effort read of a just-selected PDF, purely to prefill the
// New Tender form. Never persisted; any/all fields can come back null.
export interface TenderMetadataGuess {
  tender_name: string | null;
  organization: string | null;
  closing_date: string | null;
}

// The upload-tender endpoint's response is loosely typed in the OpenAPI spec
// (additionalProperties: true) rather than a named schema -- treat it
// defensively, but it should carry at least id + mission_id like TenderRead.
export interface TenderUploadResponse {
  tender_id: string;
  mission_id: string;
  tender_name?: string | null;
  organization?: string | null;
  closing_date?: string | null;
  [key: string]: unknown;
}

// Resolves ComplianceMatrixEntryRead.evidence_reference (an opaque
// CapabilityMapping id) into the actual company record + source document
// that grounds a recommendation -- the "Company Document" leg of the
// Decision Screen's signature evidence trail (DESIGN_SYSTEM.md §10).
export interface EvidenceSourceRead {
  entity_type: CapabilityEntityType;
  label: string;
  source_document_id: string | null;
  source_document_name: string | null;
}

// Excludes "pending" where the value is being set BY a human (that's the
// starting state, not a target one -- same rule the backend's
// VerifyComplianceRequest validator already enforces).
export type ComplianceMatrixVerificationStatus = "pending" | "verified_compliant" | "verified_non_compliant" | "escalated";
export type VerificationDecision = Exclude<ComplianceMatrixVerificationStatus, "pending">;

export interface ComplianceMatrixEntryRead {
  id: string;
  requirement_id: string;
  status: MatchStatus;
  supporting_evidence: string | null;
  notes: string | null;
  requires_verification: boolean;
  verification_reason: string | null;
  risk_level: RiskLevel | null;
  verification_status: ComplianceMatrixVerificationStatus;
  matching_confidence: number | null;
  evidence_reference: string | null;
  // "Source Clause" leg -- which tender document page this requirement came
  // from. "Company Document" leg -- which company record + upload backs it.
  source_page: number | null;
  evidence_source: EvidenceSourceRead | null;
  // Verification metadata (Compliance Verification UI). Never render
  // verified_by (a raw user id) directly -- verified_by_name is the
  // resolved display name, added specifically so the badge never has to
  // say "by you" for a mission another user opens later.
  verified_by: string | null;
  verified_by_name: string | null;
  verified_at: string | null;
}

// POST /api/v1/compliance/{id}/verify
export interface VerifyComplianceRequest {
  verification_status: VerificationDecision;
  note: string | null;
}

export interface GapAnalysisEntry {
  requirement_id: string;
  requirement_type: RequirementType;
  description: string | null;
  mandatory: boolean;
  status: MatchStatus;
  reason: string | null;
  source_page: number | null;
  // Architecture debate Phase 5 additions -- populated from
  // decision_engine.reconstruct_match_result() (see backend
  // app/schemas/decision.py's GapAnalysisEntry docstring). Both nullable/
  // defaulted-empty since older requirements predate requirement_nature
  // (Phase 1) and most requirements resolve to zero unsupported domains.
  requirement_nature: RequirementNature | null;
  unsupported_domains: CapabilityEntityType[];
  // Bid-readiness confirmation feature -- whether a human has confirmed
  // this item (a SUBMISSION_GATING/FUTURE_CONTRACTUAL_COMMITMENT gap) is
  // actually prepared. The item stays in its bucket either way (never
  // dropped) -- confirmed just changes how it's displayed and whether it
  // still counts as "unresolved" in remediation_summary.bid_readiness.
  confirmed: boolean;
  confirmed_at: string | null;
  // Qualification override feature -- whether an administrator has
  // explicitly overridden this item (a mandatory CAPABILITY_CLAIM
  // qualification gap) despite no real capability evidence existing for
  // it yet. Unlike `confirmed` (an already-true fact), `overridden`
  // represents an explicit, audited risk acceptance -- render it
  // visually distinct from "requirement met," never absorbed into it.
  overridden: boolean;
  overridden_by: string | null;
  overridden_by_name: string | null;
  overridden_at: string | null;
  override_note: string | null;
}

// Architecture debate Phase 5 -- the single deterministic backend
// representation of "what does this evaluation actually require, and
// why" (app/schemas/decision.py's RemediationSummary). The frontend/PDF
// render these buckets directly; they do not independently reclassify
// gap_analysis entries into qualification/readiness/coverage/review
// groups -- that decision is made once, server-side, by
// decision_engine.classify_remediation().
export interface RemediationSummary {
  qualification: QualificationStatus;
  qualification_gaps: GapAnalysisEntry[];

  bid_readiness: ReadinessStatus;
  blocked_items: GapAnalysisEntry[];
  action_required_items: GapAnalysisEntry[];

  coverage_gaps: GapAnalysisEntry[];

  human_review_items: GapAnalysisEntry[];

  // Architecture debate Phase 6 (REVIEW-explainability gap) -- non-
  // mandatory CAPABILITY_CLAIM requirements with a definitive NOT_MET
  // verdict. Not a qualification risk (qualification only ever looks at
  // mandatory items) and not ambiguous (NOT_MET is definitive, nothing
  // for a human to adjudicate) -- but the one item shape that can push
  // `recommendation.recommendation_type` to "review" (via the backend's
  // settings.max_optional_review_items threshold) while contributing to
  // no other bucket here. Render this directly; never recompute the
  // threshold or re-derive this set from gap_analysis/compliance_matrix
  // client-side -- see decision_engine.classify_remediation()'s
  // docstring for the exhaustive backend-side proof that this is the
  // only such item shape.
  optional_capability_gaps: GapAnalysisEntry[];
}

export interface RecommendationRead {
  id: string;
  mission_id: string;
  recommendation_type: RecommendationType;
  executive_summary: string | null;
  risk_level: RiskLevel | null;
  generated_at: string;
  document_confidence: number | null;
  entity_confidence: number | null;
  matching_confidence: number | null;
  recommendation_confidence: number | null;
  overall_confidence: number | null;
  snapshot_id: string | null;
}

export interface EvaluationResponse {
  recommendation: RecommendationRead;
  compliance_matrix: ComplianceMatrixEntryRead[];
  gap_analysis: GapAnalysisEntry[];
  // Required, not optional -- the deployed backend contract (Phase 5)
  // guarantees this is always populated on every EvaluationResponse.
  // Do not add a fallback/degraded path for its absence; see the Phase 6
  // inspection report's discussion of backward compatibility.
  remediation_summary: RemediationSummary;
}

export interface MissionRead {
  id: string;
  company_id: string;
  user_id: string;
  mission_type: string;
  status: MissionStatus;
  created_at: string;
  completed_at: string | null;
  recommendation_id: string | null;
  capability_snapshot_id: string | null;
  actual_outcome: string | null;
  outcome_notes: string | null;
  // Real tender identity, resolved server-side from the linked Tender row
  // (user-entered tender name, falling back to the uploaded file name) --
  // mission_type is always the fixed constant "tender_evaluation" and was
  // never a tender name. Only populated by GET /missions and
  // GET /missions/:id; null on other mission action responses.
  tender_id: string | null;
  tender_name: string | null;
}

// --- Bid-readiness confirmation ---
// POST/DELETE /api/v1/missions/{mission_id}/requirements/{requirement_id}/confirm

export interface BidReadinessConfirmationRead {
  id: string;
  requirement_id: string;
  confirmed_by: string;
  confirmed_at: string;
  note: string | null;
}

// --- Qualification override ---
// POST/DELETE /api/v1/missions/{mission_id}/requirements/{requirement_id}/override
// Distinct from bid-readiness confirmation -- see GapAnalysisEntry.overridden's
// own comment. A real, audited administrator risk-acceptance, not a
// confirmation of an already-true fact; note is REQUIRED at creation time.
export interface QualificationOverrideRead {
  id: string;
  requirement_id: string;
  overridden_by: string;
  overridden_at: string;
  note: string | null;
}

// --- Manual capability creation -- POST /api/v1/capabilities/manual ---
// No document required, admin-gated. Supports all five entity types
// (unlike POST /capabilities/build, which only supports the three with a
// document-extraction agent). `fields` is intentionally loose (matches
// the backend's ManualCapabilityCreateRequest.fields dict[str, Any]) --
// per-entity-type validation happens server-side.
export interface ManualCapabilityCreateRequest {
  entity_type: CapabilityEntityType;
  fields: Record<string, unknown>;
}

// --- Capability field update -- PATCH /api/v1/capabilities/{id} ---
// Pre-existing M9 endpoint (revalidation_service.handle_capability_update),
// generic across all five entity types via capability_service.PATCHABLE_FIELDS
// -- only just extended to cover Equipment/FinancialRecord. `fields` mirrors
// the same loose dict[str, Any] shape as manual creation; unknown/unpatchable
// field names 422 server-side.
export interface CapabilityUpdateRequest {
  fields: Record<string, unknown>;
}

export interface RevalidationResult {
  entity_id: string;
  changed_fields: string[];
  affected_missions: string[];
  new_recommendations: string[];
}

// --- Bid Decision (Human Approval Layer -- POST/GET /api/v1/approval) ---

export interface ApprovalDecisionRequest {
  mission_id: string;
  decision: BusinessDecision;
  // Required server-side when decision === "rejected"; optional otherwise.
  reason: string | null;
}

export interface DecisionEventRead {
  user_id: string | null;
  event: string;
  result: string | null;
  timestamp: string;
  // Additive (TENDER_JOURNEY_IMPLEMENTATION_PLAN.md Phase 6) -- resolved
  // server-side from user_id, same pattern as
  // ComplianceMatrixEntryRead.verified_by_name.
  user_name: string | null;
}

export interface ApprovalHistoryResponse {
  mission: MissionRead;
  recommendation: RecommendationRead;
  compliance_matrix: ComplianceMatrixEntryRead[];
  decision_events: DecisionEventRead[];
}

export interface ApiErrorDetail {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export interface ApiValidationError {
  detail: ApiErrorDetail[];
}

// ---------------------------------------------------------------------------
// SIH26100 -- Bidder Verification domain (Phase 2 backend, Phase 3 frontend).
// Deliberately a separate vocabulary from Tender/Requirement/Mission above
// -- a Procurement is not a Tender, a BidderSubmission is not a Mission.
// See backend/app/schemas/sih.py for the source of truth these mirror.
// ---------------------------------------------------------------------------

export type ProcurementStatus = "open" | "closed" | "archived";
export type SubmissionStatus = "submitted" | "under_review" | "decided";
export type ComplianceVerificationStatus =
  | "verified"
  | "mismatch"
  | "missing"
  | "not_applicable"
  | "not_claimed"
  | "critical_fail";
export type OfficerDecisionType = "approve" | "reject" | "request_clarification";
// RiskLevel ("low" | "medium" | "high" | "critical") already exists above
// and is reused as-is -- SIH's compliance_summary_service produces exactly
// this same vocabulary.

export interface ProcurementRead {
  id: string;
  company_id: string;
  title: string;
  organization: string | null;
  reference_number: string | null;
  category: string | null;
  closing_date: string | null;
  status: ProcurementStatus;
  // Collusion Radar repeat-winner signal -- which Bidder (if any) this
  // Procurement was awarded to. null until an officer explicitly sets it
  // via PATCH .../procurements/{id}/award -- never inferred.
  awarded_bidder_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProcurementCreateRequest {
  title: string;
  organization?: string | null;
  reference_number?: string | null;
  category?: string | null;
  closing_date?: string | null;
}

export interface BidderRead {
  id: string;
  company_id: string;
  legal_name: string;
  trade_name: string | null;
  pan: string | null;
  // SIH26100 demo-scope expansion (Bidder Network Graph) -- optional
  // identifiers used to find shared-identifier relationships between
  // bidders. See network_graph_service.py.
  registered_address: string | null;
  director_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  created_at: string;
  updated_at: string;
}

export interface BidderCreateRequest {
  legal_name: string;
  trade_name?: string | null;
  pan?: string | null;
  registered_address?: string | null;
  director_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
}

export interface BidderUpdateRequest {
  legal_name?: string;
  trade_name?: string | null;
  pan?: string | null;
  registered_address?: string | null;
  director_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
}

export interface SubmissionRead {
  id: string;
  procurement_id: string;
  bidder_id: string;
  status: SubmissionStatus;
  // SIH26100 demo-scope expansion (Collusion Radar) -- the bidder's
  // quoted price. Null when not yet entered; a submission with no
  // bid_amount is simply excluded from value-based collusion heuristics.
  bid_amount: number | null;
  created_at: string;
  updated_at: string;
}

export interface ComplianceCategoryRead {
  id: string;
  code: string;
  name: string;
  description: string | null;
  mandatory_by_default: boolean;
  risk_weight: number;
  is_active: boolean;
}

// Keyed by ComplianceCategory.code (e.g. "udyam", "gst") -- exactly what
// POST /sih/submissions/{id}/verify expects. No document/OCR pipeline yet
// (Phase 4), so this is filled in directly by the officer for now.
export type DeclaredFactsByCategory = Record<string, Record<string, unknown>>;

export interface VerificationResultRead {
  id: string;
  submission_id: string;
  category_id: string;
  category_code: string;
  category_name: string;
  mandatory: boolean;
  status: ComplianceVerificationStatus;
  critical: boolean;
  declared_value: Record<string, unknown> | null;
  registry_value: Record<string, unknown> | null;
  discrepancies: string[] | null;
  confidence: number | null;
  source: string;
  reason: string | null;
  checked_at: string;
  // Phase 5 evidence linking -- which confirmed BidderDocument (if any)
  // produced this row's declared_value. Both null for the manual-entry
  // verify path and for document-independent categories (blacklisting).
  source_document_id: string | null;
  source_document_name: string | null;
}

export interface MandatoryComplianceIssueRead {
  category_code: string;
  category_name: string;
  status: ComplianceVerificationStatus;
  reason: string | null;
  source_document_id: string | null;
  source_document_name: string | null;
}

export interface ComplianceSummaryRead {
  total_applicable: number;
  verified_count: number;
  failed_count: number;
  missing_count: number;
  critical_count: number;
  review_count: number;
  compliance_score: number;
  risk_level: RiskLevel;
  critical_categories: string[];
  mandatory_issues: MandatoryComplianceIssueRead[];
}

export interface DecisionRequest {
  decision: OfficerDecisionType;
  note: string;
}

export interface OfficerDecisionRead {
  id: string;
  submission_id: string;
  officer_id: string;
  decision: OfficerDecisionType;
  note: string;
  decided_at: string;
}

// --- Bidder documents (Phase 4) ---
//
// AI extraction only ever populates BidderDocumentRead.extracted_data --
// it never decides ComplianceVerificationStatus. See backend/app/schemas/
// sih.py's BidderDocumentRead (storage_path is deliberately never exposed
// here -- no local filesystem path ever reaches the frontend).

export type DocumentExtractionStatus = "pending" | "processing" | "extracted" | "review_required" | "failed";

export interface BidderDocumentRead {
  id: string;
  submission_id: string;
  category_code: string | null;
  category_source: string; // "officer" | "auto" | "unclassified"
  file_name: string;
  uploaded_at: string;
  extraction_status: DocumentExtractionStatus;
  extracted_data: Record<string, unknown> | null;
  extraction_confidence: number | null;
  extraction_error: string | null;
  extracted_at: string | null;
  // Phase 5 -- AI extraction alone is never authoritative; is_confirmed
  // gates whether confirmed_data (possibly officer-corrected) actually
  // reaches verification. See POST .../documents/{id}/confirm.
  is_confirmed: boolean;
  confirmed_data: Record<string, unknown> | null;
  confirmed_at: string | null;
  manually_corrected: boolean;
}

export interface SetDocumentCategoryRequest {
  category_code: string;
}

export interface ConfirmDocumentExtractionRequest {
  corrected_fields?: Record<string, unknown> | null;
}

// --- Evidence Grounding Guard (Phase 1b) ---
// See backend/app/services/sih/grounding_guard_service.py.

export type GroundingOrigin = "document_evidence" | "manual_declaration" | "no_evidence";

export interface CategoryGroundingRead {
  category_code: string;
  category_name: string;
  status: ComplianceVerificationStatus;
  origin: GroundingOrigin;
  source_document_id: string | null;
  source_document_name: string | null;
}

export interface GroundingReportRead {
  submission_id: string;
  categories: CategoryGroundingRead[];
  document_evidenced_count: number;
  manual_declaration_count: number;
  no_evidence_count: number;
}

// --- Authenticity Scanner (Phase 2) ---
// Metadata/consistency indicators only -- never a forensic verdict. See
// backend/app/services/sih/authenticity_service.py.

export type AuthenticitySeverity = "info" | "low" | "medium" | "high";
export type AuthenticitySummaryLabel = "no_anomalies_detected" | "indicators_present" | "not_analyzable";

export interface AuthenticityIndicatorRead {
  code: string;
  label: string;
  detail: string;
  severity: AuthenticitySeverity;
}

export interface AuthenticityScanRead {
  id: string;
  document_id: string;
  indicators: AuthenticityIndicatorRead[];
  summary_label: AuthenticitySummaryLabel;
  scanned_by: string;
  scanned_at: string;
}

// --- Bidder Network Graph (Phase 3) ---
// Shared-identifier relationships only -- never implies wrongdoing. See
// backend/app/services/sih/network_graph_service.py.

export interface RelatedBidderRead {
  bidder_id: string;
  legal_name: string;
  trade_name: string | null;
  reasons: string[];
}

export interface NetworkGraphReportRead {
  bidder_id: string;
  bidder_legal_name: string;
  related_bidders: RelatedBidderRead[];
}

// --- Collusion Radar (Phase 4) ---
// Transparent heuristic indicators only -- collusion is never stated as
// confirmed. See backend/app/services/sih/collusion_radar_service.py.

export interface CollusionIndicatorRead {
  code: string;
  label: string;
  detail: string;
  severity: AuthenticitySeverity;
}

export interface CollusionReportRead {
  procurement_id: string;
  indicators: CollusionIndicatorRead[];
  score: number;
  disclaimer: string;
}

// --- Requirement-to-Evidence Mapping engine ---
// See backend/app/services/sih/procurement_requirement_service.py.

export type ProcurementDocumentExtractionStatus = "pending" | "extracted" | "failed";

export interface ProcurementDocumentRead {
  id: string;
  procurement_id: string;
  original_filename: string;
  mime_type: string | null;
  file_size_bytes: number | null;
  extraction_status: ProcurementDocumentExtractionStatus;
  extraction_error: string | null;
  uploaded_at: string;
  uploaded_by: string | null;
}

export interface ProcurementRequirementRead {
  id: string;
  procurement_id: string;
  source_document_id: string | null;
  requirement_text: string;
  // Advisory AI-suggested mapping to a fixed ComplianceCategory.code, or
  // null when no confident match was found. Never authoritative.
  category_hint: string | null;
  is_mandatory: boolean;
  created_at: string;
}

export interface ProcurementDocumentUploadResponse {
  document: ProcurementDocumentRead;
  requirements: ProcurementRequirementRead[];
}

// "matched": a passing (VERIFIED/NOT_APPLICABLE) VerificationResult backs
//   this requirement's category_hint.
// "unmatched_failed": the category's latest result is MISMATCH/CRITICAL_FAIL.
// "unmatched_missing": the category's latest result is MISSING/NOT_CLAIMED,
//   or the submission has never been verified for it.
// "no_automated_check": category_hint is null -- nothing to automatically
//   compare against; requires manual officer review.
export type RequirementEvidenceMapStatus =
  | "matched"
  | "unmatched_failed"
  | "unmatched_missing"
  | "no_automated_check";

export interface RequirementEvidenceMapEntryRead {
  requirement_id: string;
  requirement_text: string;
  category_hint: string | null;
  is_mandatory: boolean;
  status: RequirementEvidenceMapStatus;
  verification_status: ComplianceVerificationStatus | null;
  source_verification_result_id: string | null;
  source_document_id: string | null;
  source_document_name: string | null;
}
