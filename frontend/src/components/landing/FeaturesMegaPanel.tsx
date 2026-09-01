import { useMemo, useState } from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import { cn } from "../../lib/cn";
import { featureCategories, features } from "./landingData";

export function FeaturesMegaPanel() {
  const [expanded, setExpanded] = useState<number | null>(null);
  const [activeCategory, setActiveCategory] = useState<(typeof featureCategories)[number]>("All Features");

  const visibleCards = useMemo(
    () => (activeCategory === "All Features" ? features : features.filter((c) => c.category === activeCategory)),
    [activeCategory]
  );

  return (
    <div>
      {/* Intro block -- centered, matching Solutions/How It Works */}
      <div className="text-center mb-8">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-primary">
          <Sparkles size={12} />
          Powerful features, purpose-built for procurement officers
        </span>
        <h2 className="mt-4 text-2xl lg:text-3xl font-bold tracking-tight leading-[1.1] text-foreground">
          Everything You Need to Verify Bidders with Confidence.
        </h2>
        <p className="mt-3 text-sm text-muted-foreground leading-relaxed max-w-xl mx-auto">
          PRAMAAN brings together AI document extraction, simulated government registry verification, compliance
          scoring, and officer decision workflows in a single platform designed for procurement officers.
        </p>
      </div>

      {/* Category filter */}
      <div className="flex flex-wrap items-center justify-center gap-2 mb-6">
        {featureCategories.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={cn(
              "rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors border",
              activeCategory === cat
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-surface text-foreground/70 border-border hover:bg-surface-hover"
            )}
          >
            {cat}
          </button>
        ))}
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {visibleCards.map((card, i) => {
          const isOpen = expanded === i;
          return (
            <div
              key={card.title}
              className="rounded-xl border border-border bg-surface p-4 transition-shadow hover:shadow-elevated"
            >
              <div className={cn("w-10 h-10 rounded-lg flex items-center justify-center mb-3", card.color.bg, card.color.text)}>
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
    </div>
  );
}
