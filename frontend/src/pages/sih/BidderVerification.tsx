import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  Clock,
  FileQuestion,
  FileText,
  History,
  Info,
  Network,
  Radar,
  RotateCw,
  ScanEye,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Trash2,
  UploadCloud,
  XCircle,
} from "lucide-react";
import {
  confirmBidderDocument,
  deleteBidderDocument,
  extractBidderDocument,
  getBidder,
  getBidderNetwork,
  getLatestOfficerDecision,
  getOfficerDecisionHistory,
  getProcurementCollusionRadar,
  getSubmission,
  getSubmissionGrounding,
  getSubmissionSummary,
  getSubmissionVerification,
  listBidderDocuments,
  listComplianceCategories,
  listDocumentAuthenticityScans,
  recordOfficerDecision,
  runVerification,
  scanDocumentAuthenticity,
  setBidderDocumentCategory,
  updateBidder,
  uploadBidderDocument,
  verifyFromDocuments,
} from "../../api/endpoints";
import { extractErrorMessage } from "../../api/client";
import { useToast } from "../../context/ToastContext";
import type {
  AuthenticityScanRead,
  BidderDocumentRead,
  BidderRead,
  CollusionReportRead,
  ComplianceCategoryRead,
  ComplianceSummaryRead,
  DeclaredFactsByCategory,
  GroundingReportRead,
  NetworkGraphReportRead,
  OfficerDecisionRead,
  OfficerDecisionType,
  SubmissionRead,
  VerificationResultRead,
} from "../../api/types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ConfidenceBar,
  ConfidenceRing,
  Dropzone,
  Input,
  Modal,
  Select,
  Skeleton,
  Textarea,
} from "../../components/kit";
import { cn } from "../../lib/cn";

const DOCUMENT_STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  processing: "Extracting…",
  review_required: "Review Required",
  failed: "Extraction Failed",
};

// Same severity palette as ProcurementSubmissions.tsx's Collusion Radar
// card -- kept identical rather than shared/extracted, since it's a
// three-entry map and this is the only other place it's used.
const COLLUSION_SEVERITY_CLASSES: Record<string, string> = {
  low: "text-info bg-info-soft",
  medium: "text-warning bg-warning-soft",
  high: "text-danger bg-danger-soft",
};

// Officer-facing document status is a synthesis of two backend fields --
// extraction_status alone can't distinguish "AI extracted this, still
// needs your review" from "you already reviewed and confirmed it," and
// that distinction is the entire point of Phase 5's confirmation gate.
function documentDisplayStatus(doc: BidderDocumentRead): { value: string; label: string } {
  if (doc.extraction_status === "extracted") {
    return doc.is_confirmed ? { value: "confirmed", label: "Confirmed" } : { value: "needs_confirmation", label: "Needs Review" };
  }
  return { value: doc.extraction_status, label: DOCUMENT_STATUS_LABEL[doc.extraction_status] };
}

// The subset of each category's extraction schema (app/schemas/
// sih_extraction.py) an officer can review/correct before confirming --
// deliberately narrow, matching the Phase 5 brief's per-category field
// lists exactly, not every field the schema happens to have. Blacklisting
// has no entry: its extraction is informational/audit-only and never
// feeds declared_facts (see backend document_service's
// _DECLARED_FACTS_MAPPERS), so there's nothing to correct.
const CATEGORY_REVIEW_FIELDS: Record<string, { key: string; label: string; isList?: boolean }[]> = {
  udyam: [
    { key: "udyam_number", label: "Udyam Registration Number" },
    { key: "entity_name", label: "Enterprise Name" },
    { key: "status", label: "Status" },
  ],
  gst: [
    { key: "gstin", label: "GSTIN" },
    { key: "legal_name", label: "Legal Name" },
    { key: "status", label: "Registration Status" },
  ],
  pan_itr: [
    { key: "pan", label: "PAN" },
    { key: "legal_name", label: "Legal Name" },
    { key: "itr_years_claimed", label: "ITR Years Claimed (comma-separated)", isList: true },
  ],
  epfo_esic: [
    { key: "establishment_id", label: "EPFO / ESIC Establishment ID" },
    { key: "legal_name", label: "Entity Name" },
    { key: "status", label: "Status" },
  ],
  // SIH26100 demo-scope expansion -- mca21/epfo/esic/nsic/startup_india
  // all extract via the shared IdentifierStatusExtraction schema on the
  // backend (sih_extraction.py), hence the identical 3-field shape here.
  mca21: [
    { key: "identifier", label: "CIN" },
    { key: "entity_name", label: "Entity Name" },
    { key: "status", label: "Status" },
  ],
  epfo: [
    { key: "identifier", label: "EPFO Establishment ID" },
    { key: "entity_name", label: "Entity Name" },
    { key: "status", label: "Status" },
  ],
  esic: [
    { key: "identifier", label: "ESIC Establishment ID" },
    { key: "entity_name", label: "Entity Name" },
    { key: "status", label: "Status" },
  ],
  nsic: [
    { key: "identifier", label: "NSIC Registration Number" },
    { key: "entity_name", label: "Entity Name" },
    { key: "status", label: "Status" },
  ],
  startup_india: [
    { key: "identifier", label: "DPIIT Recognition Number" },
    { key: "entity_name", label: "Entity Name" },
    { key: "status", label: "Status" },
  ],
  oem_authorization: [
    { key: "authorization_number", label: "Authorization Number" },
    { key: "oem_name", label: "OEM Name" },
    { key: "authorized_bidder_name", label: "Authorized Bidder Name" },
  ],
  digilocker: [
    { key: "digilocker_reference", label: "DigiLocker Reference" },
    { key: "entity_name", label: "Entity Name" },
  ],
  make_in_india: [
    { key: "declared_local_content_percentage", label: "Declared Local Content %" },
    { key: "entity_name", label: "Entity Name" },
  ],
};

function encodeFieldValue(v: unknown): string {
  if (v == null) return "";
  if (Array.isArray(v)) return v.join(", ");
  return String(v);
}

