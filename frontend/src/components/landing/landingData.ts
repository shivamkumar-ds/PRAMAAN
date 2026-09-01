import type { LucideIcon } from "lucide-react";
import {
  Gauge,
  Layers,
  FileBarChart2,
  Workflow,
  FileSearch,
  ShieldCheck,
  Sparkles,
  Lock,
  Building2,
  HardHat,
  Factory,
  Landmark,
  HeartPulse,
  Shield,
  Briefcase,
  BookOpen,
  FileText,
  HelpCircle,
  FileUp,
  Users,
  History,
  UserPlus,
  Gavel,
} from "lucide-react";

// Content for the marketing landing page only -- lives here rather than
// inline in components so the (fairly long) copy for each nav dropdown
// panel is easy to review/edit without wading through JSX. Per the
// explicit brief: no fabricated customer counts, no invented pricing, no
// lorem ipsum -- every string below is either a real product capability
// (matching what pages/sih/*.tsx and app/services/sih/* actually do) or
// an honest "not yet available" statement.
//
// PRAMAAN (SIH26100) is a bid compliance *verification* platform for
// procurement officers, not a bidder-side tender-evaluation tool -- the
// copy below describes the officer's real workflow (Procurement -> Add
// Bidder -> upload bidder documents -> AI extraction -> officer review &
// confirm -> run verification against simulated government registries ->
// compliance score & risk level -> officer decision), not the older
// PRAMAAN bidder-side pitch this file previously carried.

export interface DropdownCard {
  icon: LucideIcon;
  title: string;
  description: string;
  details: string[];
}

// Orphaned since the Solutions nav dropdown renders `solutionVerticals`
// below instead -- left in place (now content-accurate) in case a
// simpler summary card set is useful elsewhere later.
export const solutions: DropdownCard[] = [
  {
    icon: ShieldCheck,
    title: "Bidder Compliance Verification",
    description: "Verify bidder submissions against simulated government registries before an award decision.",
    details: [
      "Cross-checks declared bidder details against 12 simulated registry sources",
      "Every result carries a status, discrepancy, and reason -- never a bare verdict",
      "A transparent compliance score and Low / Medium / High / Critical risk level",
    ],
  },
  {
    icon: Sparkles,
    title: "AI Document Extraction",
    description: "Extracts bidder identity and registration details from uploaded documents, reviewed by an officer.",
    details: [
      "Handles both text-based and scanned bidder documents",
      "Every extracted field is reviewed and explicitly confirmed before it counts",
      "Full traceability back to the exact source document",
    ],
  },
  {
    icon: FileBarChart2,
    title: "Auditable Officer Decisions",
    description: "Approve, reject, or request clarification -- every decision is recorded and preserved.",
    details: [
      "Insert-only decision history, never silently overwritten",
      "A written note is required for every recorded decision",
      "Full audit trail from a final decision back to the original evidence",
    ],
  },
  {
    icon: Workflow,
    title: "Procurement Workspace",
    description: "Manage every procurement from bidder onboarding through verification to a recorded decision.",
    details: [
      "A shared workspace per procurement, from first bidder added to final call",
      "Status tracking across every stage of verification",
      "Company-scoped access so tenants never see each other's data",
    ],
  },
];

// Category used to power the "Our Core Features" filter pills in the
// Features mega-panel. Purely a client-side grouping of the same real
// feature copy below -- no new claims, just a filter.
export type FeatureCategory =
  | "Document Intelligence"
  | "Registry Verification"
  | "Decision Intelligence"
  | "Audit & Compliance";

export interface FeatureCard extends DropdownCard {
  category: FeatureCategory;
  // Per-card icon accent -- this panel intentionally breaks from the
  // single-accent-color rule elsewhere on the site (founder-directed,
  // matching the approved reference layout) so eight distinct
  // capabilities read as visually distinct at a glance.
  color: { bg: string; text: string };
}

