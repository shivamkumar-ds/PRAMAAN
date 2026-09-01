import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, ArrowRight, FileText, ListChecks, Plus, Radar, ShieldAlert, Trash2, UploadCloud, UserRound } from "lucide-react";
import {
  createBidder,
  createSubmission,
  deleteProcurementRequirement,
  deleteTenderDocument,
  getProcurement,
  getProcurementCollusionRadar,
  getSubmissionSummary,
  getSubmissionVerification,
  listBidders,
  listProcurementRequirements,
  listSubmissionsForProcurement,
  listTenderDocuments,
  setProcurementAwardedBidder,
  uploadTenderDocument,
} from "../../api/endpoints";
import { extractErrorMessage } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type {
  BidderRead,
  CollusionReportRead,
  ComplianceSummaryRead,
  ProcurementDocumentRead,
  ProcurementRead,
  ProcurementRequirementRead,
  SubmissionRead,
} from "../../api/types";
import { Badge, Button, Card, CardBody, CardHeader, Dropzone, EmptyState, Input, Modal, Select, SkeletonList } from "../../components/kit";

const COLLUSION_SEVERITY_CLASSES: Record<string, string> = {
  low: "text-info bg-info-soft",
  medium: "text-warning bg-warning-soft",
  high: "text-danger bg-danger-soft",
};

interface Row {
  submission: SubmissionRead;
  bidder: BidderRead | null;
  summary: ComplianceSummaryRead | null;
  lastVerifiedAt: string | null;
  verified: boolean;
}

