import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  buildCapability,
  createCapabilityManual,
  deleteCapability,
  getCapabilityGraph,
  listDocuments,
  updateCapability,
} from "../api/endpoints";
import { extractErrorMessage } from "../api/client";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";
import type { CapabilityEntityType, CapabilityGraphResponse, DocumentRead } from "../api/types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Input,
  Select,
  SkeletonList,
  StatCard,
} from "../components/kit";
import { AIProcessing } from "../components/kit";
import { Award, Users, Briefcase, Wrench, Landmark, Layers, Pencil, PenLine, Trash2, type LucideIcon } from "lucide-react";

const ENTITY_TYPES: CapabilityEntityType[] = ["certification", "employee", "project", "equipment", "financial_record"];

// POST /capabilities/build (document extraction) only has an LLM agent for
// these three types -- mirrors the backend's READ_SCHEMAS/ENTITY_MODELS in
// app/api/v1/capabilities.py and capability_service.py exactly (both
// comment that Equipment/FinancialRecord were never given an extraction
// agent, only a manual-creation path). Offering a "Build Capabilities"
// button for a document mapped to equipment/financial_record would just
// 422 with "'financial_record' is not supported by the Capability Builder
// in M3." -- a real bug this list exists specifically to prevent.
const BUILDABLE_ENTITY_TYPES: CapabilityEntityType[] = ["certification", "employee", "project"];

const BUILD_STAGES = ["Reading document…", "Extracting structured entities…", "Validating confidence…", "Saving to capability library…"];

// Documents.tsx's upload form already asks the user to classify the
// document (its DOCUMENT_TYPES list) at upload time -- that choice is
// real and persisted server-side (Document.document_type). Previously
// this page ignored it entirely and re-asked via an editable dropdown
// defaulting to "certification" every time, which is exactly the bug a
// real user hit (uploaded as "financial_record", Capabilities page still
// showed "certification" pre-selected). The two vocabularies aren't
// identical strings (Documents.tsx uses "employee_resume"/"project_record"/
// "equipment_record", this page's CapabilityEntityType uses "employee"/
// "project"/"equipment"), so this maps between them. Per the intended
// model, the type is fixed at upload time -- to change it, delete the
// document and re-upload with the correct type (same as source_document_id
// being immutable everywhere else in this pipeline); there is
// deliberately no editable selector here any more.
const DOCUMENT_TYPE_TO_ENTITY_TYPE: Record<string, CapabilityEntityType | undefined> = {
  certification: "certification",
  employee_resume: "employee",
  project_record: "project",
  equipment_record: "equipment",
  financial_record: "financial_record",
};

// Manual capability creation (no document required) -- fields per entity
// type match the actual model columns (backend
// capability_service.MANUAL_CREATE_FIELDS/MANUAL_REQUIRED_FIELDS is the
// real source of truth; this list mirrors it for the form only). `kind`
// drives which input renders; "array" fields are entered as a
// comma-separated string and split on submit. "fiscal_year" is its own
// kind (not "number") specifically because Indian tenders' real-world
// convention is "2024-25", not a plain year -- a type="number" input
// rejects the hyphen outright (browser shows "Please enter a number" and
// silently keeps the field empty), which is exactly the bug a real user
// hit here. financial_year renders as text and gets parsed leniently --
// see parseFiscalYear below.
type ManualFieldKind = "text" | "date" | "number" | "array" | "fiscal_year";
interface ManualFieldSpec {
  name: string;
  label: string;
  kind: ManualFieldKind;
  required?: boolean;
}

// Accepts the range notation users actually type ("2024-25", "2024-2025",
// "FY 2024-25") as well as a plain year ("2025") and always resolves to a
// single ending year -- the backend model only stores one int
// (financial_year), representing the year a year-specific requirement
// like "years ending 31.03.2026" is checked against (see
// capability_service.py's MANUAL_REQUIRED_FIELDS comment). Returns null
// for genuinely unparseable input so the caller can surface a real error
// instead of silently saving garbage.
function parseFiscalYear(raw: string): number | null {
  const trimmed = raw.trim();
  const rangeMatch = trimmed.match(/(\d{4})\s*[-/]\s*(\d{2,4})/);
  if (rangeMatch) {
    const startYear = parseInt(rangeMatch[1], 10);
    const endPart = rangeMatch[2];
    let endYear: number;
    if (endPart.length === 2) {
      const century = Math.floor(startYear / 100) * 100;
      endYear = century + parseInt(endPart, 10);
      if (endYear < startYear) endYear += 100; // e.g. "1999-00" -> 2000
    } else {
      endYear = parseInt(endPart, 10);
    }
    return endYear;
  }
  const singleMatch = trimmed.match(/(\d{4})/);
  return singleMatch ? parseInt(singleMatch[1], 10) : null;
}

