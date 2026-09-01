import { useState } from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import { cn } from "../../lib/cn";
import { solutionVerticals } from "./landingData";

const DEMO_MAILTO = "mailto:team.pramaan@gmail.com?subject=" + encodeURIComponent("Demo request — PRAMAAN");

export function SolutionsMegaPanel() {
  const [expanded, setExpanded] = useState<number | null>(null);

  return (
    <div>
      <div className="text-center mb-8">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-primary">
          <Sparkles size={12} />
          Built for every procurement office
        </span>
        <h2 className="mt-4 text-2xl lg:text-3xl font-bold tracking-tight leading-[1.1] text-foreground">
          Solutions That Fit the Way You Work
        </h2>
        <p className="mt-3 text-sm text-muted-foreground leading-relaxed max-w-xl mx-auto">
          PRAMAAN adapts to your organization type, your team size, and your procurement complexity — helping you
          verify bidders with clarity and confidence.
        </p>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {solutionVerticals.map((card, i) => {
          const isOpen = expanded === i;
          return (
            <div
              key={card.title}
              className="rounded-xl border border-border bg-surface p-4 transition-shadow hover:shadow-elevated"
            >
              <div className="w-10 h-10 rounded-lg bg-primary/10 text-primary flex items-center justify-center mb-3">
                <card.icon size={17} />
              </div>
              <p className="text-sm font-semibold tracking-tight leading-snug">{card.title}</p>
              <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">{card.description}</p>
              <button
                onClick={() => setExpanded(isOpen ? null : i)}
                className="text-xs font-semibold text-primary mt-3 inline-flex items-center gap-1 hover:underline"
                aria-expanded={isOpen}
              >
                Learn more
                <ArrowRight size={12} className={cn("transition-transform", isOpen && "translate-x-0.5")} />
              </button>
              {isOpen && (
                <ul className="mt-3 pt-3 border-t border-border space-y-1.5 animate-fade-in">
                  {card.details.map((d) => (
                    <li key={d} className="text-xs text-muted-foreground leading-relaxed flex gap-2">
                      <span className="text-primary shrink-0">•</span>
                      {d}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-4 rounded-xl bg-primary/5 border border-primary/15 px-5 py-4 flex flex-col sm:flex-row items-center justify-center gap-4 text-center sm:text-left">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-primary/10 text-primary flex items-center justify-center shrink-0">
            <Sparkles size={15} />
          </div>
          <p className="text-sm text-foreground">
            <span className="font-semibold">Not sure where you fit?</span>{" "}
            <span className="text-muted-foreground">PRAMAAN is flexible and adapts to your unique procurement process.</span>
          </p>
        </div>
        <a
          href={DEMO_MAILTO}
          className="text-sm font-semibold text-primary inline-flex items-center gap-1 hover:underline shrink-0"
        >
          Talk to our experts
          <ArrowRight size={14} />
        </a>
      </div>
    </div>
  );
}