export const features: FeatureCard[] = [
  {
    icon: FileText,
    title: "AI Document Extraction",
    description: "Extracts bidder identity, registration numbers, and declared details from uploaded documents.",
    category: "Document Intelligence",
    color: { bg: "bg-blue-50", text: "text-blue-600" },
    details: [
      "Handles both text-based and scanned bidder documents",
      "Preserves the source document for every extracted field",
      "Extraction never auto-confirms -- a human always reviews it first",
    ],
  },
  {
    icon: Layers,
    title: "Officer Review & Confirmation",
    description: "Every AI-extracted field is reviewed, corrected if needed, and explicitly confirmed by an officer.",
    category: "Document Intelligence",
    color: { bg: "bg-emerald-50", text: "text-emerald-600" },
    details: [
      "No verification runs against unconfirmed data",
      "Officer corrections are tracked separately from the original AI extraction",
      "Keeps a human in the loop at every step, not just at the final decision",
    ],
  },
  {
    icon: ShieldCheck,
    title: "Simulated Registry Verification",
    description: "Cross-checks bidder claims against 12 simulated government registry sources.",
    category: "Registry Verification",
    color: { bg: "bg-violet-50", text: "text-violet-600" },
    details: [
      "Udyam, GST, PAN/Income Tax, MCA21, EPFO, ESIC, NSIC, Startup India, OEM Authorization, DigiLocker, Make in India, and Blacklist/Debarment",
      "Every registry source is clearly disclosed as simulated, deterministic mock data -- no live government portal is ever queried",
      "EPFO and ESIC are tracked as fully separate, independently checkable categories",
    ],
  },
  {
    icon: Gauge,
    title: "Compliance Score & Risk Level",
    description: "A transparent compliance score and a Low / Medium / High / Critical risk level for every submission.",
    category: "Decision Intelligence",
    color: { bg: "bg-orange-50", text: "text-orange-600" },
    details: [
      "A high score can never override a critical finding, like a blacklisted bidder or a PAN mismatch",
      "Mandatory and optional verification categories are scored differently",
      "Every score is explainable, tied back to the underlying category results",
    ],
  },
  {
    icon: FileSearch,
    title: "Category-by-Category Findings",
    description: "Drill into any verification category to see the bidder's declared value against the registry value.",
    category: "Registry Verification",
    color: { bg: "bg-teal-50", text: "text-teal-600" },
    details: [
      "VERIFIED, MISMATCH, MISSING, or CRITICAL -- normalized statuses, no ambiguity",
      "Every finding shows the exact discrepancy and a written reason",
      "Traces back to the confirmed bidder document that produced it, where applicable",
    ],
  },
  {
    icon: Lock,
    title: "Multi-Tenant Data Isolation",
    description: "Every procurement, bidder, and document stays scoped to your organization.",
    category: "Audit & Compliance",
    color: { bg: "bg-sky-50", text: "text-sky-600" },
    details: [
      "No document or verification result is ever visible across organizational boundaries",
      "Company-scoped access enforced at every layer, not just the UI",
      "Same isolation guarantees enforced across the entire platform",
    ],
  },
  {
    icon: History,
    title: "Officer Decisions & Audit Trail",
    description: "Approve, reject, or request clarification -- every decision recorded with a note, never overwritten.",
    category: "Audit & Compliance",
    color: { bg: "bg-rose-50", text: "text-rose-600" },
    details: [
      "Insert-only decision history -- nothing is ever silently edited",
      "Every decision is manually made by a procurement officer, never automated",
      "Full traceability from a final decision back to the original evidence",
    ],
  },
  {
    icon: FileBarChart2,
    title: "Explainable Verification",
    description: "Every result -- from a single registry check to the overall compliance score -- comes with a reason.",
    category: "Decision Intelligence",
    color: { bg: "bg-purple-50", text: "text-purple-600" },
    details: [
      "No verdict without a traceable source",
      "Discrepancies are described in plain language, not error codes",
      "Built for a procurement officer to review and act on, not a data scientist",
    ],
  },
];

export const featureCategories: ("All Features" | FeatureCategory)[] = [
  "All Features",
  "Document Intelligence",
  "Registry Verification",
  "Decision Intelligence",
  "Audit & Compliance",
];