// Shared by both the manual-creation form and the inline edit form so the
// two never drift -- turns the raw string values keyed by field name into
// the typed payload build_capability_manual()/update_capability_fields()
// expect, or a single human-readable error if a value can't be parsed.
function buildFieldsFromSpecs(
  specs: ManualFieldSpec[],
  values: Record<string, string>
): { fields: Record<string, unknown> } | { error: string } {
  const fields: Record<string, unknown> = {};
  for (const spec of specs) {
    const raw = values[spec.name];
    if (raw === undefined || raw.trim() === "") continue;
    if (spec.kind === "array") {
      fields[spec.name] = raw.split(",").map((v) => v.trim()).filter(Boolean);
    } else if (spec.kind === "number") {
      const n = Number(raw);
      if (!Number.isNaN(n)) fields[spec.name] = n;
    } else if (spec.kind === "fiscal_year") {
      const year = parseFiscalYear(raw);
      if (year === null) {
        return { error: `${spec.label}: couldn't understand "${raw}" -- try a year like 2025 or a range like 2024-25.` };
      }
      fields[spec.name] = year;
    } else {
      fields[spec.name] = raw;
    }
  }
  return { fields };
}

const MANUAL_FIELDS: Record<CapabilityEntityType, ManualFieldSpec[]> = {
  certification: [
    { name: "certification_name", label: "Certification name", kind: "text", required: true },
    { name: "issuing_authority", label: "Issuing authority", kind: "text" },
    { name: "issue_date", label: "Issue date", kind: "date" },
    { name: "expiry_date", label: "Expiry date", kind: "date" },
    { name: "status", label: "Status", kind: "text" },
  ],
  employee: [
    { name: "name", label: "Name", kind: "text", required: true },
    { name: "position", label: "Position", kind: "text" },
    { name: "qualification", label: "Qualification", kind: "text" },
    { name: "experience", label: "Experience", kind: "text" },
    { name: "availability", label: "Availability", kind: "text" },
    { name: "skills", label: "Skills (comma-separated)", kind: "array" },
  ],
  project: [
    { name: "client", label: "Client", kind: "text" },
    { name: "industry", label: "Industry", kind: "text" },
    { name: "contract_value", label: "Contract value", kind: "number" },
    { name: "duration", label: "Duration", kind: "text" },
    { name: "completion_status", label: "Completion status", kind: "text" },
    { name: "similarity_tags", label: "Similarity tags (comma-separated)", kind: "array" },
  ],
  equipment: [
    { name: "equipment_name", label: "Equipment name", kind: "text", required: true },
    { name: "category", label: "Category", kind: "text" },
    { name: "quantity", label: "Quantity", kind: "number" },
    { name: "availability", label: "Availability", kind: "text" },
    { name: "specifications", label: "Specifications", kind: "text" },
  ],
  financial_record: [
    { name: "financial_year", label: "Financial year (e.g. 2025 or 2024-25)", kind: "fiscal_year", required: true },
    { name: "revenue", label: "Revenue", kind: "number" },
    { name: "net_worth", label: "Net worth", kind: "number" },
    { name: "working_capital", label: "Working capital", kind: "number" },
    { name: "credit_rating", label: "Credit rating", kind: "text" },
  ],
};

