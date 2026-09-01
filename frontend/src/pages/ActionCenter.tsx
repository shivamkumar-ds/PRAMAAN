import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  confirmRequirement,
  getEvaluation,
  listMissions,
  overrideQualificationGap,
  removeQualificationOverride,
  runEvaluation,
  unconfirmRequirement,
} from "../api/endpoints";
import { extractErrorMessage } from "../api/client";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";
import { tenderDisplayName } from "../lib/tenderName";
import { recommendationLabel } from "../lib/recommendationLabels";
import { forwardLookingGap } from "../lib/forwardLookingGap";
import { remediationCounts, formatTypedProgress, RECOMMENDATION_URGENCY_RANK } from "../lib/remediationCounts";
import { groupByTheme, type ThemedGroup } from "../lib/actionCenterThemes";
import { cn } from "../lib/cn";
import type { EvaluationResponse, GapAnalysisEntry, MissionRead } from "../api/types";
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, SkeletonList } from "../components/kit";
import {
  AlertOctagon,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileSearch,
  Layers,
  RefreshCw,
  ShieldCheck,
  ShieldQuestion,
  Sparkles,
  Target,
  X,
} from "lucide-react";

type EvaluatedEntry = { mission: MissionRead; evaluation: EvaluationResponse };

// Merges blocked_items + action_required_items into one "Bid Preparation"
// list, each item tagged with which of the two it actually came from --
// see remediationCounts.ts's docstring for why they're combined for
// display but the underlying backend distinction (mandatory/blocked vs.
// non-mandatory/action-required) is preserved per-item rather than lost.
// This remains the flat, ungrouped source of truth for counting
// (remediationCounts.bidPrep, list-view cards) -- theming (see
// lib/actionCenterThemes.ts) is a display-only layer applied on top of
// this same list inside the detail view below, never a second source of
// items.
function bidPrepItems(evaluation: EvaluationResponse): { item: GapAnalysisEntry; blocked: boolean }[] {
  return [
    ...evaluation.remediation_summary.blocked_items.map((item) => ({ item, blocked: true })),
    ...evaluation.remediation_summary.action_required_items.map((item) => ({ item, blocked: false })),
  ];
}

// Splits bidPrepItems() into the two sub-groups the detail view renders
// separately -- unconfirmed (still needs action, shown first/prominent)
// and confirmed (resolved, shown after, visually quiet). A row's
// item.confirmed is the single source of truth for which group it's in;
// there is deliberately no third, mixed state.
function splitBidPrep(items: { item: GapAnalysisEntry; blocked: boolean }[]) {
  return {
    unconfirmed: items.filter(({ item }) => !item.confirmed),
    confirmed: items.filter(({ item }) => item.confirmed),
  };
}

// remediationCounts().total intentionally counts raw bucket membership
// (blocked_items/action_required_items never shrink on confirmation --
// decision_engine.classify_remediation()'s own docstring: confirmed
// items stay visible in their bucket rather than disappearing). That's
// correct for remediation_summary itself, but the Action Center's own
// "is this tender clear" / "Continue fixing" vs "Review" framing must
// not keep telling the user something is still outstanding once every
// bid-prep item on it has actually been confirmed -- otherwise the list
// view would contradict the same "everything confirmed" state the
// detail view now shows plainly. This subtracts confirmed bid-prep
// items from the outstanding total; qualification/coverage/human-review
// counts are untouched since nothing in this feature ever confirms them.
function effectivelyClear(evaluation: EvaluationResponse): boolean {
  const counts = remediationCounts(evaluation.remediation_summary);
  const unresolvedBidPrep = splitBidPrep(bidPrepItems(evaluation)).unconfirmed.length;
  return counts.qualification === 0 && unresolvedBidPrep === 0 && counts.coverage === 0 && counts.humanReview === 0;
}