// The 2x2 capability-highlight grid -- paraphrased from the feature
// details above, not new claims. Orphaned (not currently rendered by
// FeaturesMegaPanel), kept content-accurate in case it's wired up later.
export const featureHighlights: { icon: LucideIcon; title: string; description: string }[] = [
  {
    icon: Sparkles,
    title: "AI-Powered Extraction",
    description: "Extracts bidder identity and registration data with full source-document traceability.",
  },
  {
    icon: ShieldCheck,
    title: "Explainable Verification",
    description: "Every result is backed by a registry value, a discrepancy, and a written reason -- never a black box.",
  },
  {
    icon: Lock,
    title: "Secure & Compliant",
    description: "Enterprise-grade security with strict tenant isolation and complete data privacy.",
  },
  {
    icon: Layers,
    title: "Built for Scale",
    description: "Handles multiple procurements, bidders, and documents without slowing down.",
  },
];

// The Solutions mega-panel groups by the type of buying organization
// PRAMAAN is built for -- procurement officers at government departments,
// PSUs, and similar bodies verifying *bidders*, not bidders themselves.
// Same DropdownCard shape as everything else so it works with the same
// expand-in-place "Learn more" pattern used throughout the site.
export const solutionVerticals: DropdownCard[] = [
  {
    icon: Landmark,
    title: "Government Departments",
    description: "Verify bidder submissions for GeM procurements with a transparent, auditable process.",
    details: [
      "Cross-checks bidder registrations against Udyam, GST, PAN, and MCA21",
      "Every finding is traceable back to a confirmed bidder document",
      "Officer decisions are recorded with a mandatory note for every call",
    ],
  },
  {
    icon: Building2,
    title: "Public Sector Undertakings (PSUs)",
    description: "Run bidder compliance checks across large-scale PSU tenders with a consistent workflow.",
    details: [
      "One verification workflow across every procurement, not a one-off manual check",
      "Company-scoped workspace shared across your verification team",
      "Compliance score and risk level computed the same way, every time",
    ],
  },
  {
    icon: HardHat,
    title: "Infrastructure & PWD",
    description: "Verify contractor registrations, EPFO/ESIC compliance, and blacklist status for works tenders.",
    details: [
      "EPFO and ESIC checked as separate, independently verifiable categories",
      "Blacklist/debarment checks flagged as a deterministic critical finding",
      "MCA21 status check catches issues like a struck-off company registration",
    ],
  },
  {
    icon: HeartPulse,
    title: "Healthcare Procurement",
    description: "Confirm bidder registrations and certifications for medical equipment and hospital tenders.",
    details: [
      "OEM Authorization verification confirms a bidder is actually authorized to supply",
      "DigiLocker cross-check flags a possibly tampered supporting document",
      "Every category result is reviewable individually before a decision is recorded",
    ],
  },
  {
    icon: Shield,
    title: "Defence Procurement",
    description: "Verify sensitive supplier submissions with strict tenant isolation and a full audit trail.",
    details: [
      "Company-scoped data isolation keeps sensitive procurement data private",
      "Insert-only Officer Decision history for full accountability",
      "A critical identity finding always overrides a high numerical score",
    ],
  },
  {
    icon: BookOpen,
    title: "Educational Institutions",
    description: "Check vendor and contractor compliance for institutional procurement, from Udyam to blacklist.",
    details: [
      "Startup India / NSIC / Udyam checks support MSME-preference evaluation",
      "Make in India local-content check for eligible procurement categories",
      "Clear VERIFIED / MISMATCH / MISSING / CRITICAL status per category",
    ],
  },
  {
    icon: Factory,
    title: "Municipal Corporations",
    description: "Verify local contractors and suppliers against MCA21, GST, and labour-compliance registries.",
    details: [
      "Structured document review before any verification is run",
      "Discrepancies shown in plain language, ready for officer sign-off",
      "Full history of every decision made, for every submission",
    ],
  },
  {
    icon: Briefcase,
    title: "Central & State Agencies",
    description: "Scale bidder verification across teams with role-based officer review and centralized audit trails.",
    details: [
      "Every category, source, discrepancy, and reason persisted for audit",
      "A written decision note required for every Approve, Reject, or Clarification",
      "Simulated registries clearly disclosed -- built for a demo, honest about it",
    ],
  },
];