// Per-category declared-fact fields the officer can enter directly --
// Phase 3 has no document upload/OCR pipeline yet (explicitly deferred to
// Phase 4), so this is how declared_facts reaches POST .../verify. Field
// keys match exactly what each backend adapter reads (registry_adapters.py)
// -- e.g. GSTAdapter reads declared_facts["gstin"].
const CATEGORY_FIELDS: Record<string, { key: string; label: string; placeholder?: string; hint?: string }[]> = {
  udyam: [
    { key: "udyam_number", label: "Udyam Number", placeholder: "UDYAM-DL-01-0012345" },
    { key: "entity_name", label: "Entity Name (as registered)", placeholder: "ABC Engineering Private Limited" },
  ],
  gst: [{ key: "gstin", label: "GSTIN", placeholder: "07ABCDE1234F1Z5" }],
  pan_itr: [
    {
      key: "itr_years_claimed",
      label: "ITR Years Claimed",
      placeholder: "2023-24, 2022-23",
      hint: "Comma-separated financial years.",
    },
  ],
  epfo_esic: [{ key: "establishment_id", label: "EPFO / ESIC Establishment ID", placeholder: "DL/EPFO/998877" }],
  // blacklisting has no declarable fields -- it's an identity-based check
  // (bidder PAN against the central debarment registry), always included
  // automatically when verification runs (see handleRunVerification).

  // SIH26100 demo-scope expansion.
  mca21: [{ key: "cin", label: "CIN", placeholder: "U29100DL2015PTC280123" }],
  epfo: [{ key: "establishment_id", label: "EPFO Establishment ID", placeholder: "DL/EPFO/998877" }],
  esic: [{ key: "establishment_id", label: "ESIC Establishment ID", placeholder: "31-00-998877-000-1001" }],
  nsic: [{ key: "nsic_registration_number", label: "NSIC Registration Number", placeholder: "NSIC/DL/2019/00456" }],
  startup_india: [{ key: "dpiit_number", label: "DPIIT Recognition Number", placeholder: "DIPP123456" }],
  oem_authorization: [
    { key: "authorization_number", label: "OEM Authorization Number", placeholder: "OEM-AUTH-2026-0091" },
    { key: "bidder_name", label: "Authorized Bidder Name (as issued)", placeholder: "ABC Engineering Private Limited" },
  ],
  digilocker: [{ key: "digilocker_reference", label: "DigiLocker Reference", placeholder: "DL-REF-ABCENG-0012" }],
  make_in_india: [
    { key: "local_content_percentage", label: "Declared Local Content %", placeholder: "62", hint: "A plain number, e.g. 62 for 62%." },
  ],
};

const STATUS_LABEL: Record<string, string> = {
  verified: "Verified",
  mismatch: "Mismatch",
  missing: "Missing",
  not_applicable: "Not Applicable",
  not_claimed: "Not Claimed",
  critical_fail: "Critical",
};

const STATUS_ICON: Record<string, typeof CheckCircle2> = {
  verified: CheckCircle2,
  mismatch: AlertTriangle,
  missing: FileQuestion,
  not_applicable: Info,
  not_claimed: Info,
  critical_fail: XCircle,
};

function formatValue(v: unknown): string {
  if (v == null) return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "object") {
    const entries = Object.entries(v as Record<string, unknown>);
    if (!entries.length) return "—";
    return entries.map(([k, val]) => `${k}: ${formatValue(val)}`).join("; ");
  }
  return String(v);
}

const DECISION_COPY: Record<OfficerDecisionType, { label: string; danger: boolean; description: string }> = {
  approve: { label: "Approve", danger: false, description: "Approving this bidder submission as compliant." },
  reject: { label: "Reject", danger: true, description: "Rejecting this bidder submission." },
  request_clarification: {
    label: "Request Clarification",
    danger: false,
    description: "Asking the bidder for more information before a final decision.",
  },
};

