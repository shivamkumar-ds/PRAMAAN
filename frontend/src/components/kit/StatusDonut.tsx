const SEGMENT_COLOR: Record<string, string> = {
  met: "hsl(var(--success))",
  conditional: "hsl(var(--warning))",
  review_required: "hsl(var(--info))",
  not_met: "hsl(var(--danger))",
  // SIH26100 -- ComplianceVerificationStatus vocabulary (PRAMAAN Overview's
  // Verification Status Overview donut). Additive only; every existing
  // PRAMAAN caller above is untouched.
  verified: "hsl(var(--success))",
  mismatch: "hsl(var(--warning))",
  missing: "hsl(var(--warning))",
  critical_fail: "hsl(var(--danger))",
  not_claimed: "hsl(var(--muted-foreground))",
  not_applicable: "hsl(var(--muted-foreground))",
};

export function StatusDonut({
  segments,
  size = 120,
  centerLabel,
  centerSubLabel = "Average",
}: {
  segments: { key: string; label: string; count: number }[];
  size?: number;
  centerLabel: string;
  /** Defaults to "Average" so every existing caller renders identically.
   * PRAMAAN Overview's donut passes "Total" instead, since its centerLabel
   * is a count, not an average. */
  centerSubLabel?: string;
}) {
  const total = segments.reduce((sum, s) => sum + s.count, 0) || 1;
  const strokeWidth = 12;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  let offsetSoFar = 0;
  const arcs = segments
    .filter((s) => s.count > 0)
    .map((s) => {
      const fraction = s.count / total;
      const dash = fraction * circumference;
      const arc = (
        <circle
          key={s.key}
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={SEGMENT_COLOR[s.key] ?? "hsl(var(--muted-foreground))"}
          strokeWidth={strokeWidth}
          strokeDasharray={`${dash} ${circumference - dash}`}
          strokeDashoffset={-offsetSoFar}
          strokeLinecap="butt"
        />
      );
      offsetSoFar += dash;
      return arc;
    });

  return (
    <div className="flex items-center gap-3">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle cx={size / 2} cy={size / 2} r={radius} stroke="hsl(var(--muted))" strokeWidth={strokeWidth} fill="none" />
          {arcs}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-bold tabular-nums">{centerLabel}</span>
          <span className="text-[10px] text-muted-foreground uppercase tracking-wide">{centerSubLabel}</span>
        </div>
      </div>
      {/* Each entry stacks label above percentage rather than sitting on one
          row -- a single row (dot + full label + "17% (2)") doesn't fit in
          narrower cards (e.g. PRAMAAN Overview's Verification Status
          widget) and previously forced the label into a truncated,
          unreadable "Misma..." / "Not Cl..." ellipsis. Stacking removes the
          need to truncate at all, at any card width. */}
      <div className="space-y-1.5 min-w-0">
        {segments.map((s) => (
          <div key={s.key} className="flex items-start gap-1.5 text-xs">
            <span
              className="w-2 h-2 rounded-full shrink-0 mt-1"
              style={{ background: SEGMENT_COLOR[s.key] ?? "hsl(var(--muted-foreground))" }}
            />
            <div className="min-w-0 leading-tight">
              <div className="text-muted-foreground">{s.label}</div>
              <div className="font-semibold tabular-nums">
                {total ? Math.round((s.count / total) * 100) : 0}% ({s.count})
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
