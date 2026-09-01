import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CalendarDays, ChevronDown, KeyRound, Menu as MenuIcon, X } from "lucide-react";
import { Button, Logo } from "../kit";
import { cn } from "../../lib/cn";
import { SolutionsMegaPanel } from "./SolutionsMegaPanel";
import { FeaturesMegaPanel } from "./FeaturesMegaPanel";
import { HowItWorksMegaPanel } from "./HowItWorksMegaPanel";

// Trimmed down per explicit founder direction: only Solutions, Features,
// How It Works, Contact -- Pricing (never had a real section behind it,
// only scrolled to Contact), Industries, Resources, and About (previously
// in the nav) are gone. The data arrays for Industries/Resources still
// exist in landingData.ts in case they come back later, they're just not
// imported/rendered here anymore.
type DropdownKey = "solutions" | "features" | "how-it-works";

const DROPDOWN_ITEMS: { key: DropdownKey; label: string }[] = [
  { key: "solutions", label: "Solutions" },
  { key: "features", label: "Features" },
  { key: "how-it-works", label: "How It Works" },
];

const DEMO_MAILTO =
  "mailto:team.pramaan@gmail.com?subject=" + encodeURIComponent("Demo request — PRAMAAN");

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function MenuPanel({ activeKey }: { activeKey: DropdownKey }) {
  if (activeKey === "solutions") {
    return <SolutionsMegaPanel />;
  }

  if (activeKey === "features") {
    return <FeaturesMegaPanel />;
  }

  // how-it-works
  return <HowItWorksMegaPanel />;
}

export function LandingNavbar() {
  const [activeKey, setActiveKey] = useState<DropdownKey | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setActiveKey(null);
    }
    function onClickOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setActiveKey(null);
    }
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onClickOutside);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onClickOutside);
    };
  }, []);

  function toggle(key: DropdownKey) {
    setActiveKey((cur) => (cur === key ? null : key));
  }

  return (
    <div ref={rootRef} className="sticky top-0 z-50 bg-background/90 backdrop-blur border-b border-border">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        <Link to="/" className="flex flex-col shrink-0" onClick={() => setActiveKey(null)}>
          <Logo size={24} wordmarkClassName="text-[15px]" />
          <span className="text-[10px] text-muted-foreground pl-8 -mt-0.5">From Documents to Decisions.</span>
        </Link>

        <nav className="hidden lg:flex items-center gap-1" aria-label="Primary">
          {DROPDOWN_ITEMS.map((item) => (
            <button
              key={item.key}
              onClick={() => toggle(item.key)}
              className={cn(
                "flex items-center gap-1 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                activeKey === item.key
                  ? "text-primary bg-primary/10"
                  : "text-foreground/80 hover:text-foreground hover:bg-surface-hover"
              )}
              aria-expanded={activeKey === item.key}
            >
              {item.label}
              <ChevronDown size={13} className={cn("transition-transform", activeKey === item.key && "rotate-180")} />
            </button>
          ))}
          <button
            onClick={() => {
              setActiveKey(null);
              scrollToId("contact");
            }}
            className="rounded-md px-3 py-2 text-sm font-medium text-foreground/80 hover:text-foreground hover:bg-surface-hover"
          >
            Contact
          </button>
        </nav>

        <div className="hidden lg:flex items-center gap-2.5 shrink-0">
          <Link to="/login">
            <Button variant="outline" size="md" icon={<KeyRound size={14} />}>
              Login
              <ChevronDown size={12} className="text-muted-foreground" />
            </Button>
          </Link>
          <Button size="md" icon={<CalendarDays size={14} />} onClick={() => (window.location.href = DEMO_MAILTO)}>
            Book A Demo
          </Button>
        </div>

        <button
          className="lg:hidden text-foreground"
          onClick={() => setMobileOpen((v) => !v)}
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
        >
          {mobileOpen ? <X size={20} /> : <MenuIcon size={20} />}
        </button>
      </div>

      {activeKey && (
        // Panel is inside the sticky navbar, so if its content (e.g. the
        // 8-card Solutions grid) is taller than the viewport, the whole
        // sticky box grows past the fold and page scroll appears "stuck"
        // until you scroll past its full height. Capping it to the
        // remaining viewport height (100vh - navbar height) and scrolling
        // internally keeps normal page scroll working at all times.
        <div className="hidden lg:block border-t border-border bg-background animate-fade-in max-h-[calc(100vh-4rem)] overflow-y-auto">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
            <MenuPanel activeKey={activeKey} />
          </div>
        </div>
      )}

      {mobileOpen && (
        <div className="lg:hidden border-t border-border bg-background px-4 py-4 space-y-1 animate-fade-in max-h-[calc(100vh-4rem)] overflow-y-auto">
          {DROPDOWN_ITEMS.map((item) => (
            <div key={item.key}>
              <button
                onClick={() => toggle(item.key)}
                className="w-full flex items-center justify-between rounded-md px-3 py-2.5 text-sm font-medium text-foreground/90"
              >
                {item.label}
                <ChevronDown size={14} className={cn("transition-transform", activeKey === item.key && "rotate-180")} />
              </button>
              {activeKey === item.key && (
                <div className="px-3 pb-3">
                  <MenuPanel activeKey={item.key} />
                </div>
              )}
            </div>
          ))}
          <button
            onClick={() => {
              scrollToId("contact");
              setMobileOpen(false);
            }}
            className="w-full text-left rounded-md px-3 py-2.5 text-sm font-medium text-foreground/90"
          >
            Contact
          </button>
          <div className="flex items-center gap-2.5 pt-3">
            <Link to="/login" className="flex-1">
              <Button variant="outline" size="md" className="w-full">
                Login
              </Button>
            </Link>
            <Button size="md" className="flex-1" onClick={() => (window.location.href = DEMO_MAILTO)}>
              Book A Demo
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
