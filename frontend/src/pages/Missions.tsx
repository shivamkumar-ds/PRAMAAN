import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { archiveMission, executeMission, listMissions, purgeMission } from "../api/endpoints";
import { extractErrorMessage } from "../api/client";
import { useToast } from "../context/ToastContext";
import type { MissionRead, MissionStatus } from "../api/types";
import { Badge, Button, Card, CardBody, ConfirmDialog, EmptyState, FilterChip, Input, Menu, MenuItem, Select, SkeletonList } from "../components/kit";
import { cn } from "../lib/cn";
import { tenderDisplayName } from "../lib/tenderName";
import { ArrowRight, CheckCircle2, Clock3, ExternalLink, FileUp, Loader2, MoreVertical, Radar, Search, Sparkles, Trash2, XCircle } from "lucide-react";

// The brief asked for a visual "story" of the tender journey (Upload ->
// Extraction -> Matching -> Compliance -> Gap Analysis -> Decision Engine
// -> Recommendation -> Report -> Completed). The real backend only tracks
// mission status at one granularity: MissionStatus ("created" | "running"
// | "awaiting_approval" | "completed" | "archived") -- there's no field
// anywhere in the contract that records which of those nine sub-steps is
// currently active. Rather than invent progress the backend can't back up,
// this stepper uses the four real states as its stages; "archived" is
// shown as a separate end-state tag rather than a fifth stage, since it's
// a post-completion housekeeping state, not forward progress.
const STAGES: { key: MissionStatus; label: string; icon: typeof FileUp }[] = [
  { key: "created", label: "Uploaded", icon: FileUp },
  { key: "running", label: "AI Processing", icon: Loader2 },
  { key: "awaiting_approval", label: "Awaiting Approval", icon: Clock3 },
  { key: "completed", label: "Completed", icon: CheckCircle2 },
];

function stageIndex(status: MissionStatus): number {
  if (status === "archived") return 3;
  const idx = STAGES.findIndex((s) => s.key === status);
  return idx === -1 ? 0 : idx;
}