// Orphaned since the How It Works dropdown moved to the 7-step
// processSteps timeline below (per the founder-approved reference). Left
// in place, now content-accurate, in case a simpler 4-step summary is
// useful elsewhere later.
export const howItWorks: DropdownCard[] = [
  {
    icon: UserPlus,
    title: "1. Add a Bidder",
    description: "Create a procurement, add a bidder, and upload their registration and compliance documents.",
    details: [
      "Handles both text-based and scanned bidder documents",
      "Every document stays scoped to your organization",
      "Documents can be added incrementally as a bidder submits more",
    ],
  },
  {
    icon: Sparkles,
    title: "2. Extract & Confirm",
    description: "AI reads each document and extracts identity and registration details for officer review.",
    details: [
      "Distinguishes declared identifiers from supporting context automatically",
      "An officer reviews, corrects if needed, and explicitly confirms every field",
      "Verification never runs against unconfirmed data",
    ],
  },
  {
    icon: ShieldCheck,
    title: "3. Verify",
    description: "Every confirmed detail is checked against a simulated government registry, with evidence attached.",
    details: [
      "Covers 12 verification categories, from Udyam to Blacklist/Debarment",
      "Surfaces the exact discrepancy and reason for every non-clean result",
      "A critical finding is never softened by a high overall score",
    ],
  },
  {
    icon: Gavel,
    title: "4. Decide",
    description: "Get a compliance score, risk level, and a full audit trail -- then record the officer's decision.",
    details: [
      "Compliance score, risk level, and every category result on one screen",
      "Approve, Reject, or Request Clarification, always with a written note",
      "Insert-only Decision History, never silently overwritten",
    ],
  },
];

export interface ProcessStep {
  step: number;
  icon: LucideIcon;
  title: string;
  description: string;
  color: { bg: string; text: string };
}

// The 7-step "How It Works" timeline -- matches the approved reference
// layout, now mapped to PRAMAAN's actual verification flow (Procurement
// -> Bidder -> Documents -> Extraction -> Officer confirmation ->
// Verification -> Decision), not an aspirational workflow.
export const processSteps: ProcessStep[] = [
  {
    step: 1,
    icon: FileUp,
    title: "Create a Procurement",
    description: "Set up a new procurement and add the bidders whose submissions need to be verified.",
    color: { bg: "bg-blue-50", text: "text-blue-600" },
  },
  {
    step: 2,
    icon: UserPlus,
    title: "Add Bidder & Upload Documents",
    description: "Add a bidder and upload their registration, GST, PAN, and other compliance documents.",
    color: { bg: "bg-emerald-50", text: "text-emerald-600" },
  },
  {
    step: 3,
    icon: Sparkles,
    title: "AI Extracts Bidder Data",
    description: "AI reads each document and extracts identity, registration numbers, and declared details.",
    color: { bg: "bg-violet-50", text: "text-violet-600" },
  },
  {
    step: 4,
    icon: FileSearch,
    title: "Officer Reviews & Confirms",
    description: "A procurement officer reviews the extracted data, corrects anything wrong, and confirms it.",
    color: { bg: "bg-orange-50", text: "text-orange-600" },
  },
  {
    step: 5,
    icon: ShieldCheck,
    title: "Run Verification",
    description: "PRAMAAN checks every confirmed detail against simulated government registries -- Udyam, GST, PAN, MCA21, EPFO, ESIC, and more.",
    color: { bg: "bg-sky-50", text: "text-sky-600" },
  },
  {
    step: 6,
    icon: Gauge,
    title: "Compliance Score & Risk Level",
    description: "Review VERIFIED, MISMATCH, MISSING, or CRITICAL findings per category, plus an overall score and risk level.",
    color: { bg: "bg-purple-50", text: "text-purple-600" },
  },
  {
    step: 7,
    icon: FileBarChart2,
    title: "Record Officer Decision",
    description: "Approve, reject, or request clarification -- with a note preserved in a fully auditable decision trail.",
    color: { bg: "bg-teal-50", text: "text-teal-600" },
  },
];

