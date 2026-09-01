import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  Plus,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  Users,
} from "lucide-react";
import {
  createProcurement,
  getSubmissionSummary,
  getSubmissionVerification,
  listBidders,
  listComplianceCategories,
  listProcurements,
  listSubmissionsForProcurement,
  uploadTenderDocument,
} from "../api/endpoints";
import { extractErrorMessage } from "../api/client";
import { useToast } from "../context/ToastContext";
import type {
  BidderRead,
  ComplianceCategoryRead,
  ComplianceSummaryRead,
  ProcurementRead,
  RiskLevel,
  SubmissionRead,
  VerificationResultRead,
} from "../api/types";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  ConfidenceRing,
  Dropzone,
  EmptyState,
  Input,
  SkeletonList,
  SkeletonStatRow,
  StatCard,
  StatusDonut,
  useGreeting,
} from "../components/kit";

interface Row {
  procurement: ProcurementRead;
  submission: SubmissionRead;
  bidder: BidderRead | null;
  summary: ComplianceSummaryRead | null;
  results: VerificationResultRead[];
}

const RISK_RANK: Record<RiskLevel, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const STATUS_LABEL: Record<string, string> = {
  verified: "Verified",
  mismatch: "Mismatch",
  missing: "Missing",
  critical_fail: "Critical",
  not_claimed: "Not Claimed",
  not_applicable: "Not Applicable",
};
const RISK_BAR_TONE: Record<RiskLevel, string> = {
  low: "bg-success",
  medium: "bg-warning",
  high: "bg-danger/70",
  critical: "bg-danger",
};

