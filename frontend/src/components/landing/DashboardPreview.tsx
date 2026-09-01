import { Bell, CheckCircle2, ClipboardList, LayoutDashboard, Search, Sparkles } from "lucide-react";
import { Logo } from "../kit";

// A static, illustrative mock of the authenticated PRAMAAN Overview -- used
// only in the marketing hero to communicate "this is a real product," not a
// live data view. Deliberately restrained: no invented analytics, no
// exaggerated charts, just the shape of the actual app (sidebar, a
// handful of stat cards, two short lists) mirroring pages/Dashboard.tsx
// as it exists today -- same 4 stat cards (Procurements / Bidder
// Submissions / Completed Verifications / Critical Findings), same
// "Recent Procurements" and "Recent Activity" cards. Content is
// representative sample data, clearly not a real customer's procurements.
export function DashboardPreview() {
  return (
    <div className="hidden lg:block rounded-2xl border border-border bg-surface shadow-hero overflow-hidden">
      <div className="flex">
        <div className="w-40 shrink-0 border-r border-border bg-background/60 px-3 py-4">
          <div className="mb-4">
            <Logo size={18} wordmarkClassName="text-xs" />
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-2 rounded-md bg-primary/10 text-primary px-2.5 py-1.5 text-[11px] font-medium">
              <LayoutDashboard size={12} /> Overview
            </div>
            {["Procurements", "Bidders", "Verification Queue", "Audit Trail"].map((label) => (
              <div key={label} className="rounded-md px-2.5 py-1.5 text-[11px] text-muted-foreground">
                {label}
              </div>
            ))}
          </div>
        </div>

        <div className="flex-1 min-w-0 flex flex-col">
          <div className="h-10 border-b border-border flex items-center justify-end gap-3 px-4 shrink-0">
            <Search size={12} className="text-muted-foreground" />
            <Bell size={12} className="text-muted-foreground" />
            <div className="w-5 h-5 rounded-full bg-primary/15 text-primary flex items-center justify-center text-[9px] font-semibold">
              A
            </div>
          </div>

          <div className="p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <p className="text-sm font-semibold tracking-tight">Good morning 👋</p>
                <p className="text-[11px] text-muted-foreground">Here's what's happening with your procurements today.</p>
              </div>
            </div>

            {/* Same 4 cards as the real Dashboard.tsx stat row (Procurements,
                Bidder Submissions, Completed Verifications, Critical
                Findings) -- 2x2 here since the mockup column is narrower
                than the real page. */}
            <div className="grid grid-cols-2 gap-2.5 mb-4">
              {[
                { label: "Procurements", value: "6" },
                { label: "Bidder Submissions", value: "9" },
                { label: "Completed Verifications", value: "7" },
                { label: "Critical Findings", value: "2", tone: "text-danger" },
              ].map((stat) => (
                <div key={stat.label} className="rounded-lg border border-border bg-surface px-3 py-2.5">
                  <p className="text-[9px] font-medium uppercase tracking-wide text-muted-foreground">{stat.label}</p>
                  <p className={`text-lg font-semibold tabular-nums mt-0.5 ${stat.tone ?? ""}`}>{stat.value}</p>
                </div>
              ))}
            </div>

            <div className="space-y-2.5">
              <div className="rounded-lg border border-border bg-surface p-3">
                <p className="text-[10px] font-semibold flex items-center gap-1.5 mb-2">
                  <ClipboardList size={11} className="text-muted-foreground" /> Recent Procurements
                </p>
                <div className="space-y-1.5">
                  {[
                    { name: "GeM Pipeline Maintenance", status: "Awaiting Review", tone: "text-warning bg-warning-soft" },
                    { name: "Municipal IT Services", status: "Completed", tone: "text-success bg-success-soft" },
                  ].map((t) => (
                    <div key={t.name} className="flex items-center justify-between gap-1.5 text-[10px]">
                      <span className="text-foreground/80 truncate">{t.name}</span>
                      <span className={`text-[8px] font-medium rounded px-1 py-0.5 shrink-0 uppercase tracking-wide ${t.tone}`}>
                        {t.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-lg border border-border bg-surface p-3">
                <p className="text-[10px] font-semibold flex items-center gap-1.5 mb-2">
                  <Sparkles size={11} className="text-muted-foreground" /> Recent Activity
                </p>
                <div className="space-y-1.5">
                  {[
                    { icon: CheckCircle2, label: "Verification completed — ABC Engineering Pvt Ltd" },
                    { icon: ClipboardList, label: "Bidder document uploaded — Sunrise Traders" },
                  ].map((a) => (
                    <div key={a.label} className="flex items-center gap-1.5 text-[10px]">
                      <a.icon size={10} className="text-success shrink-0" />
                      <span className="text-foreground/80 truncate">{a.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