export default function ProcurementSubmissions() {
  const { procurementId } = useParams<{ procurementId: string }>();
  const [procurement, setProcurement] = useState<ProcurementRead | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [allBidders, setAllBidders] = useState<BidderRead[]>([]);
  const [selectedBidderId, setSelectedBidderId] = useState("");
  const [legalName, setLegalName] = useState("");
  const [tradeName, setTradeName] = useState("");
  const [pan, setPan] = useState("");
  const [bidAmount, setBidAmount] = useState("");
  const [collusionReport, setCollusionReport] = useState<CollusionReportRead | null>(null);
  const [requirements, setRequirements] = useState<ProcurementRequirementRead[]>([]);
  const [requirementsLoading, setRequirementsLoading] = useState(true);
  const [documents, setDocuments] = useState<ProcurementDocumentRead[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(true);
  const [deletingDocumentId, setDeletingDocumentId] = useState<string | null>(null);
  const [deletingRequirementId, setDeletingRequirementId] = useState<string | null>(null);
  const [tenderFile, setTenderFile] = useState<File | null>(null);
  const [uploadingTender, setUploadingTender] = useState(false);
  const [awardOpen, setAwardOpen] = useState(false);
  const [awardBidderId, setAwardBidderId] = useState("");
  const [awarding, setAwarding] = useState(false);
  const { user } = useAuth();
  const { notify } = useToast();
  // Full 5-role RBAC (Task 4): every role except Auditor may do the
  // day-to-day evidence-gathering work this page gates on canManage --
  // mirrors backend require_sih_write_role. Auditor stays read-only.
  const canManage = user?.role !== "auditor";
  // Setting the awarded bidder is narrower -- Administrator/Executive
  // only, mirrors backend require_sih_award_role (a business decision,
  // not routine evidence-gathering; see collusion_radar_service.py's
  // repeat-winner indicator, which this feeds).
  const canAward = user?.role === "administrator" || user?.role === "executive";

  const refresh = async () => {
    if (!procurementId) return;
    try {
      const [proc, submissions, bidders] = await Promise.all([
        getProcurement(procurementId),
        listSubmissionsForProcurement(procurementId),
        listBidders(),
      ]);
      setProcurement(proc);
      setAllBidders(bidders);
      const biddersById = new Map(bidders.map((b) => [b.id, b]));

      // Bounded to this procurement's own bidders -- summary + verification
      // per submission, both real backend calls (never fabricated), so the
      // officer sees the actual current score/risk/last-checked state.
      const enriched = await Promise.all(
        submissions.map(async (s): Promise<Row> => {
          const [summary, results] = await Promise.all([
            getSubmissionSummary(s.id).catch(() => null),
            getSubmissionVerification(s.id).catch(() => []),
          ]);
          const sortedTimes = results.map((r) => r.checked_at).sort();
          const lastVerifiedAt = sortedTimes.length ? sortedTimes[sortedTimes.length - 1] : null;
          return {
            submission: s,
            bidder: biddersById.get(s.bidder_id) ?? null,
            summary,
            lastVerifiedAt,
            verified: results.length > 0,
          };
        })
      );
      // Bidders needing attention first -- critical, then high, then
      // everything else, then never-verified last (nothing to triage yet).
      const riskRank: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
      enriched.sort((a, b) => {
        if (a.verified !== b.verified) return a.verified ? -1 : 1;
        const ra = a.summary ? riskRank[a.summary.risk_level] ?? 4 : 4;
        const rb = b.summary ? riskRank[b.summary.risk_level] ?? 4 : 4;
        return ra - rb;
      });
      setRows(enriched);

      // Collusion Radar (Phase 4) -- needs at least two submissions to say
      // anything meaningful; fetched separately so its failure never blocks
      // the main submissions list from rendering.
      if (submissions.length >= 2) {
        getProcurementCollusionRadar(procurementId)
          .then(setCollusionReport)
          .catch(() => setCollusionReport(null));
      } else {
        setCollusionReport(null);
      }
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const refreshRequirements = async () => {
    if (!procurementId) return;
    setRequirementsLoading(true);
    try {
      setRequirements(await listProcurementRequirements(procurementId));
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setRequirementsLoading(false);
    }
  };

  const refreshDocuments = async () => {
    if (!procurementId) return;
    setDocumentsLoading(true);
    try {
      setDocuments(await listTenderDocuments(procurementId));
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setDocumentsLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    refreshRequirements();
    refreshDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [procurementId]);

  const handleUploadTender = async () => {
    if (!procurementId || !tenderFile) return;
    setUploadingTender(true);
    try {
      const result = await uploadTenderDocument(procurementId, tenderFile);
      notify(
        "success",
        `Tender document processed -- ${result.requirements.length} requirement(s) extracted.`
      );
      setTenderFile(null);
      await Promise.all([refreshRequirements(), refreshDocuments()]);
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setUploadingTender(false);
    }
  };

  const handleDeleteTenderDocument = async (documentId: string, fileName: string) => {
    if (!procurementId) return;
    if (!confirm(`Delete "${fileName}"? This removes the file. Any requirements already extracted from it will remain, just without an attributed source document.`)) return;
    setDeletingDocumentId(documentId);
    try {
      await deleteTenderDocument(procurementId, documentId);
      notify("success", `${fileName} deleted.`);
      await Promise.all([refreshDocuments(), refreshRequirements()]);
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setDeletingDocumentId(null);
    }
  };

  const handleDeleteRequirement = async (requirementId: string) => {
    if (!procurementId) return;
    if (!confirm("Delete this requirement? This only removes it from the extracted list -- it does not affect any evidence already checked against it.")) return;
    setDeletingRequirementId(requirementId);
    try {
      await deleteProcurementRequirement(procurementId, requirementId);
      notify("success", "Requirement deleted.");
      await refreshRequirements();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setDeletingRequirementId(null);
    }
  };

  const resetAddForm = () => {
    setMode("existing");
    setSelectedBidderId("");
    setLegalName("");
    setTradeName("");
    setPan("");
    setBidAmount("");
  };

  const handleAdd = async () => {
    if (!procurementId) return;
    setAdding(true);
    try {
      let bidderId = selectedBidderId;
      if (mode === "new") {
        if (!legalName.trim()) return;
        const created = await createBidder({
          legal_name: legalName.trim(),
          trade_name: tradeName.trim() || null,
          pan: pan.trim() || null,
        });
        bidderId = created.id;
      }
      if (!bidderId) return;
      const parsedBidAmount = bidAmount.trim() ? Number(bidAmount.trim()) : null;
      await createSubmission(procurementId, bidderId, parsedBidAmount != null && !Number.isNaN(parsedBidAmount) ? parsedBidAmount : null);
      notify("success", "Bidder submission added.");
      setAddOpen(false);
      resetAddForm();
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setAdding(false);
    }
  };

  const canSubmitAdd = mode === "existing" ? Boolean(selectedBidderId) : legalName.trim().length > 0;

  const handleSetAward = async () => {
    if (!procurementId || !awardBidderId) return;
    setAwarding(true);
    try {
      const updated = await setProcurementAwardedBidder(procurementId, awardBidderId);
      setProcurement(updated);
      notify("success", "Awarded bidder recorded.");
      setAwardOpen(false);
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setAwarding(false);
    }
  };

  const awardedBidder = procurement?.awarded_bidder_id
    ? rows.find((r) => r.bidder?.id === procurement.awarded_bidder_id)?.bidder ?? null
    : null;

  return (
    <div className="space-y-6">
      <Link to="/procurement-verification" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft size={14} /> Procurement Verification
      </Link>

      {procurement && (
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{procurement.title}</h1>
            <p className="text-sm text-muted-foreground mt-1">
              {[procurement.reference_number, procurement.organization].filter(Boolean).join(" · ") || "No reference / organization on file"}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Badge value={procurement.status} />
            {awardedBidder && (
              <span className="text-xs font-medium text-foreground bg-muted rounded-md px-2 py-1">
                Awarded: {awardedBidder.legal_name}
              </span>
            )}
            {canAward && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setAwardBidderId(procurement.awarded_bidder_id ?? "");
                  setAwardOpen(true);
                }}
              >
                {awardedBidder ? "Change Awarded Bidder" : "Mark Awarded Bidder"}
              </Button>
            )}
            {canManage && (
              <Button size="sm" icon={<Plus size={14} />} onClick={() => setAddOpen(true)}>
                Add Bidder Submission
              </Button>
            )}
          </div>
        </div>
      )}

      <Card>
        <CardHeader
          title="Tender Document"
          description="Upload the tender/eligibility document to extract discrete compliance requirements -- AI-assembled, officer-reviewable, never authoritative until checked against a bidder's evidence."
        />
        <CardBody className="space-y-4">
          {canManage && (
            <div className="flex flex-wrap items-center gap-3">
              <Dropzone
                compact
                file={tenderFile}
                onFileSelected={setTenderFile}
                accept="application/pdf,image/*"
                hint="PDF or image, up to 50MB"
                className="h-11 flex-1 min-w-[240px]"
              />
              <Button
                icon={<UploadCloud size={14} />}
                loading={uploadingTender}
                disabled={!tenderFile}
                onClick={handleUploadTender}
                size="lg"
                className="shrink-0"
              >
                Upload &amp; Extract
              </Button>
            </div>
          )}

          {documentsLoading ? (
            <SkeletonList rows={1} />
          ) : documents.length > 0 ? (
            <div className="space-y-2">
              {documents.map((doc) => (
                <div key={doc.id} className="flex items-center gap-2.5 rounded-md bg-muted px-3 py-2 text-sm">
                  <FileText size={14} className="shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{doc.original_filename}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Uploaded {new Date(doc.uploaded_at).toLocaleString()}
                      {doc.extraction_error ? ` -- ${doc.extraction_error}` : ""}
                    </p>
                  </div>
                  <Badge value={doc.extraction_status} />
                  {canManage && (
                    <button
                      type="button"
                      onClick={() => handleDeleteTenderDocument(doc.id, doc.original_filename)}
                      disabled={deletingDocumentId === doc.id}
                      aria-label={`Delete ${doc.original_filename}`}
                      title="Delete document"
                      className="text-muted-foreground hover:text-danger disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          ) : null}

          {requirementsLoading ? (
            <SkeletonList rows={2} />
          ) : requirements.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No requirements extracted yet -- upload a tender document above.
            </p>
          ) : (
            <div className="space-y-2">
              {requirements.map((req) => (
                <div key={req.id} className="flex items-start gap-2.5 rounded-md bg-muted px-3 py-2 text-sm">
                  <ListChecks size={14} className="shrink-0 mt-0.5 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="break-words">{req.requirement_text}</p>
                    <div className="flex items-center gap-1.5 mt-1">
                      {req.category_hint ? (
                        <Badge value={req.category_hint} />
                      ) : (
                        <span className="text-xs text-muted-foreground italic">no automated check</span>
                      )}
                      <span
                        className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                          req.is_mandatory ? "bg-danger-soft text-danger" : "bg-muted text-muted-foreground"
                        }`}
                      >
                        {req.is_mandatory ? "Mandatory" : "Optional"}
                      </span>
                    </div>
                  </div>
                  {canManage && (
                    <button
                      type="button"
                      onClick={() => handleDeleteRequirement(req.id)}
                      disabled={deletingRequirementId === req.id}
                      aria-label="Delete requirement"
                      title="Delete requirement"
                      className="text-muted-foreground hover:text-danger disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      {!loading && collusionReport && collusionReport.indicators.length > 0 && (
        <Card>
          <CardHeader
            title="Collusion Radar"
            description={`Attention score: ${collusionReport.score}/100 -- transparent, rule-based indicators only.`}
          />
          <CardBody className="space-y-2">
            {collusionReport.indicators.map((ind, i) => (
              <div
                key={`${ind.code}-${i}`}
                className={`flex items-start gap-2 rounded-md px-3 py-2 text-sm ${COLLUSION_SEVERITY_CLASSES[ind.severity] ?? "bg-muted"}`}
              >
                <Radar size={14} className="shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium">{ind.label}</p>
                  <p className="text-xs mt-0.5 opacity-90">{ind.detail}</p>
                </div>
              </div>
            ))}
            <p className="text-xs text-muted-foreground pt-1">{collusionReport.disclaimer}</p>
          </CardBody>
        </Card>
      )}

      {loading ? (
        <Card>
          <CardBody>
            <SkeletonList rows={3} />
          </CardBody>
        </Card>
      ) : rows.length === 0 ? (
        <Card>
          <CardBody>
            <EmptyState
              icon={UserRound}
              title="No bidder submissions yet"
              description="Add a bidder to this procurement to begin registry verification."
              action={
                canManage ? (
                  <button onClick={() => setAddOpen(true)} className="text-sm font-medium text-primary hover:underline">
                    Add a bidder submission →
                  </button>
                ) : undefined
              }
            />
          </CardBody>
        </Card>
      ) : (
        <div className="space-y-3">
          {rows.map(({ submission, bidder, summary, lastVerifiedAt, verified }) => (
            <Card key={submission.id} className="transition-shadow hover:shadow-elevated">
              <CardBody className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="w-9 h-9 rounded-full bg-primary/10 text-primary flex items-center justify-center text-sm font-semibold shrink-0">
                    {(bidder?.legal_name ?? "?")[0]?.toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold truncate">{bidder?.legal_name ?? "Unknown bidder"}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {bidder?.pan ? `PAN ${bidder.pan}` : "No PAN on file"}
                      {submission.bid_amount != null && ` · Bid ₹${submission.bid_amount.toLocaleString("en-IN")}`}
                      {lastVerifiedAt && ` · Last checked ${new Date(lastVerifiedAt).toLocaleString()}`}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-5 shrink-0">
                  {!verified ? (
                    <span className="text-xs font-medium text-muted-foreground inline-flex items-center gap-1.5">
                      <AlertTriangle size={13} /> Not yet verified
                    </span>
                  ) : summary ? (
                    <>
                      <div className="text-right">
                        <p className="text-xs text-muted-foreground">Score</p>
                        <p className="text-sm font-semibold tabular-nums">{summary.compliance_score}/100</p>
                      </div>
                      <Badge value={summary.risk_level} withIcon />
                      {summary.critical_count > 0 && (
                        <span className="inline-flex items-center gap-1 text-xs font-semibold text-danger">
                          <ShieldAlert size={13} /> {summary.critical_count} critical
                        </span>
                      )}
                    </>
                  ) : null}
                  <Link
                    to={`/procurement-verification/${procurementId}/bidders/${submission.id}`}
                    className="inline-flex items-center gap-1 text-sm text-primary font-medium hover:underline"
                  >
                    Open <ArrowRight size={13} />
                  </Link>
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      )}

      <Modal
        open={addOpen}
        title="Add Bidder Submission"
        description="Attach an existing bidder or register a new one against this procurement."
        onClose={() => !adding && setAddOpen(false)}
        footer={
          <>
            <Button variant="outline" size="sm" onClick={() => setAddOpen(false)} disabled={adding}>
              Cancel
            </Button>
            <Button size="sm" loading={adding} disabled={!canSubmitAdd} onClick={handleAdd}>
              Add Submission
            </Button>
          </>
        }
      >
        <div className="space-y-3.5">
          <div className="flex gap-2 p-0.5 bg-muted rounded-md w-fit">
            {(["existing", "new"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                  mode === m ? "bg-surface shadow-xs text-foreground" : "text-muted-foreground"
                }`}
              >
                {m === "existing" ? "Existing bidder" : "New bidder"}
              </button>
            ))}
          </div>

          {mode === "existing" ? (
            allBidders.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No bidders registered yet -- switch to "New bidder" to create one.
              </p>
            ) : (
              <Select
                label="Bidder"
                value={selectedBidderId}
                onChange={(e) => setSelectedBidderId(e.target.value)}
              >
                <option value="">Select a bidder…</option>
                {allBidders.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.legal_name}
                    {b.pan ? ` (PAN ${b.pan})` : ""}
                  </option>
                ))}
              </Select>
            )
          ) : (
            <>
              <Input label="Legal name" value={legalName} onChange={(e) => setLegalName(e.target.value)} placeholder="ABC Engineering Private Limited" autoFocus />
              <Input label="Trade name (optional)" value={tradeName} onChange={(e) => setTradeName(e.target.value)} />
              <Input label="PAN (optional)" value={pan} onChange={(e) => setPan(e.target.value.toUpperCase())} placeholder="ABCDE1234F" />
            </>
          )}
          <Input
            label="Bid amount (optional)"
            type="number"
            value={bidAmount}
            onChange={(e) => setBidAmount(e.target.value)}
            placeholder="e.g. 4850000"
            hint="Used only by the Collusion Radar's bid-value indicators once entered for two or more bidders."
          />
        </div>
      </Modal>

      <Modal
        open={awardOpen}
        title="Mark Awarded Bidder"
        description="Records which bidder won this procurement -- feeds the Collusion Radar's repeated-winner indicator. Requires at least one officer decision already recorded for this procurement."
        onClose={() => !awarding && setAwardOpen(false)}
        footer={
          <>
            <Button variant="outline" size="sm" onClick={() => setAwardOpen(false)} disabled={awarding}>
              Cancel
            </Button>
            <Button size="sm" loading={awarding} disabled={!awardBidderId} onClick={handleSetAward}>
              Save
            </Button>
          </>
        }
      >
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No bidder submissions on this procurement yet.</p>
        ) : (
          <Select label="Awarded bidder" value={awardBidderId} onChange={(e) => setAwardBidderId(e.target.value)}>
            <option value="">Select a bidder…</option>
            {rows.map(({ bidder, submission }) =>
              bidder ? (
                <option key={submission.id} value={bidder.id}>
                  {bidder.legal_name}
                  {bidder.pan ? ` (PAN ${bidder.pan})` : ""}
                </option>
              ) : null
            )}
          </Select>
        )}
      </Modal>
    </div>
  );
}
