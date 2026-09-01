import { ArrowRight, FileSearch, Layers, ShieldCheck, FileBarChart2 } from "lucide-react";
import { Button, Logo } from "../components/kit";
import { LandingNavbar } from "../components/landing/LandingNavbar";
import { DashboardPreview } from "../components/landing/DashboardPreview";
import { ContactSection } from "../components/landing/ContactSection";
import { trustStatements } from "../components/landing/landingData";

const DEMO_MAILTO = "mailto:team.pramaan@gmail.com?subject=" + encodeURIComponent("Demo request — PRAMAAN");

const pills = [
  { icon: FileSearch, title: "AI Document Extraction", description: "Automatically extract bidder identity and registration data from uploaded documents." },
  { icon: Layers, title: "12 Verification Categories", description: "Udyam, GST, PAN, MCA21, EPFO, ESIC, NSIC, Startup India, OEM Auth, DigiLocker, Make in India, Blacklist." },
  { icon: ShieldCheck, title: "Simulated Registry Verification", description: "Cross-checks every claim against mock government registry records — no live portals are queried." },
  { icon: FileBarChart2, title: "Compliance Score & Risk Level", description: "A transparent, explainable score with Low / Medium / High / Critical risk flags for every bidder." },
];

const footerLinks = {
  Company: [{ label: "About", id: "company" }, { label: "Contact", id: "contact" }],
  Product: [{ label: "Solutions" }, { label: "Features" }, { label: "How It Works" }],
  Resources: [{ label: "Documentation" }, { label: "FAQ" }, { label: "Release Notes" }],
};

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export default function Landing() {
  return (
    <div className="min-h-screen bg-background">
      <LandingNavbar />

      {/* Hero */}
      <section className="relative overflow-hidden">
        {/* Soft blue gradient wash, not a hard block -- keeps the premium
            "white background, subtle depth" feel from the brief rather
            than a saturated hero banner. */}
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_80%_50%_at_50%_-10%,hsl(var(--primary)/0.10),transparent)]"
        />
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 pb-10 lg:pt-10 lg:pb-12 grid lg:grid-cols-2 gap-10 items-start">
          <div>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-xs font-medium text-primary">
              <span className="w-1.5 h-1.5 rounded-full bg-primary" />
              AI-Powered Bid Compliance Verification
            </span>

            <h1 className="mt-4 text-4xl sm:text-5xl lg:text-[3.3rem] font-bold tracking-tight leading-[1.06] text-foreground">
              From Documents
              <br />
              to Decisions.
              <br />
              <span className="text-primary">Verify. Score. Decide.</span>
            </h1>

            <p className="mt-4 text-base text-muted-foreground leading-relaxed max-w-xl">
              PRAMAAN helps procurement officers verify bidder submissions against simulated government registries —
              Udyam, GST, PAN, MCA21, EPFO, ESIC, and more — with a transparent compliance score, risk level, and a
              fully auditable decision trail.
            </p>

            <div className="mt-6 flex flex-wrap items-center gap-3">
              <Button size="lg" onClick={() => (window.location.href = DEMO_MAILTO)} icon={<ArrowRight size={16} />}>
                Book a Demo
              </Button>
            </div>

            <p className="mt-4 text-xs text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1">
              <span>Simulated Government Registries</span>
              <span aria-hidden="true">•</span>
              <span>Explainable Verification</span>
              <span aria-hidden="true">•</span>
              <span>Built for Procurement Officers</span>
            </p>
          </div>

          {/* Plain top alignment (no sticky) -- sticky positioning let the
              card visually drift past its own row's bottom edge while
              scrolling and overlap the pills row beneath it. Static
              placement keeps it pinned to the top of the row, level with
              the headline, with no overlap risk. */}
          <div>
            <DashboardPreview />
          </div>

          {/* Full-width row, not confined to the half-width left column --
              spreading these horizontally across the whole page uses the
              space properly instead of a cramped 2x2 grid with empty
              space beside it. */}
          <div className="lg:col-span-2 grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {pills.map((pill) => (
              <div key={pill.title} className="flex items-start gap-3 rounded-xl border border-border bg-surface p-3.5 shadow-xs transition-shadow hover:shadow-elevated">
                <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
                  <pill.icon size={15} />
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-semibold tracking-tight">{pill.title}</p>
                  <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">{pill.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Trust row -- capability statements only, no fabricated metrics
          or customer logos (explicit constraint). */}
      <section id="features-anchor" className="border-y border-border bg-surface">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-7">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-6">
            {trustStatements.map((t) => (
              <div key={t.label} className="flex flex-col items-center text-center gap-2">
                <div className="w-10 h-10 rounded-full bg-primary/10 text-primary flex items-center justify-center">
                  <t.icon size={17} />
                </div>
                <p className="text-xs font-medium text-foreground/80 leading-snug">{t.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <ContactSection />

      {/* Footer */}
      <footer id="company" className="bg-background">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-14">
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-10">
            <div>
              <Logo size={22} />
              <p className="text-sm text-muted-foreground mt-3 leading-relaxed max-w-xs">
                PRAMAAN is the bid compliance verification platform that helps procurement officers verify bidder
                submissions against simulated government registries, score compliance, and record auditable
                decisions with confidence.
              </p>
            </div>

            {Object.entries(footerLinks).map(([heading, links]) => (
              <div key={heading}>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">{heading}</p>
                <ul className="space-y-2">
                  {links.map((link) => (
                    <li key={link.label}>
                      {"id" in link && link.id ? (
                        <button
                          onClick={() => scrollToId(link.id!)}
                          className="text-sm text-foreground/75 hover:text-primary transition-colors"
                        >
                          {link.label}
                        </button>
                      ) : (
                        <span className="text-sm text-foreground/75">{link.label}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="mt-12 pt-6 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-4">
            <p className="text-xs text-muted-foreground">© 2026 PRAMAAN. All rights reserved.</p>
            <div className="flex items-center gap-5">
              <span className="text-xs text-muted-foreground">Privacy Policy</span>
              <span className="text-xs text-muted-foreground">Terms</span>
              <span className="text-xs text-muted-foreground">Security</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
