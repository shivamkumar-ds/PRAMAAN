import { cn } from "../../lib/cn";

// riskLevel is optional and, when given, can only ever push the tone
// toward danger -- it never softens what the numeric score alone would
// produce. This mirrors Badge.tsx's own risk_level->tone map (critical
// and high both -> "danger"), so a bidder whose risk_level is
// critical/high can never render with a warning/success-colored ring
// just because compliance_score happens to be diluted by other, clean
// categories. See the E2E smoke-test report: risk_level=critical with a
// mid-numeric score (e.g. a blacklisted-but-otherwise-clean bidder) is
// exactly the case this guards against -- "a high/decent score must
// never visually imply that a critically risky bidder is safe."
function toneForValue(pct: number, riskLevel?: string | null) {
  if (riskLevel === "critical" || riskLevel === "high") return { bar: "bg-danger", text: "text-danger" };
  if (pct >= 85) return { bar: "bg-success", text: "text-success" };
  if (pct >= 60) return { bar: "bg-warning", text: "text-warning" };
  return { bar: "bg-danger", text: "text-danger" };
}

export function ConfidenceBar({ label, value }: { label: string; value: number | null }) {
  const pct = value == null ? null : Math.round(value * 100);
  const tone = toneForValue(pct ?? 0);
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className={cn("text-xs font-semibold tabular-nums", pct == null ? "text-muted-foreground" : tone.text)}>
          {pct == null ? "—" : `${pct}%`}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-500", tone.bar)}
          style={{ width: `${pct ?? 0}%` }}
        />
      </div>
    </div>
  );
}

export function ConfidenceRing({
  value,
  size = 88,
  riskLevel,
}: {
  value: number | null;
  size?: number;
  /** Compliance-score-specific: when "critical"/"high", forces the danger
   * tone regardless of the numeric score -- see toneForValue's comment.
   * Omit for any non-risk use of this ring (there are none today, but the
   * prop is intentionally optional so this stays a generic ring). */
  riskLevel?: string | null;
}) {
  const pct = value == null ? 0 : Math.round(value * 100);
  const tone = toneForValue(pct, riskLevel);
  const strokeWidth = 7;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - pct / 100);

  const strokeColor =
    tone.bar === "bg-success" ? "hsl(var(--success))" : tone.bar === "bg-warning" ? "hsl(var(--warning))" : "hsl(var(--danger))";

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} stroke="hsl(var(--muted))" strokeWidth={strokeWidth} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={strokeColor}
          strokeWidth={strokeWidth}
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-xl font-bold tabular-nums">{value == null ? "—" : `${pct}%`}</span>
      </div>
    </div>
  );
}