function MissionStepper({ status }: { status: MissionStatus }) {
  const current = stageIndex(status);
  const isRunning = status === "running";
  return (
    <div className="flex items-center">
      {STAGES.map((stage, i) => {
        const reached = i <= current;
        const isCurrent = i === current && !(status === "completed" || status === "archived");
        return (
          <div key={stage.key} className="flex items-center">
            <div className="flex flex-col items-center gap-1.5 w-20">
              <div
                className={cn(
                  "w-7 h-7 rounded-full flex items-center justify-center border-2 transition-colors",
                  reached
                    ? "bg-primary border-primary text-primary-foreground"
                    : "bg-surface border-border text-muted-foreground"
                )}
              >
                <stage.icon size={13} className={isCurrent && isRunning ? "animate-spin" : undefined} />
              </div>
              <span className={cn("text-[10px] text-center leading-tight", reached ? "text-foreground font-medium" : "text-muted-foreground")}>
                {stage.label}
              </span>
            </div>
            {i < STAGES.length - 1 && (
              <div className={cn("h-0.5 w-6 sm:w-10 -mt-4", i < current ? "bg-primary" : "bg-border")} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// Honest rotating status line for a mission currently mid-execute -- same
// posture as the kit AIProcessing component (real LLM call, no fake
// progress %), just compact enough to sit under the stepper on a list card
// instead of taking over the whole page.
const RUNNING_MESSAGES = [
  "Running AI analysis…",
  "Reading tender requirements…",
  "Matching against your capabilities…",
  "Still working — this can take a little while…",
];

function RunningIndicator() {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => {
      setIndex((i) => (i < RUNNING_MESSAGES.length - 1 ? i + 1 : i));
    }, 2200);
    return () => clearInterval(interval);
  }, []);
  return (
    <div className="mt-4 pt-4 border-t border-border flex items-center gap-2 text-xs text-muted-foreground">
      <Sparkles size={13} className="text-primary animate-pulse shrink-0" />
      <span>{RUNNING_MESSAGES[index]}</span>
    </div>
  );
}

export default function Missions() {
  const [missions, setMissions] = useState<MissionRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningId, setRunningId] = useState<string | null>(null);
  // Only "openai" is wired up server-side right now (see
  // ExecuteMissionRequest) -- Gemini/Qwen aren't verified/usable in this
  // deployment yet, so the selector only offers the one real option
  // rather than listing choices that would fail.
  const [provider, setProvider] = useState<"openai">("openai");
  const [archivingId, setArchivingId] = useState<string | null>(null);
  // The tender pending a delete confirmation -- null means the confirm
  // dialog is closed. Replaces the old window.confirm() (unstyled, blocks
  // the tab, can't show a "request in progress" state on its own button).
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null);
  // Separate from pendingDelete/archivingId above -- this is the real,
  // irreversible purge_mission() call, only ever offered for a row that's
  // already archived. Kept as its own state (not a flag reused on
  // pendingDelete) so the two very different confirm dialogs -- "hide it,
  // recoverable" vs "destroy it, forever" -- can never be conflated.
  const [pendingPurge, setPendingPurge] = useState<{ id: string; name: string } | null>(null);
  const [purgingId, setPurgingId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<MissionStatus | "all">("all");
  const [sortBy, setSortBy] = useState<"newest" | "oldest" | "name">("newest");
  const { notify } = useToast();
  const navigate = useNavigate();

  const refresh = async () => {
    try {
      // Reports.tsx (a separate, duplicate browse view over this same
      // list_missions() call) has been retired -- Tender Workspace is now
      // the single place all missions live, including archived ones, which
      // were previously invisible everywhere in the app once "deleted."
      // Full list is kept in state; archived rows are excluded from the
      // default view (not the fetch) via visibleMissions below, so
      // selecting the "Archived" filter can reveal them without a second
      // fetch or a backend status filter (list_missions() has none).
      setMissions(await listMissions());
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // listMissions() returns newest-first (see mission_service.list_missions,
  // ordered by created_at.desc()) -- the upload order number shown to the
  // user should read 1, 2, 3... in the order tenders were actually uploaded,
  // so it's derived here rather than relying on array position directly.
  const total = missions.length;
  // Order numbers reflect real upload order (index in the newest-first
  // fetch), independent of the current filter/sort applied for display.
  const orderById = new Map(missions.map((m, i) => [m.id, total - i]));

  // Search + status filter + sort are purely client-side over the already-
  // fetched list -- no new backend query params needed since
  // list_missions() already returns everything this page uses. "All"
  // means "everything actively in play" and still excludes archived, same
  // default behavior as before this consolidation -- archived rows only
  // appear when a user deliberately selects the "Archived" filter.
  const visibleMissions = missions
    .filter((m) => (statusFilter === "all" ? m.status !== "archived" : m.status === statusFilter))
    .filter((m) => tenderDisplayName(m).toLowerCase().includes(search.trim().toLowerCase()))
    .slice()
    .sort((a, b) => {
      if (sortBy === "name") return tenderDisplayName(a).localeCompare(tenderDisplayName(b));
      const diff = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      return sortBy === "oldest" ? diff : -diff;
    });

  const handleRunFullAnalysis = async (missionId: string) => {
    setRunningId(missionId);
    try {
      await executeMission(missionId, provider);
      notify("success", "Full analysis complete — recommendation generated.");
      // Land on Action Center's "Path to GO" detail view for this mission,
      // not the raw Evaluation Matrix -- Action Center is now the primary
      // post-analysis surface (precise, typed, actionable gaps). The
      // Evaluation Matrix stays fully reachable from there via "Open in
      // Tender Workspace" / existing nav tabs; this only changes where a
      // freshly-completed analysis defaults to landing.
      navigate(`/action-center?mission=${missionId}`);
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setRunningId(null);
    }
  };

  const handleConfirmDelete = async () => {
    if (!pendingDelete) return;
    const { id: missionId, name } = pendingDelete;
    setArchivingId(missionId);
    try {
      await archiveMission(missionId);
      notify("success", `"${name}" deleted.`);
      setPendingDelete(null);
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setArchivingId(null);
    }
  };

  const handleConfirmPurge = async () => {
    if (!pendingPurge) return;
    const { id: missionId, name } = pendingPurge;
    setPurgingId(missionId);
    try {
      await purgeMission(missionId);
      notify("success", `"${name}" permanently deleted.`);
      setPendingPurge(null);
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setPurgingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Tender Workspace</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Every tender's journey from upload to Tender Assessment.
        </p>
      </div>

      {!loading && missions.length > 0 && (
        <Card>
          <CardBody className="flex flex-wrap items-center gap-3 py-3">
            <div className="relative flex-1 min-w-[200px]">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search tenders…"
                className="pl-8"
                aria-label="Search tenders"
              />
            </div>
            <div className="w-44">
              <Select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as MissionStatus | "all")}
                aria-label="Filter by status"
              >
                <option value="all">Status: All</option>
                <option value="created">Status: Uploaded</option>
                <option value="running">Status: AI Processing</option>
                <option value="awaiting_approval">Status: Awaiting Approval</option>
                <option value="completed">Status: Completed</option>
                <option value="archived">Status: Archived</option>
              </Select>
            </div>
            <div className="w-44">
              <Select value={sortBy} onChange={(e) => setSortBy(e.target.value as "newest" | "oldest" | "name")} aria-label="Sort by">
                <option value="newest">Sort: Newest first</option>
                <option value="oldest">Sort: Oldest first</option>
                <option value="name">Sort: Name (A-Z)</option>
              </Select>
            </div>
            {/* Direct, one-click access to deleted/archived tenders --
                the Status dropdown above already includes "Archived" as
                an option, but it's easy to miss buried in a select. This
                chip toggles the same statusFilter state, so it's just a
                second, more visible entry point onto the exact same
                filter, not a parallel view. */}
            <FilterChip
              label="Archived"
              active={statusFilter === "archived"}
              onClick={() => setStatusFilter((prev) => (prev === "archived" ? "all" : "archived"))}
            />
          </CardBody>
        </Card>
      )}

      {loading ? (
        <Card>
          <CardBody>
            <SkeletonList rows={4} />
          </CardBody>
        </Card>
      ) : missions.length === 0 ? (
        <Card>
          <CardBody>
            <EmptyState
              icon={Radar}
              title="No missions yet"
              description="Upload a tender to start your first mission."
              action={
                <Link to="/tenders/new" className="text-sm font-medium text-primary hover:underline">
                  Upload a tender →
                </Link>
              }
            />
          </CardBody>
        </Card>
      ) : visibleMissions.length === 0 ? (
        <Card>
          <CardBody>
            <EmptyState
              icon={Search}
              title="No tenders match"
              description="Try a different search term or status filter."
            />
          </CardBody>
        </Card>
      ) : (
        <div className="space-y-4">
          {visibleMissions.map((m) => {
            const order = orderById.get(m.id) ?? 0;
            return (
              <Card key={m.id} className="transition-shadow hover:shadow-elevated">
                <CardBody>
                  <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
                    <div className="flex items-start gap-3 min-w-0">
                      <div className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center text-sm font-semibold shrink-0">
                        {order}
                      </div>
                      <div className="min-w-0">
                        <p className="font-semibold truncate">{tenderDisplayName(m)}</p>
                        <p className="text-xs text-muted-foreground tabular-nums mt-0.5">
                          Started {new Date(m.created_at).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge value={m.status} withIcon />
                      <Link
                        to={`/missions/${m.id}`}
                        className="inline-flex items-center gap-1 text-sm text-primary font-medium hover:underline"
                      >
                        Open <ArrowRight size={13} />
                      </Link>
                      <Menu
                        label={`More actions for ${tenderDisplayName(m)}`}
                        trigger={
                          <span className="w-7 h-7 rounded-md flex items-center justify-center text-muted-foreground hover:bg-surface-hover transition-colors">
                            <MoreVertical size={15} />
                          </span>
                        }
                      >
                        <MenuItem icon={<ExternalLink size={14} />} onClick={() => navigate(`/missions/${m.id}`)}>
                          Open
                        </MenuItem>
                        {/* Active rows get the recoverable "hide it"
                            action; already-archived rows get the real,
                            irreversible purge_mission() call instead --
                            re-archiving an already-archived row isn't a
                            thing the backend supports, so these two menu
                            items are mutually exclusive per row. */}
                        {m.status !== "archived" ? (
                          <MenuItem
                            icon={<Trash2 size={14} />}
                            danger
                            onClick={() => setPendingDelete({ id: m.id, name: tenderDisplayName(m) })}
                          >
                            {archivingId === m.id ? "Deleting…" : "Delete"}
                          </MenuItem>
                        ) : (
                          <MenuItem
                            icon={<XCircle size={14} />}
                            danger
                            onClick={() => setPendingPurge({ id: m.id, name: tenderDisplayName(m) })}
                          >
                            {purgingId === m.id ? "Deleting…" : "Delete Permanently"}
                          </MenuItem>
                        )}
                      </Menu>
                    </div>
                  </div>
                  <div className="overflow-x-auto pb-1">
                    <MissionStepper status={m.status} />
                  </div>
                  {m.status === "running" && <RunningIndicator />}
                  {m.status === "created" && (
                    <div className="mt-5 pt-4 border-t border-border flex items-center justify-end gap-2.5">
                      <span className="text-xs text-muted-foreground">AI Engine</span>
                      <div className="w-40">
                        <Select
                          value={provider}
                          onChange={(e) => setProvider(e.target.value as "openai")}
                          className="py-1.5 text-xs"
                          aria-label="AI engine for this analysis"
                        >
                          <option value="openai">OpenAI (GPT)</option>
                        </Select>
                      </div>
                      <Button
                        size="sm"
                        loading={runningId === m.id}
                        disabled={runningId !== null}
                        onClick={() => handleRunFullAnalysis(m.id)}
                      >
                        Run Full Analysis
                      </Button>
                    </div>
                  )}
                </CardBody>
              </Card>
            );
          })}
        </div>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete tender?"
        description={
          pendingDelete && (
            <>
              Are you sure you want to delete <strong className="text-foreground">"{pendingDelete.name}"</strong>?
              <br />
              <br />
              The tender will be hidden from the default Tender Workspace view and Dashboard. You can find it
              later under the Archived filter here.
            </>
          )
        }
        confirmLabel="Delete Tender"
        loading={archivingId === pendingDelete?.id}
        onConfirm={handleConfirmDelete}
        onCancel={() => setPendingDelete(null)}
      />

      <ConfirmDialog
        open={pendingPurge !== null}
        title="Permanently delete tender?"
        description={
          pendingPurge && (
            <>
              Are you sure you want to permanently delete{" "}
              <strong className="text-foreground">"{pendingPurge.name}"</strong>?
              <br />
              <br />
              This removes the tender, its requirements, documents, and evaluation history for good.{" "}
              <strong className="text-foreground">This cannot be undone.</strong>
            </>
          )
        }
        confirmLabel="Delete Permanently"
        loading={purgingId === pendingPurge?.id}
        onConfirm={handleConfirmPurge}
        onCancel={() => setPendingPurge(null)}
      />
    </div>
  );
}