function timeAgo(iso: string): string {
  const date = new Date(iso);
  const secs = Math.round((Date.now() - date.getTime()) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return date.toLocaleDateString();
}

/**
 * PRAMAAN Overview -- a genuine layout/density redesign (grid restructure,
 * sidebar density, table-based panels), still built entirely from data
 * this page already fetches plus one additive call per submission
 * (getSubmissionVerification(), the same endpoint BidderVerification.tsx
 * already uses one screen down) -- no new backend endpoints, no invented
 * metrics. Where the reference design showed a metric this API surface
 * genuinely can't produce (a global cross-submission activity feed, due
 * dates, a "Completed" submission status that doesn't exist in
 * SubmissionStatus), the real available field/derivation is used instead
 * and disclosed in the implementation report rather than fabricated here.
 */
export default function Dashboard() {
  const [loading, setLoading] = useState(true);
  const { notify } = useToast();
  const navigate = useNavigate();
  const greeting = useGreeting();
  const [procurements, setProcurements] = useState<ProcurementRead[]>([]);
  const [categories, setCategories] = useState<ComplianceCategoryRead[]>([]);
  const [rows, setRows] = useState<Row[]>([]);

  // Empty-state quick-create -- create a procurement and, if a tender PDF
  // is attached, upload it in the same flow (see procurement_requirement_
  // service.py's Requirement-to-Evidence Mapping engine). The tender
  // document is optional: a title alone is enough to create a procurement,
  // same as the full Procurements page.
  const [quickTitle, setQuickTitle] = useState("");
  const [quickFile, setQuickFile] = useState<File | null>(null);
  const [quickCreating, setQuickCreating] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [procs, bidders, cats] = await Promise.all([
          listProcurements(),
          listBidders(),
          listComplianceCategories(),
        ]);
        setProcurements(procs);
        setCategories(cats);
        const biddersById = new Map(bidders.map((b) => [b.id, b]));

        const perProcurement = await Promise.all(
          procs.map(async (procurement) => {
            const submissions = await listSubmissionsForProcurement(procurement.id).catch(() => []);
            return Promise.all(
              submissions.map(async (submission): Promise<Row> => {
                const [summary, results] = await Promise.all([
                  getSubmissionSummary(submission.id).catch(() => null),
                  getSubmissionVerification(submission.id).catch(() => [] as VerificationResultRead[]),
                ]);
                return {
                  procurement,
                  submission,
                  bidder: biddersById.get(submission.bidder_id) ?? null,
                  summary,
                  results,
                };
              })
            );
          })
        );
        setRows(perProcurement.flat());
      } catch (err) {
        notify("error", extractErrorMessage(err));
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scoredRows = useMemo(() => rows.filter((r) => r.summary != null), [rows]);
  const criticalCount = useMemo(() => rows.filter((r) => (r.summary?.critical_count ?? 0) > 0).length, [rows]);

  const needsAttention = useMemo(() => {
    return rows
      .filter((r) => !r.summary || r.summary.critical_count > 0 || r.summary.risk_level === "high" || r.summary.risk_level === "critical")
      .sort((a, b) => {
        const ra = a.summary ? RISK_RANK[a.summary.risk_level] : 4;
        const rb = b.summary ? RISK_RANK[b.summary.risk_level] : 4;
        return ra - rb;
      })
      .slice(0, 6)
      .map((r) => {
        const lastCheckedAt = r.results.length
          ? r.results.reduce((latest, res) => (res.checked_at > latest ? res.checked_at : latest), r.results[0].checked_at)
          : null;
        const type = !r.summary ? "Not Verified" : r.summary.critical_count > 0 ? "Critical Finding" : "High Risk";
        const item = r.summary?.critical_categories?.[0] ?? (r.summary ? "Mandatory category unresolved" : "—");
        return { ...r, lastCheckedAt, type, item };
      });
  }, [rows]);

  // Real distribution of already-fetched summary.risk_level values -- no
  // fabricated buckets, "critical"/"high"/"medium"/"low" only, same
  // vocabulary compliance_summary_service.py produces.
  const riskCounts = useMemo(() => {
    const counts: Record<RiskLevel, number> = { critical: 0, high: 0, medium: 0, low: 0 };
    for (const r of scoredRows) counts[r.summary!.risk_level]++;
    return counts;
  }, [scoredRows]);
  const maxRiskCount = Math.max(1, riskCounts.low, riskCounts.medium, riskCounts.high, riskCounts.critical);

  const avgScore = useMemo(() => {
    if (scoredRows.length === 0) return null;
    return scoredRows.reduce((sum, r) => sum + r.summary!.compliance_score, 0) / scoredRows.length;
  }, [scoredRows]);

  // Ring tone must never soften a critical/high submission into looking
  // "safe" just because it's diluted by an average -- same principle as
  // BidderVerification.tsx's per-submission ring (see ConfidenceBar.tsx).
  const overallRiskLevel: RiskLevel | undefined = riskCounts.critical > 0 ? "critical" : riskCounts.high > 0 ? "high" : undefined;

  const statusSegments = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of rows) for (const res of r.results) counts[res.status] = (counts[res.status] ?? 0) + 1;
    return Object.entries(counts)
      .filter(([, count]) => count > 0)
      .map(([key, count]) => ({ key, label: STATUS_LABEL[key] ?? key, count }));
  }, [rows]);
  const totalResults = statusSegments.reduce((sum, s) => sum + s.count, 0);

  const categorySummary = useMemo(() => {
    const byCode = new Map<string, { name: string; verified: number; total: number }>();
    for (const r of rows) {
      for (const res of r.results) {
        if (res.status === "not_applicable" || res.status === "not_claimed") continue;
        const entry = byCode.get(res.category_code) ?? { name: res.category_name, verified: 0, total: 0 };
        entry.total += 1;
        if (res.status === "verified") entry.verified += 1;
        byCode.set(res.category_code, entry);
      }
    }
    const order = new Map(categories.map((c, i) => [c.code, i]));
    return Array.from(byCode.entries())
      .map(([code, v]) => ({ code, ...v }))
      .sort((a, b) => (order.get(a.code) ?? 99) - (order.get(b.code) ?? 99));
  }, [rows, categories]);

  const recentVerifications = useMemo(() => {
    return rows
      .map((r) => {
        const lastVerifiedAt = r.results.length
          ? r.results.reduce((latest, res) => (res.checked_at > latest ? res.checked_at : latest), r.results[0].checked_at)
          : null;
        return { ...r, lastVerifiedAt };
      })
      .filter((r) => r.lastVerifiedAt)
      .sort((a, b) => (b.lastVerifiedAt! > a.lastVerifiedAt! ? 1 : -1))
      .slice(0, 6);
  }, [rows]);

  const isEmpty = !loading && procurements.length === 0;
  const goto = (procurementId: string, submissionId: string) =>
    navigate(`/procurement-verification/${procurementId}/bidders/${submissionId}`);

  const handleQuickCreate = async () => {
    const title = quickTitle.trim();
    if (!title) return;
    setQuickCreating(true);
    try {
      const procurement = await createProcurement({ title });
      if (quickFile) {
        // Best-effort -- the procurement itself is already created and
        // useful even if the tender document upload/extraction fails, so
        // a failure here is surfaced as a warning, not a blocker.
        await uploadTenderDocument(procurement.id, quickFile).catch((err) =>
          notify("error", `Procurement created, but the tender document didn't upload: ${extractErrorMessage(err)}`)
        );
      }
      notify("success", `${title} created.`);
      navigate(`/procurement-verification/${procurement.id}`);
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setQuickCreating(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{greeting} 👋</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Procurement verification overview — bidders and findings across every procurement you're verifying.
        </p>
      </div>

      {isEmpty ? (
        <Card>
          <CardBody className="p-6 md:p-8">
            <div className="grid md:grid-cols-2 gap-8">
              {/* Left: what PRAMAAN does + the 3-step workflow */}
              <div>
                <div className="flex items-center gap-3 mb-2">
                  <div className="w-10 h-10 rounded-full bg-primary/10 text-primary flex items-center justify-center shrink-0">
                    <ShieldCheck size={18} />
                  </div>
                  <h2 className="text-base font-semibold">Create your first procurement</h2>
                </div>
                <p className="text-sm text-muted-foreground">
                  PRAMAAN verifies bidder submissions against simulated government registries. Create a GeM
                  procurement, attach the tender document now (or later), then bring bidders through verification
                  to a recorded decision.
                </p>

                <div className="mt-5 space-y-3">
                  {[
                    { step: "1", text: "Create a procurement" },
                    { step: "2", text: "Add a bidder and upload their documents" },
                    { step: "3", text: "Verify compliance and record an officer decision" },
                  ].map((s) => (
                    <div key={s.step} className="flex items-center gap-3 text-sm">
                      <span className="w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold flex items-center justify-center shrink-0">
                        {s.step}
                      </span>
                      <span className="text-foreground">{s.text}</span>
                    </div>
                  ))}
                </div>

                <div className="mt-6 grid grid-cols-3 gap-3">
                  {[
                    { icon: FileText, label: "Simulated GST, PAN, Udyam, MCA21 & more" },
                    { icon: ShieldAlert, label: "Authenticity & collusion checks" },
                    { icon: CheckCircle2, label: "Auditable officer decisions" },
                  ].map((f) => (
                    <div key={f.label} className="rounded-md border border-border px-3 py-2.5">
                      <f.icon size={14} className="text-primary mb-1.5" />
                      <p className="text-[11px] text-muted-foreground leading-snug">{f.label}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Right: quick-create form */}
              <div className="rounded-lg border border-border bg-surface-hover/40 p-5 space-y-3.5">
                <p className="text-sm font-semibold text-foreground">Quick create</p>
                <Input
                  label="Procurement title"
                  value={quickTitle}
                  onChange={(e) => setQuickTitle(e.target.value)}
                  placeholder="e.g. Supply of Networking Equipment — GeM/2026/B/1234"
                />
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-1.5">Tender document (optional)</p>
                  <Dropzone
                    file={quickFile}
                    onFileSelected={setQuickFile}
                    accept="application/pdf,.doc,.docx"
                    hint="PDF or Word, up to 50MB — eligibility requirements are extracted automatically"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleQuickCreate}
                  disabled={!quickTitle.trim() || quickCreating}
                  className="w-full inline-flex items-center justify-center gap-1.5 rounded-md bg-primary text-primary-foreground text-sm font-medium py-2.5 hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Plus size={14} /> {quickCreating ? "Creating…" : "Create Procurement"}
                </button>
                <Link
                  to="/procurement-verification"
                  className="block text-center text-xs text-muted-foreground hover:text-foreground hover:underline"
                >
                  Or go to the Procurements page for the full form
                </Link>
              </div>
            </div>
          </CardBody>
        </Card>
      ) : (
        <>
          {/* KPI row -- 5 equal columns */}
          {loading ? (
            <SkeletonStatRow />
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5">
              <StatCard
                label="Procurements"
                value={procurements.length}
                icon={<FileText size={16} />}
                tone="info"
                trend="GeM procurements on file"
                linkTo="/procurement-verification"
                linkLabel="View all"
              />
              <StatCard
                label="Bidder Submissions"
                value={rows.length}
                icon={<Users size={16} />}
                tone="primary"
                trend="Across all procurements"
                linkTo="/procurement-verification"
                linkLabel="View all"
              />
              <StatCard
                label="Completed Verifications"
                value={scoredRows.length}
                icon={<CheckCircle2 size={16} />}
                tone="success"
                trend="Submissions checked at least once"
                linkTo="/procurement-verification"
                linkLabel="View all"
              />
              <StatCard
                label="Critical Findings"
                value={criticalCount}
                icon={<ShieldAlert size={16} />}
                tone={criticalCount > 0 ? "danger" : "success"}
                trend={criticalCount > 0 ? "Blacklist / PAN mismatch or worse" : "None outstanding"}
                linkTo="#needs-attention"
                linkLabel="Review"
              />
              <StatCard
                label="Needs Attention"
                value={needsAttention.length}
                icon={<AlertTriangle size={16} />}
                tone={needsAttention.length > 0 ? "warning" : "success"}
                trend={needsAttention.length > 0 ? "Awaiting officer review" : "All caught up"}
                linkTo="#needs-attention"
                linkLabel="Open queue"
              />
            </div>
          )}

          {/* Operational analytics row -- 4 equal-weight columns */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3.5 items-stretch">
            <Card className="flex flex-col">
              <CardHeader title="Verification Status" description="Every checked category, all submissions." />
              <CardBody className="flex-1 flex items-center justify-center">
                {loading ? (
                  <SkeletonList rows={3} />
                ) : totalResults === 0 ? (
                  <p className="text-sm text-muted-foreground text-center">No categories verified yet.</p>
                ) : (
                  <StatusDonut segments={statusSegments} centerLabel={String(totalResults)} centerSubLabel="Checks" size={92} />
                )}
              </CardBody>
            </Card>

            <Card className="flex flex-col">
              <CardHeader title="Risk Level Distribution" description="Scored bidder submissions, by risk." />
              <CardBody className="flex-1">
                {loading ? (
                  <SkeletonList rows={3} />
                ) : scoredRows.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-6">No submissions scored yet.</p>
                ) : (
                  <div className="flex items-end justify-between gap-3 h-28 px-1">
                    {(["low", "medium", "high", "critical"] as RiskLevel[]).map((level) => (
                      <div key={level} className="flex flex-col items-center gap-1.5 flex-1 h-full justify-end">
                        <span className="text-xs font-semibold tabular-nums">{riskCounts[level]}</span>
                        <div className="w-full flex-1 flex items-end">
                          <div
                            className={`w-full rounded-t ${RISK_BAR_TONE[level]}`}
                            style={{ height: `${Math.max(4, (riskCounts[level] / maxRiskCount) * 100)}%` }}
                          />
                        </div>
                        <span className="text-[10px] text-muted-foreground capitalize">{level}</span>
                      </div>
                    ))}
                  </div>
                )}
              </CardBody>
            </Card>

            <Card className="flex flex-col">
              <CardHeader title="Overall Compliance Score" description="Averaged across scored submissions." />
              <CardBody className="flex-1 flex flex-col items-center justify-center gap-1.5">
                {loading ? (
                  <SkeletonList rows={2} />
                ) : avgScore == null ? (
                  <p className="text-sm text-muted-foreground text-center">No submissions scored yet.</p>
                ) : (
                  <>
                    <ConfidenceRing value={avgScore / 100} riskLevel={overallRiskLevel} size={92} />
                    <p className="text-[11px] text-muted-foreground text-center">
                      {scoredRows.length} scored submission{scoredRows.length === 1 ? "" : "s"}
                    </p>
                  </>
                )}
              </CardBody>
            </Card>

            <Card className="flex flex-col">
              <CardHeader title="Quick Actions" />
              <CardBody className="flex-1 space-y-0.5">
                <Link
                  to="/procurement-verification"
                  className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] font-medium text-foreground hover:bg-surface-hover transition-colors"
                >
                  <Plus size={14} className="text-primary shrink-0" /> Create Procurement
                </Link>
                <Link
                  to="/procurement-verification"
                  className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] font-medium text-foreground hover:bg-surface-hover transition-colors"
                >
                  <Users size={14} className="text-primary shrink-0" /> Add Bidder
                </Link>
                <Link
                  to="/procurement-verification"
                  className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] font-medium text-foreground hover:bg-surface-hover transition-colors"
                >
                  <UploadCloud size={14} className="text-primary shrink-0" /> Upload Documents
                </Link>
                <a
                  href="#needs-attention"
                  className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] font-medium text-foreground hover:bg-surface-hover transition-colors"
                >
                  <ShieldCheck size={14} className="text-primary shrink-0" /> Open Verification Queue
                </a>
                <div
                  aria-disabled="true"
                  title="Not available yet"
                  className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-[13px] font-medium text-muted-foreground/50 cursor-not-allowed"
                >
                  <span className="flex items-center gap-2.5">
                    <Sparkles size={14} className="shrink-0" /> Generate Report
                  </span>
                  <span className="text-[9px] font-semibold uppercase tracking-wide bg-muted text-muted-foreground rounded px-1.5 py-0.5 shrink-0">
                    Soon
                  </span>
                </div>
              </CardBody>
            </Card>
          </div>

          {/* Attention (table) + category breakdown */}
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3.5 items-start">
            <Card id="needs-attention" className="xl:col-span-2 flex flex-col scroll-mt-6">
              <CardHeader title="Needs Your Attention" description="Critical or high-risk bidder submissions, and any not yet verified." />
              <CardBody className="!p-0 h-80 overflow-y-auto">
                {loading ? (
                  <div className="px-6 py-4">
                    <SkeletonList rows={3} />
                  </div>
                ) : needsAttention.length === 0 ? (
                  <div className="px-6 py-4">
                    <EmptyState compact icon={CheckCircle2} title="Nothing needs attention" description="Every verified bidder submission is currently clean." />
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border text-left text-xs text-muted-foreground sticky top-0 bg-surface">
                          <th className="px-5 py-2 font-medium">Type</th>
                          <th className="px-3 py-2 font-medium">Item</th>
                          <th className="px-3 py-2 font-medium">Bidder</th>
                          <th className="px-3 py-2 font-medium">Procurement</th>
                          <th className="px-3 py-2 font-medium">Risk</th>
                          <th className="px-5 py-2 font-medium">Last Checked</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {needsAttention.map((r) => (
                          <tr
                            key={r.submission.id}
                            onClick={() => goto(r.procurement.id, r.submission.id)}
                            className="cursor-pointer hover:bg-surface-hover transition-colors"
                          >
                            <td className="px-5 py-2.5 whitespace-nowrap">
                              <span className="inline-flex items-center gap-1.5 text-xs font-medium">
                                {r.type === "Critical Finding" ? (
                                  <ShieldAlert size={13} className="text-danger shrink-0" />
                                ) : (
                                  <AlertTriangle size={13} className="text-warning shrink-0" />
                                )}
                                {r.type}
                              </span>
                            </td>
                            <td className="px-3 py-2.5 text-muted-foreground truncate max-w-[160px]">{r.item}</td>
                            <td className="px-3 py-2.5 font-medium text-foreground truncate max-w-[140px]">
                              {r.bidder?.legal_name ?? "Unknown bidder"}
                            </td>
                            <td className="px-3 py-2.5 text-muted-foreground truncate max-w-[160px]">{r.procurement.title}</td>
                            <td className="px-3 py-2.5">
                              {r.summary ? <Badge value={r.summary.risk_level} /> : <span className="text-xs text-muted-foreground">—</span>}
                            </td>
                            <td className="px-5 py-2.5 text-muted-foreground whitespace-nowrap text-xs">
                              {r.lastCheckedAt ? timeAgo(r.lastCheckedAt) : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardBody>
            </Card>

            <Card className="flex flex-col">
              <CardHeader title="Verification by Category" description="Verified out of every checked instance." />
              <CardBody className="h-80 overflow-y-auto">
                {loading ? (
                  <SkeletonList rows={4} />
                ) : categorySummary.length === 0 ? (
                  <EmptyState compact icon={FileText} title="No categories checked yet" description="Run verification on a bidder submission to see coverage here." />
                ) : (
                  <div className="space-y-3">
                    {categorySummary.map((c) => {
                      const pct = c.total > 0 ? Math.round((c.verified / c.total) * 100) : 0;
                      return (
                        <div key={c.code}>
                          <div className="flex items-center justify-between text-xs mb-1">
                            <span className="font-medium text-foreground truncate">{c.name}</span>
                            <span className="text-muted-foreground tabular-nums shrink-0 ml-2">
                              {c.verified}/{c.total}
                            </span>
                          </div>
                          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                            <div
                              className={pct === 100 ? "h-full rounded-full bg-success" : pct >= 50 ? "h-full rounded-full bg-warning" : "h-full rounded-full bg-danger"}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardBody>
            </Card>
          </div>

          {/* Recent verifications -- full width table */}
          <Card>
            <CardHeader
              title="Recent Verifications"
              action={
                <Link to="/procurement-verification" className="text-xs font-medium text-primary hover:underline">
                  View all
                </Link>
              }
            />
            <CardBody className="!p-0">
              {loading ? (
                <div className="px-6 py-5">
                  <SkeletonList rows={4} />
                </div>
              ) : recentVerifications.length === 0 ? (
                <div className="px-6 py-5">
                  <EmptyState compact icon={FileText} title="No verifications yet" description="Once you run verification on a bidder submission, recent results appear here." />
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-xs text-muted-foreground">
                        <th className="px-6 py-2 font-medium">Bidder</th>
                        <th className="px-3 py-2 font-medium">Procurement</th>
                        <th className="px-3 py-2 font-medium">Score</th>
                        <th className="px-3 py-2 font-medium">Risk</th>
                        <th className="px-3 py-2 font-medium">Status</th>
                        <th className="px-6 py-2 font-medium">Verified On</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {recentVerifications.map((r) => (
                        <tr
                          key={r.submission.id}
                          onClick={() => goto(r.procurement.id, r.submission.id)}
                          className="cursor-pointer hover:bg-surface-hover transition-colors"
                        >
                          <td className="px-6 py-2.5 font-medium text-foreground">{r.bidder?.legal_name ?? "Unknown bidder"}</td>
                          <td className="px-3 py-2.5 text-muted-foreground truncate max-w-[200px]">{r.procurement.title}</td>
                          <td className="px-3 py-2.5 tabular-nums">{r.summary ? `${r.summary.compliance_score}/100` : "—"}</td>
                          <td className="px-3 py-2.5">{r.summary && <Badge value={r.summary.risk_level} />}</td>
                          <td className="px-3 py-2.5">
                            <Badge value={r.submission.status} />
                          </td>
                          <td className="px-6 py-2.5 text-muted-foreground whitespace-nowrap text-xs">
                            {r.lastVerifiedAt ? new Date(r.lastVerifiedAt).toLocaleString() : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardBody>
          </Card>
        </>
      )}
    </div>
  );
}
