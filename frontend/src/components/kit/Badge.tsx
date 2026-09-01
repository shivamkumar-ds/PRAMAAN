import { cn } from "../../lib/cn";
import { CheckCircle2, XCircle, HelpCircle, AlertCircle, type LucideIcon } from "lucide-react";

type Tone = "success" | "warning" | "danger" | "info" | "neutral";

const toneClasses: Record<Tone, string> = {
  success: "bg-success-soft text-success border-success/20",
  warning: "bg-warning-soft text-warning border-warning/20",
  danger: "bg-danger-soft text-danger border-danger/20",
  info: "bg-info-soft text-info border-info/20",
  neutral: "bg-muted text-muted-foreground border-border",
};

// Central semantic mapping -- every status/risk/recommendation value used
// anywhere in the product maps here ONCE, so tone is always consistent
// regardless of which page renders it.
const semanticTone: Record<string, Tone> = {
  met: "success", go: "success", low: "success", completed: "success", active: "success", verified: "success", verified_compliant: "success",
  conditional: "warning", conditional_go: "warning", medium: "warning", review: "warning", review_required: "warning", pending: "neutral", stale: "warning", processing: "info", escalated: "warning",
  not_met: "danger", no_go: "danger", critical: "danger", high: "danger", failed: "danger", expired: "danger", verified_non_compliant: "danger",
  running: "info", created: "neutral", awaiting_approval: "warning", archived: "neutral", current: "success",
  mandatory: "neutral",
  // SIH26100 -- Bidder Verification domain (ComplianceVerificationStatus /
  // OfficerDecisionType / SubmissionStatus). "verified" and "critical"
  // already map above and are reused as-is.
  mismatch: "warning", missing: "warning", critical_fail: "danger", not_applicable: "neutral", not_claimed: "neutral",
  approve: "success", reject: "danger", request_clarification: "warning",
  submitted: "neutral", under_review: "info", decided: "success",
  open: "success", closed: "neutral",
  // BidderDocument.extraction_status (Phase 4). "pending", "processing",
  // "review_required", and "failed" already map above via existing keys.
  extracted: "success",
  // Synthetic document-row display statuses (Phase 5) -- derived in
  // BidderVerification.tsx from (extraction_status, is_confirmed), not
  // real backend enum values: an EXTRACTED-but-unconfirmed document
  // still needs officer action (warning), a confirmed one is resolved
  // (success).
  needs_confirmation: "warning",
  confirmed: "success",
};

const statusIcon: Record<string, LucideIcon> = {
  met: CheckCircle2,
  go: CheckCircle2,
  not_met: XCircle,
  no_go: XCircle,
  review_required: HelpCircle,
  review: HelpCircle,
  conditional: AlertCircle,
  conditional_go: AlertCircle,
  verified: CheckCircle2,
  mismatch: AlertCircle,
  missing: HelpCircle,
  critical_fail: XCircle,
  approve: CheckCircle2,
  reject: XCircle,
  request_clarification: HelpCircle,
  extracted: CheckCircle2,
  needs_confirmation: AlertCircle,
  confirmed: CheckCircle2,
};

export function Badge({ value, withIcon = false, label }: { value: string; withIcon?: boolean; label?: string }) {
  const tone = semanticTone[value] ?? "neutral";
  const Icon = statusIcon[value];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide whitespace-nowrap",
        toneClasses[tone]
      )}
    >
      {withIcon && Icon && <Icon size={11} />}
      {/* `label` overrides the displayed text (e.g. "go" -> "Proceed") while
          tone/icon still key off the real backend `value` -- presentation
          only, the raw enum value driving styling never changes. */}
      {label ?? value.replace(/_/g, " ")}
    </span>
  );
}

export function Dot({ value }: { value: string }) {
  const tone = semanticTone[value] ?? "neutral";
  const dotColor: Record<Tone, string> = {
    success: "bg-success",
    warning: "bg-warning",
    danger: "bg-danger",
    info: "bg-info",
    neutral: "bg-muted-foreground",
  };
  return <span className={cn("inline-block w-1.5 h-1.5 rounded-full", dotColor[tone])} />;
}
