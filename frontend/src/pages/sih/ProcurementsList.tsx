import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, FileText, Plus, ShieldCheck, Users } from "lucide-react";
import { createProcurement, listProcurements, listSubmissionsForProcurement } from "../../api/endpoints";
import { extractErrorMessage } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type { ProcurementRead } from "../../api/types";
import { Badge, Button, Card, CardBody, EmptyState, Input, Modal, SkeletonList } from "../../components/kit";

/**
 * SIH26100 -- Procurement Verification landing page. Deliberately kept
 * lean per the Phase 3 brief ("Do not overload this page with raw
 * verification details") -- bidder-level score/risk rollups only appear
 * one level down, on ProcurementSubmissions, where the fan-out is bounded
 * to one procurement's bidders instead of every procurement's every
 * bidder.
 */
export default function ProcurementsList() {
  const [procurements, setProcurements] = useState<ProcurementRead[]>([]);
  const [submissionCounts, setSubmissionCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [organization, setOrganization] = useState("");
  const [referenceNumber, setReferenceNumber] = useState("");
  const [category, setCategory] = useState("");
  const { user } = useAuth();
  const { notify } = useToast();
  const canCreate = user?.role === "administrator";

  const refresh = async () => {
    try {
      const list = await listProcurements();
      setProcurements(list);
      // Bounded fan-out: one listSubmissionsForProcurement call per
      // procurement, purely to show a real bidder count -- no per-bidder
      // score/risk is fetched here (that only happens one screen down).
      const counts = await Promise.all(
        list.map(async (p) => {
          try {
            const submissions = await listSubmissionsForProcurement(p.id);
            return [p.id, submissions.length] as const;
          } catch {
            return [p.id, 0] as const;
          }
        })
      );
      setSubmissionCounts(Object.fromEntries(counts));
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

  const resetForm = () => {
    setTitle("");
    setOrganization("");
    setReferenceNumber("");
    setCategory("");
  };

  const handleCreate = async () => {
    if (!title.trim()) return;
    setCreating(true);
    try {
      await createProcurement({
        title: title.trim(),
        organization: organization.trim() || null,
        reference_number: referenceNumber.trim() || null,
        category: category.trim() || null,
      });
      notify("success", "Procurement created.");
      setCreateOpen(false);
      resetForm();
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Procurement Verification</h1>
          <p className="text-sm text-muted-foreground mt-1">
            GeM procurements and their bidder compliance verification against government registries.
          </p>
        </div>
        {canCreate && (
          <Button icon={<Plus size={15} />} onClick={() => setCreateOpen(true)}>
            New Procurement
          </Button>
        )}
      </div>

      {loading ? (
        <Card>
          <CardBody>
            <SkeletonList rows={4} />
          </CardBody>
        </Card>
      ) : procurements.length === 0 ? (
        <Card>
          <CardBody>
            <EmptyState
              icon={ShieldCheck}
              title="No procurements yet"
              description="Create a procurement to start verifying bidder submissions against government registries."
              action={
                canCreate ? (
                  <button
                    onClick={() => setCreateOpen(true)}
                    className="text-sm font-medium text-primary hover:underline"
                  >
                    Create a procurement →
                  </button>
                ) : undefined
              }
            />
          </CardBody>
        </Card>
      ) : (
        <div className="space-y-3">
          {procurements.map((p) => (
            <Card key={p.id} className="transition-shadow hover:shadow-elevated">
              <CardBody className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="w-9 h-9 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
                    <FileText size={16} />
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold truncate">{p.title}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {[p.reference_number, p.organization].filter(Boolean).join(" · ") || "No reference / organization on file"}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-4 shrink-0">
                  <div className="hidden sm:flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Users size={13} />
                    {submissionCounts[p.id] ?? 0} bidder{(submissionCounts[p.id] ?? 0) === 1 ? "" : "s"}
                  </div>
                  <Badge value={p.status} />
                  <Link
                    to={`/procurement-verification/${p.id}`}
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
        open={createOpen}
        title="New Procurement"
        description="Create a GeM procurement to begin verifying bidder submissions against it."
        onClose={() => !creating && setCreateOpen(false)}
        footer={
          <>
            <Button variant="outline" size="sm" onClick={() => setCreateOpen(false)} disabled={creating}>
              Cancel
            </Button>
            <Button size="sm" loading={creating} disabled={!title.trim()} onClick={handleCreate}>
              Create Procurement
            </Button>
          </>
        }
      >
        <div className="space-y-3.5">
          <Input label="Title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="CPCL Pipeline Maintenance Tender" autoFocus />
          <Input label="Organization" value={organization} onChange={(e) => setOrganization(e.target.value)} placeholder="CPCL" />
          <Input label="Reference number" value={referenceNumber} onChange={(e) => setReferenceNumber(e.target.value)} placeholder="GEM/2026/B/..." />
          <Input label="Category" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Works / Services / Goods" />
        </div>
      </Modal>
    </div>
  );
}