export default function ActionCenter() {
  const { notify } = useToast();
  const { user } = useAuth();
  // POST/DELETE .../confirm are admin-only server-side (require_administrator)
  // -- hiding the button for non-admins avoids a confusing 403 on click,
  // same convention as Capabilities.tsx's canDeleteCapabilities/canCreateManually.
  const canConfirmReadiness = user?.role === "administrator";
  const [searchParams, setSearchParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [missions, setMissions] = useState<MissionRead[]>([]);
  const [evaluated, setEvaluated] = useState<EvaluatedEntry[]>([]);
  const [failedMissionIds, setFailedMissionIds] = useState<string[]>([]);
  const [rerunningId, setRerunningId] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [overridingId, setOverridingId] = useState<string | null>(null);
  // Session-only "what changed" feedback after a re-run -- never persisted,
  // never presented as durable history (V1 scope: no backend snapshot/diff
  // API exists yet). Cleared whenever the user leaves the detail view.
  const [lastRerunNote, setLastRerunNote] = useState<{ missionId: string; text: string } | null>(null);

  const selectedMissionId = searchParams.get("mission");

  const load = async () => {
    setLoading(true);
    try {
      const missionList = (await listMissions()).filter((m) => m.status !== "archived");
      setMissions(missionList);

      const reportable = missionList.filter((m) => m.recommendation_id);
      const failed: string[] = [];
      const results = await Promise.all(
        reportable.map(async (m) => {
          try {
            return { mission: m, evaluation: await getEvaluation(m.id) };
          } catch {
            failed.push(m.id);
            return null;
          }
        })
      );
      setEvaluated(results.filter((r): r is EvaluatedEntry => r !== null));
      setFailedMissionIds(failed);
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const notYetEvaluated = useMemo(() => missions.filter((m) => !m.recommendation_id), [missions]);

  const sortedEvaluated = useMemo(
    () =>
      evaluated.slice().sort((a, b) => {
        const rankDiff =
          RECOMMENDATION_URGENCY_RANK[a.evaluation.recommendation.recommendation_type] -
          RECOMMENDATION_URGENCY_RANK[b.evaluation.recommendation.recommendation_type];
        if (rankDiff !== 0) return rankDiff;
        return remediationCounts(b.evaluation.remediation_summary).total - remediationCounts(a.evaluation.remediation_summary).total;
      }),
    [evaluated]
  );

  const allClear = evaluated.length > 0 && failedMissionIds.length === 0 && evaluated.every((e) => effectivelyClear(e.evaluation));

  const selected = selectedMissionId ? evaluated.find((e) => e.mission.id === selectedMissionId) ?? null : null;

  const openMission = (missionId: string) => setSearchParams({ mission: missionId });
  const closeDetail = () => setSearchParams({});

  const handleRerun = async (missionId: string) => {
    const before = evaluated.find((e) => e.mission.id === missionId)?.evaluation.remediation_summary;
    setRerunningId(missionId);
    try {
      const result = await runEvaluation(missionId);
      setEvaluated((prev) => prev.map((e) => (e.mission.id === missionId ? { ...e, evaluation: result } : e)));

      if (before) {
        const beforeCounts = remediationCounts(before);
        const afterCounts = remediationCounts(result.remediation_summary);
        const deltas: string[] = [];
        (["qualification", "bidPrep", "coverage", "humanReview"] as const).forEach((key) => {
          const diff = beforeCounts[key] - afterCounts[key];
          if (diff > 0) {
            const label = { qualification: "qualification gap", bidPrep: "bid item", coverage: "coverage item", humanReview: "review item" }[key];
            deltas.push(`${diff} ${label}${diff === 1 ? "" : "s"} resolved`);
          }
        });
        const text = deltas.length > 0 ? `Evaluation updated — ${deltas.join(", ")}.` : "Evaluation updated — no change in outstanding items.";
        setLastRerunNote({ missionId, text });
        notify("success", text);
      } else {
        notify("success", "Evaluation updated.");
      }
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setRerunningId(null);
    }
  };

  const retryFailed = () => load();

  // Confirm/unconfirm both refetch the mission's evaluation afterward
  // rather than optimistically patching local state -- confirming can
  // change remediation_summary.bid_readiness itself (compute_bid_readiness()
  // with confirmed_requirement_ids), so the server response is the only
  // source of truth for what's still outstanding. Never touches
  // qualification -- the backend boundary rule, not re-implemented here.
  const handleConfirm = async (missionId: string, requirementId: string) => {
    setConfirmingId(requirementId);
    try {
      await confirmRequirement(missionId, requirementId);
      const result = await getEvaluation(missionId);
      setEvaluated((prev) => prev.map((e) => (e.mission.id === missionId ? { ...e, evaluation: result } : e)));
      notify("success", "Marked as prepared.");
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setConfirmingId(null);
    }
  };

  const handleUnconfirm = async (missionId: string, requirementId: string) => {
    setConfirmingId(requirementId);
    try {
      await unconfirmRequirement(missionId, requirementId);
      const result = await getEvaluation(missionId);
      setEvaluated((prev) => prev.map((e) => (e.mission.id === missionId ? { ...e, evaluation: result } : e)));
      notify("success", "Confirmation removed.");
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setConfirmingId(null);
    }
  };

  // Override/remove-override -- an explicit, audited administrator risk
  // acceptance on a mandatory CAPABILITY_CLAIM qualification gap (see
  // decision_engine.compute_qualification()'s overridden_requirement_ids
  // boundary rule and qualification_override_service.py). Always refetches
  // rather than optimistically patching -- overriding changes
  // remediation_summary.qualification and recommendation_type themselves
  // (live-recomputed server-side, same GET-time mechanism confirm/unconfirm
  // already rely on), so the server response is the only source of truth.
  // Never touches bid readiness -- the mirror-image boundary rule.
  const handleOverride = async (missionId: string, requirementId: string, note: string) => {
    setOverridingId(requirementId);
    try {
      await overrideQualificationGap(missionId, requirementId, note);
      const result = await getEvaluation(missionId);
      setEvaluated((prev) => prev.map((e) => (e.mission.id === missionId ? { ...e, evaluation: result } : e)));
      notify("success", "Requirement marked Pass (administrator override).");
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setOverridingId(null);
    }
  };

  const handleRemoveOverride = async (missionId: string, requirementId: string) => {
    setOverridingId(requirementId);
    try {
      await removeQualificationOverride(missionId, requirementId);
      const result = await getEvaluation(missionId);
      setEvaluated((prev) => prev.map((e) => (e.mission.id === missionId ? { ...e, evaluation: result } : e)));
      notify("success", "Override removed -- back to Not Pass.");
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setOverridingId(null);
    }
  };

  // Themed-group confirm/unconfirm -- calls the EXISTING per-requirement
  // confirm/unconfirm endpoint for every requirement_id in the group via
  // Promise.allSettled (not Promise.all: a single rejection must not
  // prevent the successful items from being reported), then one refetch.
  // No new bulk-confirm backend endpoint exists or is added for this.
  // Returns the requirement_ids that failed so the caller (GroupCard) can
  // let the user retry just those.
  const handleConfirmGroupItems = async (
    missionId: string,
    requirementIds: string[],
    mode: "confirm" | "unconfirm"
  ): Promise<string[]> => {
    const call = mode === "confirm" ? confirmRequirement : unconfirmRequirement;
    const results = await Promise.allSettled(requirementIds.map((id) => call(missionId, id)));
    const failed = requirementIds.filter((_, i) => results[i].status === "rejected");
    const succeededCount = requirementIds.length - failed.length;
    if (succeededCount > 0) {
      const result = await getEvaluation(missionId);
      setEvaluated((prev) => prev.map((e) => (e.mission.id === missionId ? { ...e, evaluation: result } : e)));
    }
    if (failed.length === 0) {
      notify("success", mode === "confirm" ? `${succeededCount} item(s) marked as prepared.` : `${succeededCount} item(s) unconfirmed.`);
    } else if (succeededCount > 0) {
      notify("error", `${succeededCount} succeeded, ${failed.length} failed -- retry the failed item(s).`);
    } else {
      notify("error", "Nothing could be confirmed -- please retry.");
    }
    return failed;
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Action Center</h1>
          <p className="text-sm text-muted-foreground mt-1">Your path from assessment to bid-ready.</p>
        </div>
        <Card>
          <CardBody>
            <SkeletonList rows={3} />
          </CardBody>
        </Card>
      </div>
    );
  }

  // Detail view -- one tender's remediation story, driven entirely by its
  // own EvaluationResponse.remediation_summary. Never reconstructs
  // qualification/readiness/coverage/review classification client-side.
  if (selected) {
    const { mission, evaluation } = selected;
    const remediation = evaluation.remediation_summary;
    const counts = remediationCounts(remediation);
    const bidPrep = bidPrepItems(evaluation);
    const { unconfirmed: bidPrepUnconfirmed, confirmed: bidPrepConfirmed } = splitBidPrep(bidPrep);
    const bidPrepAllConfirmed = bidPrep.length > 0 && bidPrepUnconfirmed.length === 0;

    // Themed grouping (Action Center V-next, presentation-only -- see
    // lib/actionCenterThemes.ts's own docstring): the FUTURE_CONTRACTUAL_COMMITMENT
    // subset of the still-unconfirmed bid-prep items is clustered into
    // named themes (Safety & PPE, Labour & statutory compliance, etc) for
    // display. Everything else in bid prep -- blocked/non-mandatory
    // SUBMISSION_GATING items, and PROCEDURAL items (deadlines/submission-
    // format/evaluation-criteria clauses, which classify_remediation()
    // also routes into action_required_items and which are never
    // confirmable -- see GapRow's isConfirmable) -- stays individual and
    // ungrouped, exactly as before this feature.
    const commitmentUnconfirmed = bidPrepUnconfirmed.filter(({ item }) => item.requirement_nature === "future_contractual_commitment");
    const restUnconfirmed = bidPrepUnconfirmed.filter(({ item }) => item.requirement_nature !== "future_contractual_commitment");
    const { groups: themedGroups, individual: commitmentIndividual } = groupByTheme(
      commitmentUnconfirmed.map(({ item }) => item)
    );

    // Total confirmed items across every confirmable bucket on this
    // mission -- feeds the final, quiet "Completed" summary area at the
    // bottom of the page (structure point 3). Only bid-prep items are
    // ever confirmable today (see GapRow's isConfirmable), but this stays
    // written generically in case that set ever grows.
    const totalConfirmed = bidPrepConfirmed.length;
    const note = lastRerunNote && lastRerunNote.missionId === mission.id ? lastRerunNote.text : null;
    // Typed progress summary -- replaces a single flat "N remaining"
    // figure with per-kind counts (see remediationCounts.formatTypedProgress).
    const typedProgress = formatTypedProgress(counts, bidPrepUnconfirmed.length, bidPrepConfirmed.length);
    // "Path to GO" numbered checklist -- ++step only fires for a section
    // that actually renders (JS short-circuits the right side of && when
    // the condition is falsy), so numbering stays contiguous (1, 2, 3...)
    // regardless of which sections a given tender happens to have.
    let step = 0;

    return (
      <div className="space-y-6">
        <button
          type="button"
          onClick={closeDetail}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft size={14} /> Back to Action Center
        </button>

        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5 flex-wrap">
              <h1 className="text-2xl font-semibold tracking-tight">{tenderDisplayName(mission)}</h1>
              <Badge value={evaluation.recommendation.recommendation_type} label={recommendationLabel(evaluation.recommendation.recommendation_type)} withIcon />
            </div>
            <p className="text-sm text-muted-foreground mt-1">Path to GO — what's still needed to move this tender forward.</p>
            <p className="text-xs font-medium text-muted-foreground mt-1.5">{typedProgress}</p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button variant="outline" size="sm" icon={<RefreshCw size={14} />} loading={rerunningId === mission.id} onClick={() => handleRerun(mission.id)}>
              Re-run Evaluation
            </Button>
            <Link
              to={`/missions/${mission.id}`}
              className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-md border border-border text-sm font-medium hover:bg-surface-hover transition-colors"
            >
              Open in Tender Workspace <ExternalLink size={13} />
            </Link>
          </div>
        </div>

        {note && (
          <div className="rounded-lg border border-info/30 bg-info-soft px-4 py-3 text-sm text-info">
            {note}
            <span className="block text-xs text-info/80 mt-0.5">This reflects this session only -- not a saved history.</span>
          </div>
        )}

        <div className="space-y-6">
          {/* "Nothing blocking" banner -- driven by the four core buckets
              only (counts.total), same as the Action Center list card.
              optional_capability_gaps never factors into this: the backend
              itself doesn't treat it as a qualification or readiness risk
              (see compute_qualification()/compute_bid_readiness()), so this
              banner would misrepresent it as one if it did. When optional
              items exist, the banner says so and points at the Review
              Required section below instead of going silent about them. */}
          {counts.total === 0 && (
            <Card className="border-success/30">
              <CardBody>
                <div className="flex items-center gap-3">
                  <CheckCircle2 size={22} className="text-success shrink-0" />
                  <div>
                    <p className="text-sm font-semibold">
                      {counts.reviewOptional > 0 ? "Nothing blocking on this tender." : "Nothing outstanding on this tender."}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {counts.reviewOptional > 0
                        ? `No qualification gaps, bid-preparation actions, coverage issues, or review items -- ${counts.reviewOptional} optional item${
                            counts.reviewOptional === 1 ? "" : "s"
                          } below.`
                        : "No qualification gaps, bid-preparation actions, coverage issues, or review items."}
                    </p>
                  </div>
                </div>
              </CardBody>
            </Card>
          )}

          {counts.total > 0 && (
            <>
            {remediation.qualification_gaps.length > 0 && (
              <RemediationSection
                icon={<AlertOctagon size={15} className="text-danger" />}
                tone="border-danger/30"
                title={`${++step}. What is preventing qualification?`}
                count={remediation.qualification_gaps.length}
                note="Requirements where PRAMAAN found insufficient company capability evidence. Best resolved by adding real capability evidence -- an administrator can also record an audited Pass override if the evidence will be arranged before submission."
              >
                {remediation.qualification_gaps.map((g) => (
                  <GapRow
                    key={g.requirement_id}
                    item={g}
                    missionId={mission.id}
                    canConfirmReadiness={canConfirmReadiness}
                    canOverride={canConfirmReadiness}
                    overriding={overridingId === g.requirement_id}
                    onOverride={(note) => handleOverride(mission.id, g.requirement_id, note)}
                    onRemoveOverride={() => handleRemoveOverride(mission.id, g.requirement_id)}
                  />
                ))}
              </RemediationSection>
            )}

            {bidPrep.length > 0 && (
              <Card className={bidPrepAllConfirmed ? "border-success/30" : "border-warning/30"}>
                <CardHeader
                  title={
                    <span className="flex items-center gap-2">
                      {bidPrepAllConfirmed ? (
                        <CheckCircle2 size={15} className="text-success" />
                      ) : (
                        <AlertTriangle size={15} className="text-warning" />
                      )}
                      {`${++step}. Bid preparation`}
                    </span>
                  }
                  description={
                    bidPrepAllConfirmed
                      ? `✓ All bid-preparation items confirmed — ${bidPrep.length}/${bidPrep.length} completed.`
                      : `${bidPrepUnconfirmed.length} remaining, ${bidPrepConfirmed.length} confirmed, ${bidPrep.length} total — these don't indicate a lack of capability, they're actions or documents required for submission. Confirm an item once it's genuinely prepared.`
                  }
                />

                {/* Unconfirmed sub-group -- shown first, dominates the
                    card visually. Empty when bidPrepAllConfirmed, in which
                    case only the confirmed sub-group below renders.
                    Order: individual gating/procedural items first
                    (matches pre-theming behavior exactly), then the
                    FUTURE_CONTRACTUAL_COMMITMENT themed groups (2+ items),
                    then any FUTURE_CONTRACTUAL_COMMITMENT items that
                    didn't form a group of 2+ (rendered individually per
                    the frozen "no group of 1" rule). */}
                {bidPrepUnconfirmed.length > 0 && (
                  <>
                    {restUnconfirmed.length > 0 && (
                      <CardBody className="!py-2 divide-y divide-border -mx-6">
                        {restUnconfirmed.map(({ item, blocked }) => (
                          <GapRow
                            key={item.requirement_id}
                            item={item}
                            missionId={mission.id}
                            extraBadge={blocked ? "Blocked" : "Action Required"}
                            canConfirmReadiness={canConfirmReadiness}
                            confirming={confirmingId === item.requirement_id}
                            onConfirm={() => handleConfirm(mission.id, item.requirement_id)}
                            onUnconfirm={() => handleUnconfirm(mission.id, item.requirement_id)}
                          />
                        ))}
                      </CardBody>
                    )}

                    {themedGroups.length > 0 && (
                      <div className={cn("space-y-2 px-6 py-3", restUnconfirmed.length > 0 && "border-t border-border")}>
                        {themedGroups.map((group) => (
                          <ThemedGroupCard
                            key={group.theme.key}
                            group={group}
                            canConfirmReadiness={canConfirmReadiness}
                            onConfirmAll={(ids) => handleConfirmGroupItems(mission.id, ids, "confirm")}
                          />
                        ))}
                      </div>
                    )}

                    {commitmentIndividual.length > 0 && (
                      <CardBody
                        className={cn(
                          "!py-2 divide-y divide-border -mx-6",
                          (restUnconfirmed.length > 0 || themedGroups.length > 0) && "border-t border-border"
                        )}
                      >
                        {commitmentIndividual.map((item) => (
                          <GapRow
                            key={item.requirement_id}
                            item={item}
                            missionId={mission.id}
                            extraBadge="Action Required"
                            canConfirmReadiness={canConfirmReadiness}
                            confirming={confirmingId === item.requirement_id}
                            onConfirm={() => handleConfirm(mission.id, item.requirement_id)}
                            onUnconfirm={() => handleUnconfirm(mission.id, item.requirement_id)}
                          />
                        ))}
                      </CardBody>
                    )}
                  </>
                )}

                {/* Confirmed sub-group -- collapsed by default (native
                    <details>, no extra state needed), visually quiet, and
                    listed separately from the unconfirmed group above so a
                    row is never showing both "Confirmed" and its original
                    Blocked/Action Required badge at once. */}
                {bidPrepConfirmed.length > 0 && (
                  <details className={bidPrepUnconfirmed.length > 0 ? "border-t border-border" : undefined}>
                    <summary className="cursor-pointer select-none px-6 py-3 text-xs font-medium text-muted-foreground hover:text-foreground flex items-center gap-1.5">
                      <Check size={13} className="text-success" />
                      {bidPrepConfirmed.length} confirmed item{bidPrepConfirmed.length === 1 ? "" : "s"} (resolved)
                    </summary>
                    <div className="!py-2 divide-y divide-border opacity-70">
                      {bidPrepConfirmed.map(({ item }) => (
                        <GapRow
                          key={item.requirement_id}
                          item={item}
                          missionId={mission.id}
                          muted
                          canConfirmReadiness={canConfirmReadiness}
                          confirming={confirmingId === item.requirement_id}
                          onConfirm={() => handleConfirm(mission.id, item.requirement_id)}
                          onUnconfirm={() => handleUnconfirm(mission.id, item.requirement_id)}
                        />
                      ))}
                    </div>
                  </details>
                )}
              </Card>
            )}

            {/* "Needs Your Review" -- single merged heading over
                coverage_gaps + human_review_items (Action Center V-next),
                each still classified server-side by
                decision_engine.classify_remediation() and never re-derived
                here. Two clearly labeled subsections underneath since
                they mean different things: coverage_gaps is "PRAMAAN can't
                evaluate this domain at all" (get_unsupported_domains());
                human_review_items is "evidence exists but the match
                wasn't confident enough" (REVIEW_REQUIRED/CONDITIONAL
                CAPABILITY_CLAIM results). No action button beyond "Review
                requirement" -- neither bucket has a confirm/create action
                that resolves it the way qualification/bid-prep items do. */}
            {(remediation.coverage_gaps.length > 0 || remediation.human_review_items.length > 0) && (
              <Card className="border-warning/30">
                <CardHeader
                  title={
                    <span className="flex items-center gap-2">
                      <ShieldQuestion size={15} className="text-warning" />
                      {`${++step}. Needs Your Review`}
                    </span>
                  }
                  description={`${remediation.coverage_gaps.length + remediation.human_review_items.length} item${
                    remediation.coverage_gaps.length + remediation.human_review_items.length === 1 ? "" : "s"
                  } need a human look -- not confirmed failures.`}
                />
                {remediation.coverage_gaps.length > 0 && (
                  <div className="px-6 pt-1 pb-2">
                    <p className="text-xs font-semibold text-muted-foreground mb-1">
                      PRAMAAN can't evaluate this domain ({remediation.coverage_gaps.length})
                    </p>
                    <p className="text-xs text-muted-foreground/80 mb-2">
                      No extraction capability exists yet for the relevant domain -- not a confirmed company deficiency.
                    </p>
                  </div>
                )}
                {remediation.coverage_gaps.length > 0 && (
                  <CardBody className="!py-2 divide-y divide-border -mx-6 !pt-0">
                    {remediation.coverage_gaps.map((g) => (
                      <GapRow key={g.requirement_id} item={g} missionId={mission.id} canConfirmReadiness={canConfirmReadiness} />
                    ))}
                  </CardBody>
                )}
                {remediation.human_review_items.length > 0 && (
                  <div className={cn("px-6 pt-3 pb-2", remediation.coverage_gaps.length > 0 && "border-t border-border")}>
                    <p className="text-xs font-semibold text-muted-foreground mb-1">
                      Evidence exists but is ambiguous ({remediation.human_review_items.length})
                    </p>
                    <p className="text-xs text-muted-foreground/80 mb-2">
                      PRAMAAN found relevant capability evidence but couldn't establish a sufficiently clear match.
                    </p>
                  </div>
                )}
                {remediation.human_review_items.length > 0 && (
                  <CardBody className="!py-2 divide-y divide-border -mx-6 !pt-0">
                    {remediation.human_review_items.map((g) => (
                      <GapRow
                        key={g.requirement_id}
                        item={g}
                        missionId={mission.id}
                        canConfirmReadiness={canConfirmReadiness}
                        canOverride={canConfirmReadiness}
                        overriding={overridingId === g.requirement_id}
                        onOverride={(note) => handleOverride(mission.id, g.requirement_id, note)}
                        onRemoveOverride={() => handleRemoveOverride(mission.id, g.requirement_id)}
                      />
                    ))}
                  </CardBody>
                )}
              </Card>
            )}
            </>
          )}

          {/* Review Required -- optional/non-blocking (architecture debate
              Phase 6's optional_capability_gaps: non-mandatory
              CAPABILITY_CLAIM items with a definitive NOT_MET verdict).
              Rendered independently of counts.total/the banner above --
              this section can appear even on an otherwise fully-clear
              tender, which is exactly the case that motivated it: a
              "Review Required" badge with nothing underneath it to explain
              why. Confirmed disjoint from every section above by
              decision_engine.classify_remediation()'s single-pass
              for/elif loop -- never duplicates an item already shown
              elsewhere. Lowest priority in the hierarchy (last position,
              info tone rather than danger/warning) and never phrased as a
              blocker. */}
          {remediation.optional_capability_gaps.length > 0 && (
            <RemediationSection
              icon={<ShieldQuestion size={15} className="text-info" />}
              tone="border-info/30"
              title="Review Required"
              count={remediation.optional_capability_gaps.length}
              note="Non-mandatory capability requirements not currently met -- not a qualification risk, and not counted as outstanding above."
            >
              {remediation.optional_capability_gaps.map((g) => (
                <GapRow key={g.requirement_id} item={g} missionId={mission.id} />
              ))}
            </RemediationSection>
          )}

          {/* Final, visually quiet completed/confirmed summary --
              structure point 3: the page reads as a progression ending
              in a de-emphasized "what's already resolved" area, distinct
              from the unresolved sections above which dominate visually.
              Only rendered when there's something confirmed to show. */}
          {totalConfirmed > 0 && (
            <div className="flex items-center gap-2 px-1 py-2 text-xs text-muted-foreground/80">
              <CheckCircle2 size={13} className="text-success/70 shrink-0" />
              <span>
                {totalConfirmed} bid-preparation item{totalConfirmed === 1 ? "" : "s"} confirmed on this tender.
              </span>
            </div>
          )}
        </div>
      </div>
    );
  }

  // List view -- every evaluated tender, worst-first, scannable in a few
  // seconds: name, status, what's blocking, how many items, next action.
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Action Center</h1>
        <p className="text-sm text-muted-foreground mt-1">Your Path to GO -- move each tender toward bid-ready.</p>
      </div>

      {failedMissionIds.length > 0 && (
        <Card className="border-danger/30">
          <CardBody className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-danger">
              Couldn't load status for {failedMissionIds.length} tender{failedMissionIds.length === 1 ? "" : "s"}.
            </p>
            <Button variant="outline" size="sm" onClick={retryFailed}>
              Retry
            </Button>
          </CardBody>
        </Card>
      )}

      {evaluated.length === 0 && notYetEvaluated.length === 0 ? (
        <Card>
          <CardBody>
            <EmptyState
              icon={Target}
              title="No tenders yet"
              description="Upload a tender to start your first mission."
              action={
                <Link to="/tenders/new" className="text-sm font-medium text-primary hover:underline">
                  Upload a tender →
                </Link>
              }
            />
          </CardBody>
        </Card>
      ) : evaluated.length === 0 ? (
        <Card>
          <CardBody>
            <EmptyState
              icon={FileSearch}
              title="No evaluated tenders yet"
              description="Run an evaluation to see what needs attention."
              action={
                <Link to="/missions" className="text-sm font-medium text-primary hover:underline">
                  Go to Tender Workspace →
                </Link>
              }
            />
          </CardBody>
        </Card>
      ) : allClear ? (
        <Card className="border-success/30">
          <CardBody>
            <EmptyState
              icon={CheckCircle2}
              title="You're all caught up"
              description="No outstanding qualification or bid-preparation actions were found across your evaluated tenders."
              action={
                <Link to="/missions" className="text-sm font-medium text-primary hover:underline">
                  Review tenders →
                </Link>
              }
            />
          </CardBody>
        </Card>
      ) : (
        <div className="space-y-4">
          {sortedEvaluated.map(({ mission, evaluation }) => {
            const counts = remediationCounts(evaluation.remediation_summary);
            const clear = effectivelyClear(evaluation);
            return (
              <Card key={mission.id} className="transition-shadow hover:shadow-elevated">
                <CardBody>
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <p className="font-semibold truncate">{tenderDisplayName(mission)}</p>
                        <Badge value={evaluation.recommendation.recommendation_type} label={recommendationLabel(evaluation.recommendation.recommendation_type)} withIcon />
                      </div>
                      {clear ? (
                        // "Nothing blocking" rather than a bare "Nothing
                        // outstanding" when optional review items exist --
                        // otherwise this line would read as flatly
                        // contradicting a "Review Required" badge sitting
                        // right next to it. The optional items themselves
                        // are still never counted as blockers.
                        <p className="text-sm text-success mt-2">
                          {counts.reviewOptional > 0 ? "Nothing blocking." : "Nothing outstanding."}
                        </p>
                      ) : (
                        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-sm text-muted-foreground">
                          {counts.qualification > 0 && <span>{counts.qualification} qualification gap{counts.qualification === 1 ? "" : "s"}</span>}
                          {counts.bidPrep > 0 && (
                            <span>
                              {(() => {
                                const { unconfirmed, confirmed } = splitBidPrep(bidPrepItems(evaluation));
                                return confirmed.length > 0
                                  ? `${unconfirmed.length} remaining, ${confirmed.length} confirmed, ${counts.bidPrep} total bid action${counts.bidPrep === 1 ? "" : "s"}`
                                  : `${counts.bidPrep} bid action${counts.bidPrep === 1 ? "" : "s"}`;
                              })()}
                            </span>
                          )}
                          {counts.coverage > 0 && <span>{counts.coverage} coverage issue{counts.coverage === 1 ? "" : "s"}</span>}
                          {counts.humanReview > 0 && <span>{counts.humanReview} needing review</span>}
                        </div>
                      )}
                      {counts.reviewOptional > 0 && (
                        <p className="text-xs text-muted-foreground/70 mt-1">
                          {counts.reviewOptional} optional review item{counts.reviewOptional === 1 ? "" : "s"} (non-blocking)
                        </p>
                      )}
                    </div>
                    <Button size="sm" icon={<ArrowRight size={14} />} onClick={() => openMission(mission.id)}>
                      {clear ? "Review" : "Continue fixing"}
                    </Button>
                  </div>
                </CardBody>
              </Card>
            );
          })}
        </div>
      )}

      {notYetEvaluated.length > 0 && (
        <Card>
          <CardHeader
            title="Not yet evaluated"
            description={`${notYetEvaluated.length} tender${notYetEvaluated.length === 1 ? "" : "s"} without a recommendation yet`}
          />
          <CardBody className="!py-2 divide-y divide-border -mx-6">
            {notYetEvaluated.map((m) => (
              <div key={m.id} className="px-6 py-3 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2.5 min-w-0">
                  <Layers size={15} className="text-muted-foreground shrink-0" />
                  <span className="text-sm font-medium truncate">{tenderDisplayName(m)}</span>
                  <Badge value={m.status} withIcon />
                </div>
                <Link to={`/missions/${m.id}`} className="text-sm font-medium text-primary hover:underline inline-flex items-center gap-1 shrink-0">
                  Open <ArrowRight size={13} />
                </Link>
              </div>
            ))}
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function RemediationSection({
  icon,
  tone,
  title,
  count,
  countLabel,
  note,
  children,
}: {
  icon: React.ReactNode;
  tone: string;
  title: string;
  count: number;
  // "4 → 2 unresolved" -- shown instead of the plain item count when some
  // items in this section are confirmed (bid-readiness confirmation
  // feature). Deliberately not a percentage/progress score -- just the
  // raw before/after unresolved count, per the frozen design.
  countLabel?: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <Card className={tone}>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            {icon}
            {title}
          </span>
        }
        description={`${countLabel ?? `${count} item${count === 1 ? "" : "s"}`} — ${note}`}
      />
      <CardBody className="!py-2 divide-y divide-border -mx-6">{children}</CardBody>
    </Card>
  );
}

function GapRow({
  item,
  missionId,
  extraBadge,
  canConfirmReadiness,
  confirming,
  onConfirm,
  onUnconfirm,
  muted,
  canOverride,
  overriding,
  onOverride,
  onRemoveOverride,
}: {
  item: GapAnalysisEntry;
  missionId: string;
  extraBadge?: string;
  // Confirm Prepared is only ever passed down for bid-prep items (see the
  // detail view above) -- undefined for qualification/coverage/review
  // rows, where there's genuinely nothing to confirm.
  canConfirmReadiness?: boolean;
  confirming?: boolean;
  onConfirm?: () => void;
  onUnconfirm?: () => void;
  // True only for rows rendered inside the confirmed sub-group -- applies
  // the quieter, de-emphasized treatment (structure point 3/point 1's
  // "visually quieter sub-section"). A row is never both muted (confirmed
  // group) and showing extraBadge (its original Blocked/Action Required
  // label) -- see below, that's exactly the contradictory state being
  // fixed.
  muted?: boolean;
  // Qualification override ("Pass" / "Not Pass") -- only ever passed down
  // for qualification_gaps and human_review_items rows (the two buckets
  // decision_engine.compute_qualification() actually looks at). Distinct
  // mechanism from Confirm Prepared above: this is a risk acceptance on a
  // CAPABILITY_CLAIM gap, not a readiness confirmation -- see the backend
  // boundary rule docstrings.
  canOverride?: boolean;
  overriding?: boolean;
  onOverride?: (note: string) => void;
  onRemoveOverride?: () => void;
}) {
  // Capability gaps (CAPABILITY_CLAIM-natured items -- qualification_gaps,
  // coverage_gaps, human_review_items, optional_capability_gaps) offer
  // both capability-creation paths: manual entry (no document) and the
  // existing document-build flow. unsupported_domains[0], when present
  // (coverage_gaps), preselects the entity type on both.
  const isCapabilityGap = item.requirement_nature === "capability_claim";
  const suggestedType = item.unsupported_domains[0];
  const suggestedTypeParam = suggestedType ? `suggestedType=${encodeURIComponent(suggestedType)}` : "";
  // Entity-type hint shown ON the button itself, not just implied by the
  // suggestedType query param -- so the CTA reads "Add Equipment
  // Manually" rather than a generic "Add Manually" that leaves the user
  // guessing what kind of record closes the gap. Falls back to a
  // requirement_type-derived guess (CATEGORY_DOMAINS' own base mapping,
  // decision_engine.py) when there's no unsupported_domains hint (true for
  // qualification_gaps, which by definition have zero unsupported
  // domains -- see classify_remediation()'s bucket 1 short-circuit).
  const entityHint =
    suggestedType?.replace(/_/g, " ") ??
    (
      {
        certification: "certification",
        experience: "project",
        eligibility: "certification / financial / project",
        technical: "equipment / employee / project",
      } as Record<string, string>
    )[item.requirement_type] ??
    "capability";
  // Confirmable natures per decision_engine.compute_bid_readiness()'s
  // confirmed_requirement_ids docstring -- never PROCEDURAL.
  const isConfirmable = item.requirement_nature === "submission_gating" || item.requirement_nature === "future_contractual_commitment";
  // Override affordance is only ever offered when the caller passed
  // canOverride down (qualification_gaps + human_review_items rows only --
  // see the two GapRow call sites below). Never offered on coverage_gaps
  // (nothing to accept risk on -- no MatchResult, an unsupported domain)
  // or optional_capability_gaps (non-mandatory, doesn't block qualification
  // regardless).
  const [overrideFormOpen, setOverrideFormOpen] = useState(false);
  const [overrideNote, setOverrideNote] = useState("");
  const canSubmitOverride = overrideNote.trim().length > 0;

  return (
    <div className={cn("px-6 py-3.5", muted && "opacity-80")}>
      <div className="flex items-start justify-between gap-3">
        <p className={cn("text-sm font-medium leading-relaxed", muted && "text-muted-foreground")}>{item.description}</p>
        <div className="flex items-center gap-2 shrink-0">
          {/* A row shows EXACTLY one status indicator: "Confirmed" when
              resolved, "Overridden" when an administrator has accepted the
              risk, or its original Blocked/Action Required badge when
              neither -- never more than one at once. This is the fix for
              the reported bug (a row simultaneously showing "✓ Confirmed"
              and "BLOCKED"). */}
          {item.overridden ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-warning">
              <ShieldCheck size={12} /> Overridden -- Pass
            </span>
          ) : item.confirmed ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-success">
              <Check size={12} /> Confirmed
            </span>
          ) : (
            extraBadge && <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{extraBadge}</span>
          )}
        </div>
      </div>
      <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{forwardLookingGap(item)}</p>

      {/* Permanent, unmistakable disclosure panel -- never silently
          absorbed into "requirement met" language. Stays visible even
          after the item is overridden (transparency requirement); shows
          who made the call, when, and why. */}
      {item.overridden && (
        <div className="mt-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2">
          <p className="text-[11px] font-semibold text-warning flex items-center gap-1">
            <ShieldCheck size={12} /> Administrator override -- no capability evidence exists yet
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            {item.overridden_by_name ?? "An administrator"}
            {item.overridden_at ? ` · ${new Date(item.overridden_at).toLocaleDateString()}` : ""}
          </p>
          {item.override_note && <p className="text-xs text-foreground mt-1 leading-relaxed">"{item.override_note}"</p>}
        </div>
      )}

      {overrideFormOpen && !item.overridden && (
        <div className="mt-2.5 rounded-md border border-border bg-surface-hover px-3 py-2.5">
          <label className="text-xs font-medium text-foreground">Why can this be passed without evidence yet?</label>
          <textarea
            value={overrideNote}
            onChange={(e) => setOverrideNote(e.target.value)}
            placeholder="e.g. Document will be arranged before submission -- required per compliance."
            rows={2}
            className="mt-1.5 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs leading-relaxed focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <div className="flex items-center gap-2 mt-2">
            <Button
              variant="primary"
              size="sm"
              icon={<ShieldCheck size={13} />}
              loading={overriding}
              disabled={!canSubmitOverride}
              onClick={() => {
                onOverride?.(overrideNote.trim());
                setOverrideFormOpen(false);
                setOverrideNote("");
              }}
            >
              Mark Pass
            </Button>
            <Button
              variant="outline"
              size="sm"
              icon={<X size={13} />}
              onClick={() => {
                setOverrideFormOpen(false);
                setOverrideNote("");
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 mt-2.5">
        {isCapabilityGap && (
          <Link
            to={`/capabilities?${["mode=manual", suggestedTypeParam].filter(Boolean).join("&")}`}
            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline capitalize"
          >
            <Sparkles size={12} /> Add {entityHint} capability
          </Link>
        )}
        {isConfirmable && canConfirmReadiness && (item.confirmed ? (
          // Unconfirm -- clearly visible, destructive-styled, but never
          // as prominent as the primary "Confirm Prepared" action below.
          <Button
            variant="outline"
            size="sm"
            className="border-danger/40 text-danger hover:bg-danger-soft"
            loading={confirming}
            onClick={onUnconfirm}
          >
            Unconfirm
          </Button>
        ) : (
          // Confirm Prepared -- the primary action on an unresolved row,
          // styled as such (not a tiny secondary link).
          <Button variant="primary" size="sm" icon={<Check size={13} />} loading={confirming} onClick={onConfirm}>
            Confirm Prepared
          </Button>
        ))}
        {canOverride && (item.overridden ? (
          // Not Pass -- reverses the override, back to whatever the real
          // evidence-based verdict was (NOT_MET/REVIEW_REQUIRED/CONDITIONAL).
          <Button
            variant="outline"
            size="sm"
            className="border-danger/40 text-danger hover:bg-danger-soft"
            loading={overriding}
            onClick={onRemoveOverride}
          >
            Not Pass
          </Button>
        ) : (
          !overrideFormOpen && (
            // Pass -- administrator manually accepts this gap won't block
            // qualification, with a mandatory audited reason (see the form
            // above). Deliberately styled less prominent than Confirm
            // Prepared/Add capability -- a real fix should always be the
            // first thing an administrator reaches for.
            <Button variant="outline" size="sm" icon={<ShieldCheck size={13} />} onClick={() => setOverrideFormOpen(true)}>
              Pass
            </Button>
          )
        ))}
        <Link
          to={`/missions/${missionId}?tab=analysis`}
          className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
        >
          <FileSearch size={12} /> Review requirement
        </Link>
      </div>
    </div>
  );
}

// A collapsible group of 2+ FUTURE_CONTRACTUAL_COMMITMENT items sharing a
// theme (Safety & PPE, Labour & statutory compliance, etc -- see
// lib/actionCenterThemes.ts). Deliberate product/liability safeguard: the
// "Confirm All Prepared" bulk action is gated behind `viewed`, tracked in
// local component state and only ever set true once the user has actually
// expanded the group -- a multi-item legal/safety-compliance group can
// never be blindly bulk-confirmed without the user seeing what's inside
// it first. Confirming = calling the EXISTING per-requirement confirm
// endpoint for every requirement_id in the group via Promise.allSettled
// (see ActionCenter's handleConfirmGroupItems) -- no new bulk-confirm
// backend endpoint. Partial failure is shown inline with a "Retry failed"
// action scoped to just the failed ids.
function ThemedGroupCard({
  group,
  canConfirmReadiness,
  onConfirmAll,
}: {
  group: ThemedGroup;
  canConfirmReadiness?: boolean;
  onConfirmAll: (requirementIds: string[]) => Promise<string[]>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [viewed, setViewed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [failedIds, setFailedIds] = useState<string[]>([]);

  const toggle = () => {
    setExpanded((prev) => {
      const next = !prev;
      if (next) setViewed(true);
      return next;
    });
  };

  const runConfirm = async (ids: string[]) => {
    setConfirming(true);
    try {
      const failed = await onConfirmAll(ids);
      setFailedIds(failed);
    } finally {
      setConfirming(false);
    }
  };

  const allIds = group.items.map((i) => i.requirement_id);

  return (
    <div className="rounded-md border border-border bg-surface-subtle/40">
      <button
        type="button"
        onClick={toggle}
        className="w-full flex items-center justify-between gap-3 px-3.5 py-2.5 text-left"
      >
        <span className="flex items-center gap-2 min-w-0">
          {expanded ? <ChevronDown size={14} className="shrink-0 text-muted-foreground" /> : <ChevronRight size={14} className="shrink-0 text-muted-foreground" />}
          <span className="text-sm font-semibold truncate">{group.theme.label}</span>
          <span className="text-xs font-medium text-muted-foreground shrink-0">{group.items.length} items</span>
        </span>
        {!expanded && <span className="text-[11px] text-muted-foreground shrink-0">Expand to review</span>}
      </button>

      {expanded && (
        <div className="border-t border-border">
          <p className="text-xs text-muted-foreground px-3.5 pt-2.5 pb-1">{group.theme.description}</p>
          <div className="divide-y divide-border">
            {group.items.map((item) => (
              <div key={item.requirement_id} className="px-3.5 py-2.5">
                <p className="text-sm font-medium leading-relaxed">{item.description}</p>
                {item.source_page != null && (
                  <p className="text-xs text-muted-foreground mt-0.5">Source: page {item.source_page}</p>
                )}
                {failedIds.includes(item.requirement_id) && (
                  <p className="text-xs text-danger mt-0.5">Confirmation failed for this item.</p>
                )}
              </div>
            ))}
          </div>

          {canConfirmReadiness && (
            <div className="flex items-center gap-3 px-3.5 py-2.5 border-t border-border">
              {failedIds.length > 0 ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="border-danger/40 text-danger hover:bg-danger-soft"
                  loading={confirming}
                  onClick={() => runConfirm(failedIds)}
                >
                  Retry {failedIds.length} failed item{failedIds.length === 1 ? "" : "s"}
                </Button>
              ) : (
                // Gated behind `viewed` -- only reachable once the group has
                // actually been expanded at least once (see toggle() above).
                // Since this button only renders inside the expanded block,
                // `viewed` is already true by the time it's visible; the
                // check is kept explicit rather than relying on render
                // position alone, in case this block is ever reordered.
                viewed && (
                  <Button variant="primary" size="sm" icon={<Check size={13} />} loading={confirming} onClick={() => runConfirm(allIds)}>
                    Confirm All Prepared ({allIds.length})
                  </Button>
                )
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