export interface ProcessTrustPoint {
  icon: LucideIcon;
  title: string;
  description: string;
}

// Bottom trust row for the How It Works panel -- deliberately reuses the
// same honest claims already established for the page's main trust row
// (trustStatements below), just with a one-line description each.
export const processTrustPoints: ProcessTrustPoint[] = [
  {
    icon: ShieldCheck,
    title: "Evidence-Backed",
    description: "Every verification result is supported with a registry value and a reason.",
  },
  {
    icon: FileSearch,
    title: "Explainable Findings",
    description: "Transparent, category-by-category results, no black-box scoring.",
  },
  {
    icon: Lock,
    title: "Enterprise Grade Security",
    description: "Your data is private, secure, and access-scoped to your organization.",
  },
  {
    icon: Sparkles,
    title: "AI-Powered Extraction",
    description: "Advanced reasoning for bidder documents, always reviewed by an officer.",
  },
  {
    icon: Users,
    title: "Built for Officers",
    description: "Review, verify, and decide with confidence.",
  },
];

export interface Industry {
  icon: LucideIcon;
  name: string;
  description: string;
}

// Orphaned (not currently rendered) -- kept content-accurate as a shorter
// summary of solutionVerticals above, in case a compact chip list is
// useful elsewhere later.
export const industries: Industry[] = [
  { icon: Landmark, name: "Government", description: "Verify GeM bidder submissions with a transparent, auditable process." },
  { icon: Building2, name: "PSUs", description: "Run consistent bidder compliance checks across large-scale PSU tenders." },
  { icon: HardHat, name: "Infrastructure", description: "Verify contractor registrations and labour-compliance status for works tenders." },
  { icon: HeartPulse, name: "Healthcare", description: "Confirm bidder registrations and OEM authorizations for health-sector tenders." },
  { icon: Shield, name: "Defence", description: "Verify sensitive supplier submissions with strict tenant isolation." },
  { icon: BookOpen, name: "Education", description: "Check vendor compliance for institutional procurement." },
  { icon: Factory, name: "Municipal", description: "Verify local contractors against MCA21, GST, and labour registries." },
  { icon: Briefcase, name: "Central & State Agencies", description: "Scale bidder verification across teams with centralized audit trails." },
];

export interface ResourceItem {
  icon: LucideIcon;
  title: string;
  description: string;
}

// Orphaned (not currently rendered).
export const resources: ResourceItem[] = [
  { icon: BookOpen, title: "Documentation", description: "Step-by-step guidance on using PRAMAAN. Coming soon." },
  { icon: FileText, title: "Product Overview", description: "A walkthrough of the verification workflow end to end. Coming soon." },
  { icon: HelpCircle, title: "FAQ", description: "Answers to common questions about the platform. Coming soon." },
  { icon: ShieldCheck, title: "Security", description: "Details on how PRAMAAN handles data and access. Coming soon." },
  { icon: Sparkles, title: "Release Notes", description: "What's new in PRAMAAN, as it ships. Coming soon." },
];

// Corrected per a content-accuracy pass: the previous "Google AI Powered"
// and "Hosted on Google Cloud" statements were stale -- OpenAI is the
// operational default provider today (Vertex/Gemini is the strategic,
// not-yet-primary path, per backend/app/core/config.py), and there is no
// production deployment yet (docs/DEPLOYMENT.md), so neither claim is
// true right now. Statements below are grounded in what's actually
// implemented and tested (multi-tenancy isolation, Officer Decision
// history).
export const trustStatements: { icon: LucideIcon; label: string }[] = [
  { icon: ShieldCheck, label: "Enterprise Grade Security" },
  { icon: Lock, label: "Multi-Tenant Data Isolation" },
  { icon: Sparkles, label: "AI-Powered Extraction" },
  { icon: History, label: "Audit-Ready Decision Trail" },
  { icon: Briefcase, label: "Designed for Procurement Officers" },
  { icon: FileSearch, label: "Explainable Verification" },
];