export default function Capabilities() {
  // Action Center's "Add capability" link on a qualification/coverage gap
  // carries the gap's unsupported_domains[0] (e.g. "equipment") as
  // ?suggestedType= -- a frontend-only default, not a new capability
  // creation workflow. Only ever pre-selects the entity-type dropdown for
  // documents that don't already have an explicit selection; the user can
  // still change it before building, and documents already built are
  // unaffected.
  const [searchParams] = useSearchParams();
  const suggestedTypeParam = searchParams.get("suggestedType");
  const suggestedType: CapabilityEntityType | null =
    suggestedTypeParam && (ENTITY_TYPES as string[]).includes(suggestedTypeParam)
      ? (suggestedTypeParam as CapabilityEntityType)
      : null;
  // Action Center's "Add Capability" link on a gap can route here with
  // ?mode=manual (opening the manual-add form directly, entity type
  // preselected via the same suggestedType param) instead of the
  // document-build flow -- both paths are offered from the same gap link.
  const openManualOnLoad = searchParams.get("mode") === "manual";

  const [documents, setDocuments] = useState<DocumentRead[]>([]);
  const [graph, setGraph] = useState<CapabilityGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [manualFormOpen, setManualFormOpen] = useState(openManualOnLoad);
  const [manualEntityType, setManualEntityType] = useState<CapabilityEntityType>(suggestedType ?? ENTITY_TYPES[0]);
  const [manualValues, setManualValues] = useState<Record<string, string>>({});
  const [manualSubmitting, setManualSubmitting] = useState(false);
  // Inline edit (PATCH /capabilities/{id}) -- previously only wired for
  // Certification/Employee/Project (the original M9 rollout); Equipment and
  // FinancialRecord had a real gap here: a record created with a blank
  // required-looking field (e.g. financial_year, before it became a
  // required manual-creation field) had no way to be corrected in place,
  // only delete-and-recreate. The backend PATCH endpoint and
  // PATCHABLE_FIELDS were already generic across all five types once
  // extended -- this closes the equivalent frontend gap for all five at
  // once rather than special-casing just FinancialRecord.
  const [editing, setEditing] = useState<{ id: string; entityType: CapabilityEntityType } | null>(null);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [editSubmitting, setEditSubmitting] = useState(false);
  const { notify } = useToast();
  const { user } = useAuth();
  // DELETE /capabilities/{id}, PATCH /capabilities/{id}, and POST
  // /capabilities/manual are all admin-only server-side
  // (require_administrator) -- hiding the actions for non-admins avoids a
  // confusing 403 on click, it's not a real access-control boundary (the
  // backend still enforces it).
  const canDeleteCapabilities = user?.role === "administrator";
  const canEditCapabilities = user?.role === "administrator";
  const canCreateManually = user?.role === "administrator";

  // One document, one-time capability: a document that already has a live
  // (non-removed) capability entity built from it, regardless of type,
  // can't be built again until that entity is deleted (backend enforces
  // this with a 409; this Set drives the matching UI state so the Build
  // button doesn't even offer an action that will just fail).
  const builtDocumentIds = useMemo(() => {
    if (!graph) return new Set<string>();
    const allEntities = [
      ...graph.certifications,
      ...graph.employees,
      ...graph.projects,
      ...graph.equipment,
      ...graph.financial_records,
    ];
    return new Set(allEntities.filter((e) => e.source_document_id).map((e) => e.source_document_id as string));
  }, [graph]);

  // Real preview text per document -- one document produces exactly one
  // capability entity (the "one document, one-time" rule above), so this
  // isn't pulling multiple separate records; it's the entity's own real
  // multi-value fields (an employee's skills, a project's similarity
  // tags) plus its name/label, so a document with only a single-value
  // entity (certification/equipment/financial record) honestly shows
  // just the one line rather than inventing extra items.
  const previewsByDocument = useMemo(() => {
    const map = new Map<string, string[]>();
    if (!graph) return map;
    const add = (docId: string | null, items: (string | null | undefined)[]) => {
      if (!docId) return;
      map.set(docId, items.filter((v): v is string => Boolean(v && v.trim())));
    };
    graph.certifications.forEach((c) => add(c.source_document_id, [c.certification_name, c.issuing_authority]));
    graph.employees.forEach((e) => add(e.source_document_id, [e.name, ...(e.skills ?? [])]));
    graph.projects.forEach((p) => add(p.source_document_id, [p.client ?? "Unnamed client", ...(p.similarity_tags ?? [])]));
    graph.equipment.forEach((eq) => add(eq.source_document_id, [eq.equipment_name]));
    graph.financial_records.forEach((f) => add(f.source_document_id, [f.financial_year ? `FY ${f.financial_year}` : null]));
    return map;
  }, [graph]);

  const refresh = async () => {
    setLoading(true);
    try {
      const [docs, capGraph] = await Promise.all([listDocuments(), getCapabilityGraph()]);
      // Capability Library only builds from company documents (certifications,
      // resumes, project/equipment/financial records) -- tender documents go
      // through a separate upload flow (document_type "tender", set only by
      // TenderUpload.tsx/tender_service.upload_tender) and were never meant
      // to be extractable as capability evidence. listDocuments() returns
      // every company document with no type filter, so this page has to
      // exclude tenders itself.
      setDocuments(docs.filter((d) => d.document_type !== "tender"));
      setGraph(capGraph);
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

  const handleBuild = async (documentId: string, entityType: CapabilityEntityType, fileName: string) => {
    setBuilding(documentId);
    try {
      await buildCapability(documentId, entityType);
      notify("success", `Capabilities extracted from ${fileName}.`);
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setBuilding(null);
    }
  };

  const handleRemoveCapability = async (entityId: string, label: string) => {
    if (!confirm(`Delete "${label}" from the capability library? Any mission currently citing it as evidence will be re-evaluated.`)) {
      return;
    }
    setRemovingId(entityId);
    try {
      await deleteCapability(entityId);
      notify("success", `"${label}" removed.`);
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setRemovingId(null);
    }
  };

  // Converts an entity's current field value into the string an <Input>
  // needs -- mirrors the reverse of handleManualSubmit's own parsing so a
  // value round-trips unchanged if the user saves without editing it.
  const fieldToInputValue = (spec: ManualFieldSpec, entity: Record<string, unknown>): string => {
    const raw = entity[spec.name];
    if (raw === null || raw === undefined) return "";
    if (spec.kind === "array" && Array.isArray(raw)) return raw.join(", ");
    return String(raw);
  };

  const startEdit = (entityType: CapabilityEntityType, entity: { id: string }) => {
    const specs = MANUAL_FIELDS[entityType];
    // Entities coming from CapabilityGraphResponse are typed as specific
    // interfaces (CertificationEntry, EquipmentEntry, ...) without an index
    // signature -- this is a read-only, field-by-name lookup over the same
    // object, so a cast is the right tool here rather than widening every
    // entry type in api/types.ts just to satisfy this one helper.
    const asRecord = entity as unknown as Record<string, unknown>;
    const values: Record<string, string> = {};
    specs.forEach((spec) => {
      values[spec.name] = fieldToInputValue(spec, asRecord);
    });
    setEditValues(values);
    setEditing({ id: entity.id, entityType });
  };

  const cancelEdit = () => {
    setEditing(null);
    setEditValues({});
  };

  const handleEditSubmit = async () => {
    if (!editing) return;
    const specs = MANUAL_FIELDS[editing.entityType];
    // Same required-field check as manual creation -- editing a record down
    // to a blank required field (e.g. clearing certification_name) isn't
    // allowed here any more than it is at creation time.
    const missing = specs.filter((f) => f.required && !editValues[f.name]?.trim());
    if (missing.length > 0) {
      notify("error", `${missing.map((f) => f.label).join(", ")} required.`);
      return;
    }

    const result = buildFieldsFromSpecs(specs, editValues);
    if ("error" in result) {
      notify("error", result.error);
      return;
    }

    setEditSubmitting(true);
    try {
      await updateCapability(editing.id, result.fields);
      notify("success", "Capability updated.");
      cancelEdit();
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setEditSubmitting(false);
    }
  };

  const manualFieldSpecs = MANUAL_FIELDS[manualEntityType];

  const handleManualSubmit = async () => {
    // Client-side required-field check mirrors the backend's
    // MANUAL_REQUIRED_FIELDS exactly (certification_name/name/equipment_name)
    // -- a fast, honest pre-check; the server still validates and remains
    // the real source of truth (422 on a genuine gap in this list).
    const missing = manualFieldSpecs.filter((f) => f.required && !manualValues[f.name]?.trim());
    if (missing.length > 0) {
      notify("error", `${missing.map((f) => f.label).join(", ")} required.`);
      return;
    }

    const result = buildFieldsFromSpecs(manualFieldSpecs, manualValues);
    if ("error" in result) {
      notify("error", result.error);
      return;
    }

    setManualSubmitting(true);
    try {
      await createCapabilityManual({ entity_type: manualEntityType, fields: result.fields });
      notify("success", "Capability added.");
      setManualValues({});
      setManualFormOpen(false);
      await refresh();
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setManualSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Capability Library</h1>
        <p className="text-sm text-muted-foreground mt-1">
          AI-extracted certifications, personnel, projects, equipment, and financials.
        </p>
      </div>

      {loading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="bg-surface border border-border rounded-lg p-5 h-24" />
          ))}
        </div>
      ) : graph ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="Total" value={graph.summary.total_entities} icon={<Layers size={16} />} tone="primary" />
          <StatCard label="Current" value={graph.summary.total_current} icon={<Award size={16} />} tone="success" />
          <StatCard label="Stale" value={graph.summary.total_stale} icon={<Wrench size={16} />} tone="warning" />
          <StatCard label="Expired" value={graph.summary.total_expired} icon={<Landmark size={16} />} tone="danger" />
        </div>
      ) : null}

      {canCreateManually && (
        <Card id="manual-add-card" className={manualFormOpen ? "border-primary/30" : undefined}>
          <CardHeader
            title="Add Manually"
            description={
              suggestedType
                ? `No document required. Looking for: ${suggestedType.replace(/_/g, " ")} evidence to close an open gap.`
                : "No document required -- enter capability details directly."
            }
            action={
              <Button
                variant={manualFormOpen ? "outline" : "primary"}
                size="sm"
                icon={<PenLine size={14} />}
                onClick={() => setManualFormOpen((v) => !v)}
              >
                {manualFormOpen ? "Cancel" : "Add Manually"}
              </Button>
            }
          />
          {manualFormOpen && (
            <CardBody className="space-y-4">
              <Select
                label="Entity type"
                value={manualEntityType}
                onChange={(e) => {
                  setManualEntityType(e.target.value as CapabilityEntityType);
                  setManualValues({});
                }}
                className="max-w-xs"
              >
                {ENTITY_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.replace(/_/g, " ")}
                  </option>
                ))}
              </Select>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {manualFieldSpecs.map((spec) => (
                  <Input
                    key={spec.name}
                    label={spec.required ? `${spec.label} *` : spec.label}
                    type={spec.kind === "date" ? "date" : spec.kind === "number" ? "number" : "text"}
                inputMode={spec.kind === "fiscal_year" ? "numeric" : undefined}
                    value={manualValues[spec.name] ?? ""}
                    onChange={(e) => setManualValues((prev) => ({ ...prev, [spec.name]: e.target.value }))}
                    placeholder={
                      spec.kind === "array"
                        ? "e.g. welding, rigging"
                        : spec.kind === "fiscal_year"
                        ? "e.g. 2024-25"
                        : undefined
                    }
                  />
                ))}
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" loading={manualSubmitting} onClick={handleManualSubmit}>
                  Save capability
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setManualFormOpen(false)} disabled={manualSubmitting}>
                  Cancel
                </Button>
              </div>
            </CardBody>
          )}
        </Card>
      )}

      <Card>
        <CardHeader
          title="Build from Document"
          description={
            suggestedType
              ? `Run extraction on an uploaded document. Looking for: ${suggestedType.replace(/_/g, " ")} evidence to close an open gap.`
              : "Run extraction on an uploaded document"
          }
        />
        <CardBody>
          {loading ? (
            <SkeletonList rows={2} />
          ) : documents.length === 0 ? (
            <EmptyState
              icon={Layers}
              title="No documents yet"
              description="Upload a document on the Documents page first."
              action={
                <Link to="/documents" className="text-sm font-medium text-primary hover:underline">
                  Go to Documents →
                </Link>
              }
            />
          ) : building ? (
            <AIProcessing stages={BUILD_STAGES} />
          ) : (
            <ul className="divide-y divide-border -mx-6">
              {documents.map((d) => {
                // One document, one-time capability -- once this document
                // has a live capability entity, Build is replaced with a
                // status hint instead of an action that would just 409.
                // Deleting the entity below (Certifications/Employees/etc.
                // section) frees the document up to be rebuilt.
                const alreadyBuilt = builtDocumentIds.has(d.id);
                const preview = previewsByDocument.get(d.id) ?? [];
                const shown = preview.slice(0, 4);
                const extra = preview.length - shown.length;
                // Fixed at upload time (Documents.tsx) -- not editable
                // here. A document uploaded as "other" (or any type this
                // page doesn't build capabilities for) has no mapping and
                // can't be built without being re-uploaded with a real type.
                const mappedType = DOCUMENT_TYPE_TO_ENTITY_TYPE[d.document_type];
                return (
                  <li key={d.id} className="px-6 py-3 flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <span className="text-sm font-medium truncate block">{d.file_name}</span>
                      {alreadyBuilt && shown.length > 0 && (
                        <ul className="mt-1.5 space-y-0.5">
                          {shown.map((item, i) => (
                            <li key={i} className="text-xs text-muted-foreground truncate">
                              • {item}
                            </li>
                          ))}
                          {extra > 0 && <li className="text-xs text-muted-foreground/70">+{extra} more</li>}
                        </ul>
                      )}
                    </div>
                    {alreadyBuilt ? (
                      <span className="text-xs text-muted-foreground shrink-0">
                        Capabilities built — delete below to rebuild
                      </span>
                    ) : mappedType && BUILDABLE_ENTITY_TYPES.includes(mappedType) ? (
                      <div className="flex items-center gap-2 shrink-0 flex-wrap">
                        <span className="px-2.5 py-1 rounded-md bg-surface-alt border border-border text-xs font-medium text-muted-foreground capitalize">
                          {mappedType.replace(/_/g, " ")}
                        </span>
                        <Button size="sm" onClick={() => handleBuild(d.id, mappedType, d.file_name)}>
                          Build Capabilities
                        </Button>
                      </div>
                    ) : mappedType ? (
                      // Equipment/FinancialRecord: no extraction agent exists
                      // for these two types (see BUILDABLE_ENTITY_TYPES'
                      // comment) -- document extraction was never possible
                      // here, only manual creation. Route to the manual form
                      // instead of offering a build button that would just
                      // 422 with "'{type}' is not supported by the Capability
                      // Builder in M3."
                      <div className="flex items-center gap-2 shrink-0 flex-wrap">
                        <span className="text-xs text-muted-foreground max-w-[200px] text-right">
                          {mappedType.replace(/_/g, " ")} can't be auto-extracted from a document yet.
                        </span>
                        <button
                          type="button"
                          // Same page, so a <Link> URL change alone wouldn't
                          // remount the component or re-run its
                          // useState(openManualOnLoad) initializer -- setting
                          // the form state directly is what actually opens it.
                          onClick={() => {
                            setManualEntityType(mappedType);
                            setManualFormOpen(true);
                            document.getElementById("manual-add-card")?.scrollIntoView({ behavior: "smooth" });
                          }}
                          className="text-xs font-medium text-primary hover:underline whitespace-nowrap"
                        >
                          Add manually →
                        </button>
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground shrink-0 max-w-[220px] text-right">
                        Uploaded as "{d.document_type.replace(/_/g, " ")}" -- delete and re-upload with a specific
                        document type to build capabilities.
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </CardBody>
      </Card>

      {graph && (
        <>
          <EntitySection icon={Award} title="Certifications" empty={graph.certifications.length === 0}>
            {graph.certifications.map((c) => (
              <EditableEntityRow
                key={c.id}
                entityType="certification"
                entity={c}
                displayLabel={
                  <span className="min-w-0 truncate">
                    {c.certification_name}
                    {c.issuing_authority && <span className="text-muted-foreground"> — {c.issuing_authority}</span>}
                  </span>
                }
                canEdit={canEditCapabilities}
                canDelete={canDeleteCapabilities}
                isEditing={editing?.id === c.id}
                editValues={editValues}
                editSubmitting={editSubmitting}
                onStartEdit={() => startEdit("certification", c)}
                onCancelEdit={cancelEdit}
                onFieldChange={(name, value) => setEditValues((prev) => ({ ...prev, [name]: value }))}
                onSaveEdit={handleEditSubmit}
                onDelete={() => handleRemoveCapability(c.id, c.certification_name)}
                deleting={removingId === c.id}
              />
            ))}
          </EntitySection>

          <EntitySection icon={Users} title="Employees" empty={graph.employees.length === 0}>
            {graph.employees.map((e) => (
              <EditableEntityRow
                key={e.id}
                entityType="employee"
                entity={e}
                displayLabel={
                  <span className="min-w-0 truncate">
                    {e.name}
                    {e.position && <span className="text-muted-foreground"> — {e.position}</span>}
                  </span>
                }
                extraLine={e.skills && e.skills.length > 0 ? <p className="text-xs text-muted-foreground mt-1">{e.skills.join(" · ")}</p> : undefined}
                canEdit={canEditCapabilities}
                canDelete={canDeleteCapabilities}
                isEditing={editing?.id === e.id}
                editValues={editValues}
                editSubmitting={editSubmitting}
                onStartEdit={() => startEdit("employee", e)}
                onCancelEdit={cancelEdit}
                onFieldChange={(name, value) => setEditValues((prev) => ({ ...prev, [name]: value }))}
                onSaveEdit={handleEditSubmit}
                onDelete={() => handleRemoveCapability(e.id, e.name)}
                deleting={removingId === e.id}
              />
            ))}
          </EntitySection>

          <EntitySection icon={Briefcase} title="Projects" empty={graph.projects.length === 0}>
            {graph.projects.map((p) => (
              <EditableEntityRow
                key={p.id}
                entityType="project"
                entity={p}
                displayLabel={
                  <span className="min-w-0 truncate">
                    {p.client ?? "Unnamed client"}
                    {p.industry && <span className="text-muted-foreground"> — {p.industry}</span>}
                  </span>
                }
                canEdit={canEditCapabilities}
                canDelete={canDeleteCapabilities}
                isEditing={editing?.id === p.id}
                editValues={editValues}
                editSubmitting={editSubmitting}
                onStartEdit={() => startEdit("project", p)}
                onCancelEdit={cancelEdit}
                onFieldChange={(name, value) => setEditValues((prev) => ({ ...prev, [name]: value }))}
                onSaveEdit={handleEditSubmit}
                onDelete={() => handleRemoveCapability(p.id, p.client ?? "Unnamed client")}
                deleting={removingId === p.id}
              />
            ))}
          </EntitySection>

          <EntitySection icon={Wrench} title="Equipment" empty={graph.equipment.length === 0}>
            {graph.equipment.map((eq) => (
              <EditableEntityRow
                key={eq.id}
                entityType="equipment"
                entity={eq}
                displayLabel={<span className="min-w-0 truncate">{eq.equipment_name}</span>}
                canEdit={canEditCapabilities}
                canDelete={canDeleteCapabilities}
                isEditing={editing?.id === eq.id}
                editValues={editValues}
                editSubmitting={editSubmitting}
                onStartEdit={() => startEdit("equipment", eq)}
                onCancelEdit={cancelEdit}
                onFieldChange={(name, value) => setEditValues((prev) => ({ ...prev, [name]: value }))}
                onSaveEdit={handleEditSubmit}
                onDelete={() => handleRemoveCapability(eq.id, eq.equipment_name)}
                deleting={removingId === eq.id}
              />
            ))}
          </EntitySection>

          <EntitySection icon={Landmark} title="Financial Records" empty={graph.financial_records.length === 0}>
            {graph.financial_records.map((f) => (
              <EditableEntityRow
                key={f.id}
                entityType="financial_record"
                entity={f}
                displayLabel={
                  <span className="min-w-0 truncate">{f.financial_year ? `FY ${f.financial_year}` : "—"}</span>
                }
                canEdit={canEditCapabilities}
                canDelete={canDeleteCapabilities}
                isEditing={editing?.id === f.id}
                editValues={editValues}
                editSubmitting={editSubmitting}
                onStartEdit={() => startEdit("financial_record", f)}
                onCancelEdit={cancelEdit}
                onFieldChange={(name, value) => setEditValues((prev) => ({ ...prev, [name]: value }))}
                onSaveEdit={handleEditSubmit}
                onDelete={() => handleRemoveCapability(f.id, `${f.financial_year ?? "record"} financial record`)}
                deleting={removingId === f.id}
              />
            ))}
          </EntitySection>
        </>
      )}
    </div>
  );
}

function DeleteEntityButton({ onClick, loading }: { onClick: () => void; loading: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading}
      className="w-6 h-6 rounded-md flex items-center justify-center text-muted-foreground hover:bg-danger-soft hover:text-danger transition-colors disabled:opacity-50"
      aria-label="Delete capability entry"
    >
      <Trash2 size={13} />
    </button>
  );
}

function EditEntityButton({ onClick, active }: { onClick: () => void; active: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-6 h-6 rounded-md flex items-center justify-center transition-colors ${
        active ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-primary/10 hover:text-primary"
      }`}
      aria-label={active ? "Cancel editing" : "Edit capability entry"}
    >
      <Pencil size={13} />
    </button>
  );
}

// Shared row for all five Capability Library sections -- renders the
// entity summary line plus (when editing) an inline PATCH /capabilities/{id}
// form built from MANUAL_FIELDS, the same field spec manual creation uses.
// A field left blank on save is simply not sent (update_capability_fields
// only touches keys present in the payload), so clearing a value here isn't
// currently supported -- consistent with there being no "unset" affordance
// anywhere else in the capability CRUD surface.
function EditableEntityRow({
  entityType,
  entity,
  displayLabel,
  extraLine,
  canEdit,
  canDelete,
  isEditing,
  editValues,
  editSubmitting,
  onStartEdit,
  onCancelEdit,
  onFieldChange,
  onSaveEdit,
  onDelete,
  deleting,
}: {
  entityType: CapabilityEntityType;
  entity: { id: string; freshness_status: string };
  displayLabel: React.ReactNode;
  extraLine?: React.ReactNode;
  canEdit: boolean;
  canDelete: boolean;
  isEditing: boolean;
  editValues: Record<string, string>;
  editSubmitting: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onFieldChange: (name: string, value: string) => void;
  onSaveEdit: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  return (
    <li className="py-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        {/* The truncate boundary has to live on this div, not just on
            displayLabel's own <span> -- a flex item's child span is no
            longer a direct flex item itself (flexbox only auto-blockifies
            its own direct children), so without overflow-hidden/nowrap
            here a long name/label spills past its column and visually
            collides with the badge/edit/delete icons instead of
            ellipsis-truncating. */}
        <div className="min-w-0 flex-1">
          <div className="truncate">{displayLabel}</div>
          {extraLine}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Badge value={entity.freshness_status} />
          {canEdit && <EditEntityButton active={isEditing} onClick={isEditing ? onCancelEdit : onStartEdit} />}
          {canDelete && <DeleteEntityButton loading={deleting} onClick={onDelete} />}
        </div>
      </div>
      {isEditing && (
        <div className="mt-3 pt-3 border-t border-border space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {MANUAL_FIELDS[entityType].map((spec) => (
              <Input
                key={spec.name}
                label={spec.required ? `${spec.label} *` : spec.label}
                type={spec.kind === "date" ? "date" : spec.kind === "number" ? "number" : "text"}
                inputMode={spec.kind === "fiscal_year" ? "numeric" : undefined}
                value={editValues[spec.name] ?? ""}
                onChange={(e) => onFieldChange(spec.name, e.target.value)}
                placeholder={spec.kind === "array" ? "e.g. welding, rigging" : undefined}
              />
            ))}
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" loading={editSubmitting} onClick={onSaveEdit}>
              Save changes
            </Button>
            <Button variant="ghost" size="sm" onClick={onCancelEdit} disabled={editSubmitting}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

function EntitySection({
  icon: Icon,
  title,
  empty,
  children,
}: {
  icon: LucideIcon;
  title: string;
  empty: boolean;
  children: React.ReactNode;
}) {
  if (empty) return null;
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Icon size={14} className="text-muted-foreground" />{title}</span>} />
      <CardBody className="!py-1">
        <ul className="divide-y divide-border">{children}</ul>
      </CardBody>
    </Card>
  );
}
