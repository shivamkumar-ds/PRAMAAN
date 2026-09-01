import { CheckCircle2, FileUp, Sparkles } from "lucide-react";
import { cn } from "../../lib/cn";
import { processSteps, processTrustPoints } from "./landingData";

function PreviewCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-3 text-left min-w-0">
      <p className="text-[10px] font-semibold text-foreground/90 mb-2 truncate">{title}</p>
      {children}
    </div>
  );
}

function PdfBadge() {
  return <span className="text-[8px] font-semibold text-danger bg-danger-soft rounded px-1 py-0.5 shrink-0">PDF</span>;
}

export function HowItWorksMegaPanel() {
  return (
    <div>
      <div className="text-center mb-8">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-primary">
          <Sparkles size={12} />
          Our Process
        </span>
        <h2 className="mt-4 text-2xl lg:text-3xl font-bold tracking-tight leading-[1.1] text-foreground">
          From Bidder Documents to Verified Decisions
        </h2>
        <p className="mt-3 text-sm text-muted-foreground leading-relaxed max-w-xl mx-auto">
          PRAMAAN follows a clear, evidence-backed workflow to verify bidder submissions against simulated
          government registries and support a confident, auditable procurement decision.
        </p>
      </div>

      {/* 7-step timeline */}
      <div className="relative mb-6">
        <div className="hidden lg:block absolute top-[22px] left-[7%] right-[7%] border-t-2 border-dashed border-border" />
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-x-3 gap-y-6 relative">
          {processSteps.map((s) => (
            <div key={s.step} className="flex flex-col items-center text-center">
              <div className="w-11 h-11 rounded-full bg-background border-2 border-primary/25 text-primary font-bold flex items-center justify-center text-sm mb-3 relative z-10">
                {s.step}
              </div>
              <div className={cn("w-11 h-11 rounded-xl flex items-center justify-center mb-3", s.color.bg, s.color.text)}>
                <s.icon size={19} />
              </div>
              <p className="text-xs font-semibold tracking-tight leading-snug">{s.title}</p>
              <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed">{s.description}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Realistic (illustrative, not live) preview of each step's screen */}
      <div className="hidden lg:grid grid-cols-7 gap-3 mb-8">
        <PreviewCard title="Procurement">
          <div className="flex items-center gap-1.5 text-[9px] text-foreground/80 mb-2">
            <FileUp size={10} className="text-primary shrink-0" />
            <span className="truncate flex-1">GeM Pipeline Maintenance</span>
          </div>
          <p className="text-[8px] text-muted-foreground mb-2">CPCL</p>
          <div className="space-y-1.5">
            {["ABC Engineering Pvt Ltd", "Sunrise Traders", "Larsen Pipeline Systems"].map((b) => (
              <div key={b} className="flex items-center gap-1.5 text-[9px] text-foreground/80">
                <CheckCircle2 size={10} className="text-success shrink-0" />
                <span className="truncate flex-1">{b}</span>
              </div>
            ))}
          </div>
        </PreviewCard>

        <PreviewCard title="Bidder Documents">
          <div className="space-y-1.5">
            {["Udyam Certificate.pdf", "GST Certificate.pdf", "PAN Card.pdf", "MCA21 Extract.pdf"].map((f) => (
              <div key={f} className="flex items-center gap-1.5 text-[9px] text-foreground/80">
                <FileUp size={10} className="text-primary shrink-0" />
                <span className="truncate flex-1">{f}</span>
                <PdfBadge />
              </div>
            ))}
            <div className="mt-2 rounded-md border border-dashed border-border text-center py-1.5 text-[9px] text-muted-foreground">
              Upload more documents
            </div>
          </div>
        </PreviewCard>

        <PreviewCard title="Extracted Data">
          <div className="space-y-1.5">
            {["Udyam Number", "GSTIN", "PAN", "CIN", "EPFO ID"].map((label) => (
              <div key={label} className="flex items-center gap-1.5 text-[9px]">
                <CheckCircle2 size={10} className="text-success shrink-0" />
                <span className="text-foreground/80 truncate flex-1">{label}</span>
                <span className="text-muted-foreground font-medium">✓</span>
              </div>
            ))}
          </div>
        </PreviewCard>

        <PreviewCard title="Officer Review">
          <div className="flex items-center gap-1.5 text-[9px] text-foreground/80 mb-2">
            <FileUp size={10} className="text-violet-600 shrink-0" />
            <span className="truncate flex-1">ABC_Engineering_GST.pdf</span>
          </div>
          <span className="inline-block text-[8px] font-semibold text-success bg-success-soft rounded px-1 py-0.5 mb-2">
            CONFIRMED
          </span>
          <div className="rounded-md border border-border bg-background p-2 space-y-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-1 rounded-full bg-muted" style={{ width: `${85 - i * 10}%` }} />
            ))}
          </div>
        </PreviewCard>

        <PreviewCard title="Verification Results">
          <div className="space-y-1.5">
            {[
              ["Udyam", "Verified", "text-success bg-success-soft"],
              ["GST", "Verified", "text-success bg-success-soft"],
              ["PAN", "Verified", "text-success bg-success-soft"],
              ["MCA21", "Verified", "text-success bg-success-soft"],
              ["EPFO", "Mismatch", "text-warning bg-warning-soft"],
            ].map(([label, status, cls]) => (
              <div key={label} className="flex items-center justify-between text-[9px]">
                <span className="text-foreground/80 truncate">{label}</span>
                <span className={cn("text-[8px] font-medium rounded px-1 py-0.5 shrink-0", cls)}>{status}</span>
              </div>
            ))}
          </div>
        </PreviewCard>

        <PreviewCard title="Compliance Score">
          <div className="relative w-14 h-14 mx-auto mb-2">
            <div
              className="w-14 h-14 rounded-full"
              style={{
                background:
                  "conic-gradient(hsl(var(--success)) 0% 75%, hsl(var(--warning)) 75% 92%, hsl(var(--danger)) 92% 100%)",
              }}
            />
            <div className="absolute inset-[4px] rounded-full bg-surface flex items-center justify-center">
              <span className="text-[10px] font-bold text-success">75%</span>
            </div>
          </div>
          <p className="text-center text-[8px] text-muted-foreground mb-2">Compliance Score</p>
          <div className="space-y-1 text-[9px]">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-success shrink-0" />
              <span className="text-foreground/80 flex-1">Verified</span>
              <span className="text-muted-foreground">75%</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-warning shrink-0" />
              <span className="text-foreground/80 flex-1">Mismatch</span>
              <span className="text-muted-foreground">17%</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-danger shrink-0" />
              <span className="text-foreground/80 flex-1">Critical</span>
              <span className="text-muted-foreground">8%</span>
            </div>
          </div>
        </PreviewCard>

        <PreviewCard title="Officer Decision">
          <div className="rounded-md bg-success-soft py-2 text-center mb-2">
            <p className="text-[11px] font-bold text-success leading-tight">Approved</p>
            <p className="text-[8px] text-success/80 mt-1">Low Risk</p>
          </div>
          <div className="space-y-1 text-[9px] font-medium text-primary">
            <p>Add Decision Note</p>
            <p>View Audit Trail</p>
          </div>
        </PreviewCard>
      </div>

      {/* Trust row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 pt-6 border-t border-border">
        {processTrustPoints.map((t) => (
          <div key={t.title} className="flex items-start gap-2.5">
            <div className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center shrink-0">
              <t.icon size={14} />
            </div>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-foreground">{t.title}</p>
              <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">{t.description}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