export default function BidderVerification() {
  const { procurementId, submissionId } = useParams<{ procurementId: string; submissionId: string }>();
  const [submission, setSubmission] = useState<SubmissionRead | null>(null);
  const [bidder, setBidder] = useState<BidderRead | null>(null);
  const [categories, setCategories] = useState<ComplianceCategoryRead[]>([]);
  const [results, setResults] = useState<VerificationResultRead[]>([]);
  const [summary, setSummary] = useState<ComplianceSummaryRead | null>(null);
  const [latestDecision, setLatestDecision] = useState<OfficerDecisionRead | null>(null);
  const [history, setHistory] = useState<OfficerDecisionRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);

  const [verifyOpen, setVerifyOpen] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [fields, setFields] = useState<Record<string, Record<string, string>>>({});

  // --- Bidder documents (Phase 4) ---
  // Documents list stays compact on the main dashboard -- extracted fields,
  // errors, and category correction all live behind a single "Details"
  // drill-down modal (documentDetailId) instead of inline on the page, per
  // the "dashboard is not an API response viewer" rule.
  const [documents, setDocuments] = useState<BidderDocumentRead[]>([]);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadCategory, setUploadCategory] = useState("");
  const [uploading, setUploading] = useState(false);
  const [extractingId, setExtractingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [documentDetailId, setDocumentDetailId] = useState<string | null>(null);
  const [verifyingFromDocs, setVerifyingFromDocs] = useState(false);
  // Review/correct form for the currently-open document detail modal --
  // reviewOriginal is what confirming "as-is" would send (unchanged from
  // AI extraction), reviewDraft is what's currently in the inputs; only
  // fields that actually differ are sent as corrected_fields on confirm.
  const [reviewDraft, setReviewDraft] = useState<Record<string, string>>({});
  const [reviewOriginal, setReviewOriginal] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);

  // --- Evidence Grounding Guard (Phase 1b) ---
  const [grounding, setGrounding] = useState<GroundingReportRead | null>(null);

  // --- Authenticity Scanner (Phase 2) -- latest scan per document id ---
  const [authenticityScans, setAuthenticityScans] = useState<Record<string, AuthenticityScanRead>>({});
  const [scanningId, setScanningId] = useState<string | null>(null);

  // --- Bidder Network Graph (Phase 3) ---
  const [networkGraph, setNetworkGraph] = useState<NetworkGraphReportRead | null>(null);

  // --- Collusion Radar (Phase 4) -- procurement-level, surfaced here too
  // ("why was this bidder flagged?" should not require leaving this page)
  // so a suspicious bidder's compliance findings, evidence, authenticity,
  // network relationships, and collusion indicators are all visible in one
  // place. Reuses the existing GET /procurements/{id}/collusion-radar
  // endpoint -- no new API. ---
  const [collusionReport, setCollusionReport] = useState<CollusionReportRead | null>(null);
  const [identifiersOpen, setIdentifiersOpen] = useState(false);
  const [identifiersSaving, setIdentifiersSaving] = useState(false);
  const [identifierFields, setIdentifierFields] = useState({
    registered_address: "",
    director_name: "",
    contact_email: "",
    contact_phone: "",
  });

  const openIdentifiersEditor = (b: BidderRead) => {
    setIdentifierFields({
      registered_address: b.registered_address ?? "",
      director_name: b.director_name ?? "",
      contact_email: b.contact_email ?? "",
      contact_phone: b.contact_phone ?? "",
    });
    setIdentifiersOpen(true);
  };

  const handleSaveIdentifiers = async () => {
    if (!bidder) return;
    setIdentifiersSaving(true);
    try {
      await updateBidder(bidder.id, {
        registered_address: identifierFields.registered_address.trim() || null,
        director_name: identifierFields.director_name.trim() || null,
        contact_email: identifierFields.contact_email.trim() || null,
        contact_phone: identifierFields.contact_phone.trim() || null,
      });
      notify("success", "Bidder identifiers updated.");
      setIdentifiersOpen(false);
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setIdentifiersSaving(false);
    }
  };

  const [decisionOpen, setDecisionOpen] = useState<OfficerDecisionType | null>(null);
  const [decisionNote, setDecisionNote] = useState("");
  const [decidingNow, setDecidingNow] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  const { notify } = useToast();

  const resultByCategory = useMemo(() => {
    const map = new Map<string, VerificationResultRead>();
    for (const r of results) map.set(r.category_code, r);
    return map;
  }, [results]);

  const activeCategories = categories.filter((c) => c.is_active);
  const roadmapCategories = categories.filter((c) => !c.is_active);
  const hasBeenVerified = results.length > 0;

  // "What needs my attention?" -- the single place an officer looks to
  // understand what's wrong, what's missing, and what to do next. Critical
  // findings first, then mismatches/missing, then document-pipeline items
  // that block a category from ever being checked. This replaces the old
  // standalone critical-risk banner and the header's raw count grid --
  // one place, plain language, ordered by priority.
  const attentionItems = useMemo(() => {
    const items: { id: string; tone: "danger" | "warning" | "info"; icon: typeof ShieldAlert; text: string }[] = [];
    for (const r of results) {
      if (r.status === "critical_fail") {
        items.push({ id: `crit-${r.category_code}`, tone: "danger", icon: ShieldAlert, text: `${r.category_name}: ${r.reason ?? "critical finding — requires review."}` });
      }
    }
    for (const r of results) {
      if (r.status === "mismatch") {
        items.push({ id: `mismatch-${r.category_code}`, tone: "warning", icon: AlertTriangle, text: `${r.category_name}: bidder-submitted value doesn't match the registry.` });
      }
    }
    for (const r of results) {
      if (r.status === "missing" && r.mandatory) {
        items.push({ id: `missing-${r.category_code}`, tone: "warning", icon: FileQuestion, text: `${r.category_name}: mandatory and not yet declared or documented.` });
      }
    }
    for (const doc of documents) {
      if (doc.extraction_status === "review_required") {
        items.push({ id: `doc-review-${doc.id}`, tone: "warning", icon: AlertTriangle, text: `${doc.file_name}: needs a category assigned before it can be read.` });
      } else if (doc.extraction_status === "failed") {
        items.push({ id: `doc-failed-${doc.id}`, tone: "warning", icon: AlertTriangle, text: `${doc.file_name}: AI extraction failed — retry or enter the details manually.` });
      } else if (doc.extraction_status === "extracted" && !doc.is_confirmed) {
        // A confirmed document has nothing left to flag -- only the
        // still-needs-a-human-look state is actionable.
        items.push({ id: `doc-extracted-${doc.id}`, tone: "warning", icon: Sparkles, text: `${doc.file_name}: AI-extracted — needs your review and confirmation before it can be used for verification.` });
      }
    }
    return items;
  }, [results, documents]);

  const ATTENTION_TONE_CLASSES: Record<"danger" | "warning" | "info", string> = {
    danger: "bg-danger-soft text-danger",
    warning: "bg-warning-soft text-warning",
    info: "bg-info-soft text-info",
  };

  const detailDoc = documents.find((d) => d.id === documentDetailId) ?? null;

  useEffect(() => {
    if (!detailDoc || detailDoc.extraction_status !== "extracted") return;
    const source = detailDoc.confirmed_data ?? detailDoc.extracted_data ?? {};
    const config = detailDoc.category_code ? CATEGORY_REVIEW_FIELDS[detailDoc.category_code] : undefined;
    const seeded: Record<string, string> = {};
    for (const f of config ?? []) {
      seeded[f.key] = encodeFieldValue((source as Record<string, unknown>)[f.key]);
    }
    setReviewDraft(seeded);
    setReviewOriginal(seeded);
    // Deliberately keyed on extraction_status (not just documentDetailId):
    // handleExtract() opens this modal (setDocumentDetailId) *before*
    // refresh() has replaced `documents` with the newly-extracted row, so
    // on that first render detailDoc is still the stale pre-extraction
    // object and this effect returns early via the guard above. Once
    // refresh() lands, `documents` gets new objects and detailDoc's
    // extraction_status flips to "extracted" -- re-running this effect is
    // what actually seeds the fields. Keying on documentDetailId alone
    // left the inputs permanently empty for any doc opened via the
    // Extract flow (confidence/status rendered fine since those read
    // detailDoc directly, but reviewDraft/reviewOriginal never re-seeded).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentDetailId, detailDoc?.extraction_status]);

  const refresh = async () => {
    if (!submissionId) return;
    try {
      const sub = await getSubmission(submissionId);
      setSubmission(sub);
      const [bidderData, cats, verificationResults, summaryData, latest, decisionHistory, docs, groundingReport] =
        await Promise.all([
          getBidder(sub.bidder_id),
          listComplianceCategories(),
          getSubmissionVerification(submissionId),
          getSubmissionSummary(submissionId).catch(() => null),
          getLatestOfficerDecision(submissionId).catch(() => null),
          getOfficerDecisionHistory(submissionId).catch(() => []),
          listBidderDocuments(submissionId).catch(() => []),
          getSubmissionGrounding(submissionId).catch(() => null),
        ]);
      setBidder(bidderData);
      setCategories(cats);
      setResults(verificationResults);
      setSummary(summaryData);
      setLatestDecision(latest);
      setHistory(decisionHistory);
      setDocuments(docs);
      setGrounding(groundingReport);

      // Bidder Network Graph (Phase 3) -- fetched off the bidder id, never
      // blocks the rest of the page if it fails.
      getBidderNetwork(sub.bidder_id)
        .then(setNetworkGraph)
        .catch(() => setNetworkGraph(null));

      // Collusion Radar (Phase 4) -- procurement-level, fetched via this
      // submission's own procurement_id so it works regardless of which
      // route param the page was opened from. Best-effort, same as above.
      getProcurementCollusionRadar(sub.procurement_id)
        .then(setCollusionReport)
        .catch(() => setCollusionReport(null));

      // Authenticity Scanner (Phase 2) -- latest scan per document, best
      // effort (a document that's never been scanned simply has none).
      const scanEntries = await Promise.all(
        docs.map(async (doc) => {
          const scans = await listDocumentAuthenticityScans(submissionId, doc.id).catch(() => []);
          return [doc.id, scans[0]] as const;
        })
      );
      setAuthenticityScans(
        Object.fromEntries(scanEntries.filter(([, scan]) => scan != null)) as Record<string, AuthenticityScanRead>
      );

      // Pre-fill the Run Verification form from the most recently declared
      // values, if any -- convenience for a re-run, never invented data.
      const prefill: Record<string, Record<string, string>> = {};
      for (const r of verificationResults) {
        if (!r.declared_value) continue;
        const config = CATEGORY_FIELDS[r.category_code];
        if (!config) continue;
        const entry: Record<string, string> = {};
        for (const f of config) {
          const v = (r.declared_value as Record<string, unknown>)[f.key];
          entry[f.key] = Array.isArray(v) ? v.join(", ") : v != null ? String(v) : "";
        }
        prefill[r.category_code] = entry;
      }
      setFields(prefill);
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submissionId]);

  const handleRunVerification = async () => {
    if (!submissionId) return;
    setVerifying(true);
    try {
      const declared: DeclaredFactsByCategory = {};
      for (const cat of activeCategories) {
        if (cat.code === "blacklisting") {
          // Identity-based, always checked -- see CATEGORY_FIELDS comment.
          declared.blacklisting = {};
          continue;
        }
        const config = CATEGORY_FIELDS[cat.code];
        if (!config) continue;
        const values = fields[cat.code] ?? {};
        const hasAnyValue = config.some((f) => (values[f.key] ?? "").trim().length > 0);
        if (!hasAnyValue) continue; // omitted -> backend records MISSING/NOT_CLAIMED honestly
        const payload: Record<string, unknown> = {};
        for (const f of config) {
          const raw = (values[f.key] ?? "").trim();
          if (!raw) continue;
          payload[f.key] = f.key === "itr_years_claimed" ? raw.split(",").map((s) => s.trim()).filter(Boolean) : raw;
        }
        declared[cat.code] = payload;
      }
      await runVerification(submissionId, declared);
      notify("success", "Verification complete.");
      setVerifyOpen(false);
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setVerifying(false);
    }
  };

  const handleUploadDocument = async () => {
    // Category is now mandatory at upload -- classify_document()'s
    // keyword heuristic (backend, unchanged) proved unreliable enough in
    // practice (e.g. an EPFO/ESIC certificate auto-tagged as GST) that
    // the officer picking the category themselves is the safer default;
    // the "Wrong category? Correct it" fix-up path in the document detail
    // modal still exists for anything that turns out mistagged.
    if (!submissionId || !uploadFile || !uploadCategory) return;
    setUploading(true);
    try {
      await uploadBidderDocument(submissionId, uploadFile, uploadCategory);
      notify("success", `${uploadFile.name} uploaded.`);
      setUploadFile(null);
      setUploadCategory("");
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setUploading(false);
    }
  };

  const handleExtract = async (documentId: string) => {
    if (!submissionId) return;
    setExtractingId(documentId);
    try {
      const updated = await extractBidderDocument(submissionId, documentId);
      if (updated.extraction_status === "extracted") {
        notify("success", "Document extracted. Review the fields before running verification.");
        setDocumentDetailId(documentId);
      } else if (updated.extraction_status === "review_required") {
        notify("error", updated.extraction_error ?? "Could not determine this document's category. Assign one manually.");
        setDocumentDetailId(documentId);
      } else {
        notify("error", updated.extraction_error ?? "Extraction failed.");
      }
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
      await refresh();
    } finally {
      setExtractingId(null);
    }
  };

  const handleScanAuthenticity = async (documentId: string) => {
    if (!submissionId) return;
    setScanningId(documentId);
    try {
      const scan = await scanDocumentAuthenticity(submissionId, documentId);
      setAuthenticityScans((prev) => ({ ...prev, [documentId]: scan }));
      notify(
        "success",
        scan.summary_label === "indicators_present"
          ? "Scan complete -- indicators found, worth a look."
          : "Scan complete."
      );
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setScanningId(null);
    }
  };

  const handleDeleteDocument = async (documentId: string, fileName: string) => {
    if (!submissionId) return;
    if (!confirm(`Delete "${fileName}"? This removes the file and cannot be undone.`)) return;
    setDeletingId(documentId);
    try {
      await deleteBidderDocument(submissionId, documentId);
      notify("success", `${fileName} deleted.`);
      if (documentDetailId === documentId) setDocumentDetailId(null);
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setDeletingId(null);
    }
  };

  const handleCorrectCategory = async (documentId: string, categoryCode: string) => {
    if (!submissionId || !categoryCode) return;
    try {
      await setBidderDocumentCategory(submissionId, documentId, { category_code: categoryCode });
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    }
  };

  const handleConfirmDocument = async () => {
    if (!submissionId || !detailDoc) return;
    setConfirming(true);
    try {
      const config = detailDoc.category_code ? CATEGORY_REVIEW_FIELDS[detailDoc.category_code] : undefined;
      const correctedFields: Record<string, unknown> = {};
      for (const f of config ?? []) {
        const draftValue = reviewDraft[f.key] ?? "";
        if (draftValue === (reviewOriginal[f.key] ?? "")) continue; // unchanged -- omit
        correctedFields[f.key] = f.isList
          ? draftValue.split(",").map((s) => s.trim()).filter(Boolean)
          : draftValue.trim() || null;
      }
      const hasCorrections = Object.keys(correctedFields).length > 0;
      await confirmBidderDocument(submissionId, detailDoc.id, { corrected_fields: hasCorrections ? correctedFields : null });
      notify("success", hasCorrections ? "Extraction confirmed with your corrections." : "Extraction confirmed as-is.");
      setDocumentDetailId(null);
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setConfirming(false);
    }
  };

  const handleVerifyFromDocuments = async () => {
    if (!submissionId) return;
    setVerifyingFromDocs(true);
    try {
      await verifyFromDocuments(submissionId);
      notify("success", "Verification complete using extracted documents.");
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setVerifyingFromDocs(false);
    }
  };

  const handleRecordDecision = async () => {
    if (!submissionId || !decisionOpen) return;
    if (!decisionNote.trim()) {
      notify("error", "A note explaining the decision is required.");
      return;
    }
    setDecidingNow(true);
    try {
      await recordOfficerDecision(submissionId, { decision: decisionOpen, note: decisionNote.trim() });
      notify("success", `Decision recorded: ${DECISION_COPY[decisionOpen].label}.`);
      setDecisionOpen(null);
      setDecisionNote("");
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setDecidingNow(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-6 w-40" />
        <Card>
          <CardBody className="space-y-4">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-24 w-full" />
          </CardBody>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link
        to={`/procurement-verification/${procurementId}`}
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft size={14} /> Back to bidder submissions
      </Link>

      {/* --- 1. Bidder header + overall status: identity, score, risk -- the
          5-second read. Counts/critical detail live in the Attention
          summary below, not duplicated here. */}
      <Card>
        <CardBody className="flex flex-wrap items-center justify-between gap-6">
          <div className="flex items-center gap-4 min-w-0">
            <div className="w-12 h-12 rounded-full bg-primary/10 text-primary flex items-center justify-center text-lg font-semibold shrink-0">
              {(bidder?.legal_name ?? "?")[0]?.toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <p className="text-xs text-muted-foreground">Bidder</p>
                {submission && <Badge value={submission.status} />}
              </div>
              <p className="text-lg font-semibold truncate">{bidder?.legal_name ?? "Unknown bidder"}</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                {bidder?.pan ? `PAN ${bidder.pan}` : "No PAN on file"}
                {" · "}
                <button
                  type="button"
                  onClick={() => bidder && openIdentifiersEditor(bidder)}
                  className="text-primary hover:underline"
                >
                  Edit identifiers (Network Graph)
                </button>
              </p>
            </div>
          </div>

          {hasBeenVerified && summary ? (
            <div className="flex items-center gap-6">
              <div className="flex flex-col items-center">
                <ConfidenceRing value={summary.compliance_score / 100} size={72} riskLevel={summary.risk_level} />
                <span className="text-[11px] text-muted-foreground mt-1">Compliance Score</span>
              </div>
              <div className="flex flex-col items-center gap-1.5">
                <Badge value={summary.risk_level} withIcon label={`${summary.risk_level.toUpperCase()} RISK`} />
                <span className="text-[11px] text-muted-foreground">Risk Level</span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Not yet verified against government registries.</p>
          )}

          <Button onClick={() => setVerifyOpen(true)} icon={<ShieldCheck size={15} />}>
            {hasBeenVerified ? "Re-run Verification" : "Run Verification"}
          </Button>
        </CardBody>
      </Card>

      {/* --- 2. Action / attention summary: "what needs my attention?" --
          critical findings dominate visually via tone, everything else is
          plain-language line items, ordered by priority. Nothing here
          duplicates the header's score/risk. */}
      <Card>
        <CardHeader title="Needs Your Attention" />
        <CardBody className="space-y-1.5">
          {!hasBeenVerified && documents.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Upload bidder documents or run verification to see findings here.
            </p>
          ) : attentionItems.length === 0 ? (
            <div className="flex items-center gap-2 text-sm text-success">
              <CheckCircle2 size={15} className="shrink-0" />
              No open issues — ready for a decision.
            </div>
          ) : (
            attentionItems.map((item) => (
              <div key={item.id} className={cn("flex items-start gap-2 rounded-md px-3 py-2 text-sm", ATTENTION_TONE_CLASSES[item.tone])}>
                <item.icon size={14} className="shrink-0 mt-0.5" />
                <span>{item.text}</span>
              </div>
            ))
          )}
        </CardBody>
      </Card>

      {/* --- "Why was this bidder flagged?" -- Evidence Grounding Guard
          (Phase 1b), Bidder Network Graph (Phase 3), and Collusion Radar
          (Phase 4) as compact side-by-side summary cards, so a suspicious
          bidder's compliance findings (above), evidence origin, related
          bidders, and bidding-pattern indicators are all visible on this
          one page -- never requiring a jump to the procurement-level view
          to understand why this bidder needs attention. Grounding shows
          where each verified category's evidence actually came from;
          Network Graph shows other bidders sharing a real identifier;
          Collusion Radar shows transparent, rule-based bidding-pattern
          indicators for the procurement this submission belongs to. None
          of the three is itself a verdict of wrongdoing. */}
      {(grounding || networkGraph || (collusionReport && collusionReport.indicators.length > 0)) && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {grounding && (
            <Card>
              <CardHeader title="Evidence Grounding" description="Where each result's evidence actually came from." />
              <CardBody className="space-y-1.5">
                {grounding.categories.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Nothing verified yet.</p>
                ) : (
                  <>
                    <div className="flex flex-wrap gap-3 text-xs">
                      <span className="inline-flex items-center gap-1.5">
                        <FileText size={12} className="text-success" /> {grounding.document_evidenced_count} from confirmed documents
                      </span>
                      <span className="inline-flex items-center gap-1.5">
                        <Info size={12} className="text-info" /> {grounding.manual_declaration_count} manually declared
                      </span>
                      <span className="inline-flex items-center gap-1.5">
                        <FileQuestion size={12} className="text-muted-foreground" /> {grounding.no_evidence_count} no evidence yet
                      </span>
                    </div>
                  </>
                )}
              </CardBody>
            </Card>
          )}

          {networkGraph && (
            <Card>
              <CardHeader
                title="Bidder Network Graph"
                description="Other bidders sharing a real identifier with this one -- not itself a finding of wrongdoing."
              />
              <CardBody className="space-y-1.5">
                {networkGraph.related_bidders.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No shared identifiers found with other bidders on file.</p>
                ) : (
                  networkGraph.related_bidders.map((rb) => (
                    <div key={rb.bidder_id} className="rounded-md border border-border px-3 py-2">
                      <div className="flex items-center gap-1.5 text-sm font-medium">
                        <Network size={13} className="text-primary shrink-0" /> {rb.legal_name}
                      </div>
                      <ul className="mt-1 text-xs text-muted-foreground list-disc list-inside space-y-0.5">
                        {rb.reasons.map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    </div>
                  ))
                )}
              </CardBody>
            </Card>
          )}

          {collusionReport && collusionReport.indicators.length > 0 && (
            <Card>
              <CardHeader
                title="Collusion Radar"
                description={`Procurement attention score: ${collusionReport.score}/100 -- transparent, rule-based indicators only.`}
              />
              <CardBody className="space-y-1.5">
                {collusionReport.indicators.map((ind, i) => (
                  <div
                    key={`${ind.code}-${i}`}
                    className={cn(
                      "flex items-start gap-2 rounded-md px-3 py-2 text-xs",
                      COLLUSION_SEVERITY_CLASSES[ind.severity] ?? "bg-muted"
                    )}
                  >
                    <Radar size={13} className="shrink-0 mt-0.5" />
                    <div>
                      <p className="font-medium">{ind.label}</p>
                      <p className="mt-0.5 opacity-90">{ind.detail}</p>
                    </div>
                  </div>
                ))}
                <p className="text-[11px] text-muted-foreground pt-1">{collusionReport.disclaimer}</p>
              </CardBody>
            </Card>
          )}
        </div>
      )}

      {/* --- 4. Bidder documents: compact list only. Every extracted field,
          error, and category correction lives behind the single "Details"
          drill-down (AI Extraction Review modal), never inline here. */}
      <Card>
        <CardHeader
          title="Bidder Documents"
          action={
            documents.some((d) => d.is_confirmed) && (
              <Button variant="outline" size="sm" icon={<Sparkles size={13} />} loading={verifyingFromDocs} onClick={handleVerifyFromDocuments}>
                Verify from Documents
              </Button>
            )
          }
        />
        <CardBody className="space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-end gap-3">
            <div className="sm:w-56 shrink-0">
              <Select label="Category" className="h-11" value={uploadCategory} onChange={(e) => setUploadCategory(e.target.value)}>
                <option value="">Choose category…</option>
                {activeCategories
                  .filter((c) => c.code !== "blacklisting")
                  .map((c) => (
                    <option key={c.id} value={c.code}>
                      {c.name}
                    </option>
                  ))}
              </Select>
            </div>
            <div className="flex-1 min-w-0">
              <Dropzone compact file={uploadFile} onFileSelected={setUploadFile} accept="application/pdf,image/*" hint="PDF or image, up to 50MB" className="h-11" />
            </div>
            <Button icon={<UploadCloud size={14} />} loading={uploading} disabled={!uploadFile || !uploadCategory} onClick={handleUploadDocument} size="lg" className="w-full sm:w-auto shrink-0">
              Upload
            </Button>
          </div>

          {/* The button above is disabled until both a category and a file
              are picked -- without this, a file selected with no category
              chosen looks like the Upload click did nothing at all (no
              request, no error, no feedback). */}
          {uploadFile && !uploadCategory && (
            <p className="text-xs text-warning flex items-center gap-1.5">
              <AlertTriangle size={12} className="shrink-0" />
              Choose a category above before uploading {uploadFile.name}.
            </p>
          )}

          {documents.length === 0 ? (
            <p className="text-sm text-muted-foreground">No documents uploaded yet for this bidder.</p>
          ) : (
            <div className="space-y-1.5">
              {documents.map((doc) => {
                const isExtracting = extractingId === doc.id;
                const categoryName = doc.category_code ? categories.find((c) => c.code === doc.category_code)?.name ?? doc.category_code : "Uncategorized";
                const displayStatus = documentDisplayStatus(doc);
                const drillDownLabel =
                  doc.extraction_status === "extracted" ? (doc.is_confirmed ? "View" : "Review") : "Details";
                const isScanning = scanningId === doc.id;
                const scan = authenticityScans[doc.id];
                return (
                  <div key={doc.id} className="flex items-center justify-between gap-3 rounded-lg border border-border px-4 py-2.5">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <FileText size={15} className="text-muted-foreground shrink-0" />
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{doc.file_name}</p>
                        <p className="text-[11px] text-muted-foreground">
                          {categoryName}
                          {doc.category_source === "auto" && " · AI-classified"}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge value={displayStatus.value} label={isExtracting ? "Extracting…" : displayStatus.label} />
                      {scan && (
                        <Badge
                          value={scan.summary_label}
                          label={
                            scan.summary_label === "indicators_present"
                              ? "Authenticity: indicators"
                              : scan.summary_label === "not_analyzable"
                              ? "Authenticity: n/a"
                              : "Authenticity: clean"
                          }
                        />
                      )}
                      <Button
                        variant="outline"
                        size="sm"
                        icon={<ScanEye size={12} />}
                        loading={isScanning}
                        onClick={() => handleScanAuthenticity(doc.id)}
                        title="Run the Authenticity Scanner against this document's actual stored file"
                      >
                        Scan
                      </Button>
                      {(doc.extraction_status === "pending" || doc.extraction_status === "failed") && (
                        <Button variant="outline" size="sm" icon={<RotateCw size={12} />} loading={isExtracting} onClick={() => handleExtract(doc.id)}>
                          {doc.extraction_status === "failed" ? "Retry" : "Extract"}
                        </Button>
                      )}
                      {doc.extraction_status !== "pending" && (
                        <button
                          type="button"
                          onClick={() => setDocumentDetailId(doc.id)}
                          className="text-xs font-medium text-primary hover:underline"
                        >
                          {drillDownLabel}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleDeleteDocument(doc.id, doc.file_name)}
                        disabled={deletingId === doc.id}
                        aria-label={`Delete ${doc.file_name}`}
                        title="Delete document"
                        className="text-muted-foreground hover:text-danger disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Compliance Categories" description="Each category is checked against a simulated government registry." />
        <CardBody className="space-y-2">
          <div className="flex items-start gap-2 rounded-md border border-border bg-surface-hover/40 px-3 py-2 text-xs text-muted-foreground">
            <Info size={13} className="shrink-0 mt-0.5" />
            <span>
              <span className="font-medium text-foreground">Simulated Government Registries.</span> Verification
              results in this demo are generated from deterministic mock registry data. No live government portal
              (GSTN, MCA21, EPFO, ESIC, Income Tax, DigiLocker, NSIC, Startup India, etc.) is queried.
            </span>
          </div>

          {activeCategories.map((cat) => {
            const result = resultByCategory.get(cat.code);
            const StatusIcon = result ? STATUS_ICON[result.status] ?? Info : FileQuestion;
            const isOpen = expandedCategory === cat.code;
            return (
              <div key={cat.id} className="border border-border rounded-lg overflow-hidden">
                <button
                  type="button"
                  onClick={() => result && setExpandedCategory(isOpen ? null : cat.code)}
                  disabled={!result}
                  className={cn(
                    "w-full flex items-center justify-between gap-3 px-4 py-3 text-left transition-colors",
                    result ? "hover:bg-surface-hover cursor-pointer" : "cursor-default"
                  )}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <StatusIcon
                      size={16}
                      className={cn(
                        "shrink-0",
                        !result
                          ? "text-muted-foreground"
                          : result.status === "verified"
                          ? "text-success"
                          : result.status === "critical_fail"
                          ? "text-danger"
                          : "text-warning"
                      )}
                    />
                    <span className="text-sm font-medium truncate">{cat.name}</span>
                    {cat.mandatory_by_default && <span className="text-[10px] text-muted-foreground uppercase tracking-wide shrink-0">Mandatory</span>}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge value={result ? result.status : "not_claimed"} label={result ? STATUS_LABEL[result.status] : "Not run yet"} />
                    {result && <ChevronDown size={14} className={cn("text-muted-foreground transition-transform", isOpen && "rotate-180")} />}
                  </div>
                </button>

                {isOpen && result && (
                  <div className="px-4 pb-4 pt-1 border-t border-border bg-surface-hover/40 space-y-3">
                    <div className="grid sm:grid-cols-2 gap-3 text-xs">
                      <div>
                        <p className="text-muted-foreground mb-1">Bidder Submitted</p>
                        <p className="font-medium text-foreground">{formatValue(result.declared_value)}</p>
                      </div>
                      <div>
                        <p className="text-muted-foreground mb-1">Registry Record</p>
                        <p className="font-medium text-foreground">{formatValue(result.registry_value)}</p>
                      </div>
                    </div>
                    {result.discrepancies && result.discrepancies.length > 0 && (
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Discrepancy</p>
                        <ul className="text-xs text-danger space-y-0.5 list-disc list-inside">
                          {result.discrepancies.map((d, i) => (
                            <li key={i}>{d}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {result.reason && (
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Why this matters</p>
                        <p className="text-xs text-foreground leading-relaxed">{result.reason}</p>
                      </div>
                    )}
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground pt-1">
                      <span>Source: {result.source}</span>
                      <span>Checked: {new Date(result.checked_at).toLocaleString()}</span>
                    </div>
                    {result.source_document_name && (
                      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground pt-0.5">
                        <FileText size={11} className="shrink-0" />
                        Evidence: officer-confirmed AI extraction from{" "}
                        <span className="font-medium text-foreground">{result.source_document_name}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {roadmapCategories.length > 0 && (
            <div className="pt-3 mt-3 border-t border-border">
              <p className="text-xs font-medium text-muted-foreground mb-2">Coming Soon / Not Yet Supported</p>
              <div className="flex flex-wrap gap-2">
                {roadmapCategories.map((cat) => (
                  <span
                    key={cat.id}
                    className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground"
                  >
                    {cat.name}
                  </span>
                ))}
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {/* --- Compliance Review: mandatory-requirement findings, placed
          directly above the decision buttons so an officer cannot approve/
          reject without seeing exactly which MANDATORY categories are
          still unresolved. Purely informational -- PRAMAAN flags, it
          never blocks; decision buttons below are always enabled. Backed
          by ComplianceSummary.mandatory_issues, the same mandatory_by_default
          MISSING/MISMATCH set that already drives risk_level="high" in
          compliance_summary_service.py -- this panel names those
          categories individually instead of only reporting the aggregate
          risk label. */}
      {hasBeenVerified && summary && (
        <Card>
          <CardHeader
            title="Compliance Review"
            description={`${summary.compliance_score}% compliance · ${summary.risk_level.toUpperCase()} risk`}
          />
          <CardBody className="space-y-3">
            {summary.mandatory_issues.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-success">
                <CheckCircle2 size={15} className="shrink-0" />
                All mandatory requirements are verified.
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2 rounded-md bg-danger-soft text-danger px-3 py-2 text-sm font-medium">
                  <ShieldAlert size={15} className="shrink-0" />
                  {summary.mandatory_issues.length} mandatory requirement{summary.mandatory_issues.length > 1 ? "s" : ""} unresolved
                </div>
                <div className="space-y-2">
                  {summary.mandatory_issues.map((issue) => {
                    const StatusIcon = STATUS_ICON[issue.status] ?? FileQuestion;
                    return (
                      <div
                        key={issue.category_code}
                        className="rounded-md border border-danger/30 bg-danger-soft/40 px-3 py-2.5 space-y-1.5"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusIcon size={14} className="shrink-0 text-danger" />
                          <span className="text-sm font-medium">{issue.category_name}</span>
                          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Mandatory</span>
                          <Badge value={issue.status} label={STATUS_LABEL[issue.status] ?? issue.status} />
                        </div>
                        {issue.reason && <p className="text-xs text-muted-foreground pl-[22px]">{issue.reason}</p>}
                        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground pl-[22px]">
                          <FileText size={11} className="shrink-0" />
                          {issue.source_document_name ? (
                            <>
                              Evidence:{" "}
                              <span className="font-medium text-foreground">{issue.source_document_name}</span>
                            </>
                          ) : (
                            "Evidence: Not submitted"
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <p className="text-xs text-muted-foreground">
                  PRAMAAN has identified unresolved mandatory compliance requirements. The procurement officer retains final decision authority below.
                </p>
              </>
            )}
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Procurement Officer Decision"
          description={
            latestDecision
              ? `Current decision: ${DECISION_COPY[latestDecision.decision].label}`
              : "No decision recorded yet for this bidder submission."
          }
          action={
            history.length > 0 && (
              <button
                onClick={() => setHistoryOpen((v) => !v)}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
              >
                <History size={13} /> {historyOpen ? "Hide" : "View"} history ({history.length})
              </button>
            )
          }
        />
        <CardBody className="space-y-4">
          {latestDecision && (
            <div className="rounded-md border border-border p-3 bg-surface-hover/40">
              <div className="flex items-center gap-2 mb-1">
                <Badge value={latestDecision.decision} label={DECISION_COPY[latestDecision.decision].label.toUpperCase()} />
                <span className="text-xs text-muted-foreground inline-flex items-center gap-1">
                  <Clock size={11} /> {new Date(latestDecision.decided_at).toLocaleString()}
                </span>
              </div>
              <p className="text-sm text-foreground">"{latestDecision.note}"</p>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2.5">
            <div className="flex flex-wrap gap-2.5">
              <Button variant="primary" onClick={() => setDecisionOpen("approve")}>
                Approve
              </Button>
              <Button variant="danger" onClick={() => setDecisionOpen("reject")}>
                Reject
              </Button>
            </div>
            <Button variant="warning" onClick={() => setDecisionOpen("request_clarification")}>
              Request Clarification
            </Button>
          </div>

          {historyOpen && (
            <div className="pt-3 border-t border-border space-y-2.5">
              <p className="text-xs text-muted-foreground">
                Full audit history -- earlier decisions are never deleted or overwritten.
              </p>
              {history
                .slice()
                .reverse()
                .map((d) => (
                  <div key={d.id} className="rounded-md border border-border p-3">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge value={d.decision} label={DECISION_COPY[d.decision].label.toUpperCase()} />
                      <span className="text-xs text-muted-foreground">{new Date(d.decided_at).toLocaleString()}</span>
                    </div>
                    <p className="text-sm text-foreground">"{d.note}"</p>
                  </div>
                ))}
            </div>
          )}
        </CardBody>
      </Card>

      {/* --- Run Verification modal --- */}
      <Modal
        open={verifyOpen}
        title="Run Verification"
        description="Enter what the bidder declared for each category. Categories left blank are recorded honestly as Missing or Not Claimed -- nothing is assumed."
        onClose={() => !verifying && setVerifyOpen(false)}
        size="lg"
        footer={
          <>
            <Button variant="outline" size="sm" onClick={() => setVerifyOpen(false)} disabled={verifying}>
              Cancel
            </Button>
            <Button size="sm" loading={verifying} onClick={handleRunVerification}>
              Run Verification
            </Button>
          </>
        }
      >
        <div className="space-y-4 max-h-[55vh] overflow-y-auto pr-1">
          {activeCategories
            .filter((c) => c.code !== "blacklisting")
            .map((cat) => {
              const config = CATEGORY_FIELDS[cat.code];
              if (!config) return null;
              return (
                <div key={cat.id}>
                  <p className="text-xs font-semibold text-foreground mb-2">
                    {cat.name}
                    {cat.mandatory_by_default && <span className="text-muted-foreground font-normal"> (mandatory)</span>}
                  </p>
                  <div className="grid sm:grid-cols-2 gap-2.5">
                    {config.map((f) => (
                      <div key={f.key} className={f.key === "itr_years_claimed" ? "sm:col-span-2" : undefined}>
                        <input
                          value={fields[cat.code]?.[f.key] ?? ""}
                          onChange={(e) =>
                            setFields((prev) => ({
                              ...prev,
                              [cat.code]: { ...prev[cat.code], [f.key]: e.target.value },
                            }))
                          }
                          placeholder={f.placeholder}
                          className="block w-full rounded-md border border-input bg-surface px-3 py-2 text-sm placeholder:text-muted-foreground/70 focus:outline-none focus:ring-2 focus:ring-ring focus:border-ring"
                          aria-label={f.label}
                        />
                        <span className="text-[11px] text-muted-foreground mt-1 block">{f.hint ?? f.label}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          <div className="rounded-md border border-border bg-surface-hover/40 px-3 py-2.5 text-xs text-muted-foreground flex items-center gap-2">
            <ShieldCheck size={14} className="text-primary shrink-0" />
            Blacklisting / Debarment is always checked automatically against the bidder's PAN -- no declaration needed.
          </div>
        </div>
      </Modal>

      {/* --- Officer decision modal --- */}
      <Modal
        open={decisionOpen !== null}
        title={decisionOpen ? `Decision: ${DECISION_COPY[decisionOpen].label}` : ""}
        description={decisionOpen ? DECISION_COPY[decisionOpen].description : undefined}
        onClose={() => {
          if (decidingNow) return;
          setDecisionOpen(null);
          setDecisionNote("");
        }}
        footer={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setDecisionOpen(null);
                setDecisionNote("");
              }}
              disabled={decidingNow}
            >
              Cancel
            </Button>
            <Button
              variant={decisionOpen === "reject" ? "danger" : "primary"}
              size="sm"
              loading={decidingNow}
              disabled={!decisionNote.trim()}
              onClick={handleRecordDecision}
            >
              Confirm Decision
            </Button>
          </>
        }
      >
        <Textarea
          label="Reason / Officer Note (required)"
          value={decisionNote}
          onChange={(e) => setDecisionNote(e.target.value)}
          placeholder="Explain the basis for this decision…"
          rows={4}
          autoFocus
        />
      </Modal>

      {/* --- 5. AI Extraction Review: only ever appears as a drill-down for
          one document, never inline on the main dashboard. Doubles as the
          detail view for review_required/failed documents (category
          correction, error text) so there's a single "Details" entry point
          per document row above. */}
      <Modal
        open={documentDetailId !== null}
        title={detailDoc?.file_name ?? "Document"}
        description={detailDoc ? `${detailDoc.category_code ? categories.find((c) => c.code === detailDoc.category_code)?.name ?? detailDoc.category_code : "Uncategorized"} · Uploaded ${new Date(detailDoc.uploaded_at).toLocaleDateString()}` : undefined}
        onClose={() => !confirming && setDocumentDetailId(null)}
        size="md"
        footer={
          detailDoc?.extraction_status === "extracted" ? (
            <>
              <Button variant="outline" size="sm" onClick={() => setDocumentDetailId(null)} disabled={confirming}>
                Close
              </Button>
              <Button size="sm" icon={<CheckCircle2 size={14} />} loading={confirming} onClick={handleConfirmDocument}>
                {detailDoc.is_confirmed ? "Re-confirm" : "Confirm"}
              </Button>
            </>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setDocumentDetailId(null)}>
              Close
            </Button>
          )
        }
      >
        {detailDoc && (
          <div className="space-y-4">
            <Badge value={documentDisplayStatus(detailDoc).value} label={documentDisplayStatus(detailDoc).label} />

            {detailDoc.extraction_status === "review_required" && (
              <div className="space-y-2">
                <p className="text-xs text-warning flex items-start gap-1.5">
                  <AlertTriangle size={13} className="shrink-0 mt-0.5" />
                  {detailDoc.extraction_error ?? "Could not confidently determine this document's category."}
                </p>
                <Select
                  label="Assign category"
                  className="h-9 text-xs"
                  value=""
                  onChange={(e) => e.target.value && handleCorrectCategory(detailDoc.id, e.target.value)}
                >
                  <option value="">Choose category…</option>
                  {activeCategories
                    .filter((c) => c.code !== "blacklisting")
                    .map((c) => (
                      <option key={c.id} value={c.code}>
                        {c.name}
                      </option>
                    ))}
                </Select>
              </div>
            )}

            {detailDoc.extraction_status === "failed" && (
              <p className="text-xs text-danger flex items-start gap-1.5">
                <XCircle size={13} className="shrink-0 mt-0.5" /> {detailDoc.extraction_error ?? "Extraction failed."}
              </p>
            )}

            {detailDoc.extraction_status === "extracted" && (
              <>
                {detailDoc.is_confirmed ? (
                  <p className="text-xs text-success flex items-center gap-1.5">
                    <CheckCircle2 size={12} /> Confirmed{detailDoc.manually_corrected ? " with corrections" : ""} on{" "}
                    {detailDoc.confirmed_at && new Date(detailDoc.confirmed_at).toLocaleString()}. These facts are used
                    for verification.
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                    <Sparkles size={12} className="text-primary" /> AI-extracted — verify before relying on it. Correct
                    any field below, then Confirm to make it verification input.
                  </p>
                )}

                {detailDoc.category_code && CATEGORY_REVIEW_FIELDS[detailDoc.category_code] ? (
                  <div className="space-y-2.5">
                    {CATEGORY_REVIEW_FIELDS[detailDoc.category_code].map((f) => (
                      <div key={f.key}>
                        <label className="text-[11px] font-medium text-muted-foreground mb-1 block">{f.label}</label>
                        <input
                          value={reviewDraft[f.key] ?? ""}
                          onChange={(e) => setReviewDraft((prev) => ({ ...prev, [f.key]: e.target.value }))}
                          className="block w-full rounded-md border border-input bg-surface px-3 py-2 text-sm placeholder:text-muted-foreground/70 focus:outline-none focus:ring-2 focus:ring-ring focus:border-ring"
                        />
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="grid sm:grid-cols-2 gap-x-6 gap-y-2 text-xs">
                    {detailDoc.extracted_data &&
                      Object.entries(detailDoc.extracted_data)
                        .filter(([, v]) => v != null)
                        .map(([k, v]) => (
                          <div key={k}>
                            <p className="text-muted-foreground mb-0.5">{k.replace(/_/g, " ")}</p>
                            <p className="font-medium text-foreground">{formatValue(v)}</p>
                          </div>
                        ))}
                  </div>
                )}

                <ConfidenceBar label="Extraction Confidence" value={detailDoc.extraction_confidence} />
                <Select
                  label="Wrong category? Correct it"
                  className="h-9 text-xs"
                  value=""
                  onChange={(e) => e.target.value && handleCorrectCategory(detailDoc.id, e.target.value)}
                >
                  <option value="">Choose category…</option>
                  {activeCategories
                    .filter((c) => c.code !== "blacklisting")
                    .map((c) => (
                      <option key={c.id} value={c.code}>
                        {c.name}
                      </option>
                    ))}
                </Select>
              </>
            )}

            {authenticityScans[detailDoc.id] && (
              <div className="pt-3 border-t border-border space-y-2">
                <p className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                  <ScanEye size={12} /> Authenticity Scan
                </p>
                <div className="space-y-1.5">
                  {authenticityScans[detailDoc.id].indicators.map((ind, i) => (
                    <div
                      key={`${ind.code}-${i}`}
                      className={cn(
                        "rounded-md px-2.5 py-1.5 text-xs",
                        ind.severity === "high"
                          ? "bg-danger-soft text-danger"
                          : ind.severity === "medium"
                          ? "bg-warning-soft text-warning"
                          : ind.severity === "low"
                          ? "bg-info-soft text-info"
                          : "bg-muted text-muted-foreground"
                      )}
                    >
                      <p className="font-medium">{ind.label}</p>
                      <p className="opacity-90 mt-0.5">{ind.detail}</p>
                    </div>
                  ))}
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Metadata/consistency indicators only -- not a forensic determination. Scanned{" "}
                  {new Date(authenticityScans[detailDoc.id].scanned_at).toLocaleString()}.
                </p>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* --- Bidder Network Graph identifiers editor --- */}
      <Modal
        open={identifiersOpen}
        title="Edit Bidder Identifiers"
        description="Used only by the Bidder Network Graph to find real shared identifiers with other bidders -- never displayed as a finding by itself."
        onClose={() => !identifiersSaving && setIdentifiersOpen(false)}
        footer={
          <>
            <Button variant="outline" size="sm" onClick={() => setIdentifiersOpen(false)} disabled={identifiersSaving}>
              Cancel
            </Button>
            <Button size="sm" loading={identifiersSaving} onClick={handleSaveIdentifiers}>
              Save
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Input
            label="Registered address"
            value={identifierFields.registered_address}
            onChange={(e) => setIdentifierFields((prev) => ({ ...prev, registered_address: e.target.value }))}
          />
          <Input
            label="Director name"
            value={identifierFields.director_name}
            onChange={(e) => setIdentifierFields((prev) => ({ ...prev, director_name: e.target.value }))}
          />
          <Input
            label="Contact email"
            value={identifierFields.contact_email}
            onChange={(e) => setIdentifierFields((prev) => ({ ...prev, contact_email: e.target.value }))}
          />
          <Input
            label="Contact phone"
            value={identifierFields.contact_phone}
            onChange={(e) => setIdentifierFields((prev) => ({ ...prev, contact_phone: e.target.value }))}
          />
        </div>
      </Modal>
    </div>
  );
}
