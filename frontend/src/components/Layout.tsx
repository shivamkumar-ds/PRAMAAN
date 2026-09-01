import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ChevronDown,
  FileSearch,
  FileText,
  History,
  LayoutDashboard,
  LogOut,
  Menu as MenuIcon,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  UserCircle,
  Users,
  X,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { cn } from "../lib/cn";
import { LiveClock, Logo, Menu, MenuDivider, MenuItem, Switch } from "./kit";

// PRAMAAN is the primary product experience -- the procurement-officer
// verification workflow (Procurements -> Bidders -> Verification
// Dashboard). PRAMAAN's own bidder-side self-assessment pages (Tender
// Workspace, Action Center, Capabilities, Documents, Upload Tender) are
// deliberately no longer linked from primary navigation: they still exist
// and still work (see App.tsx's routes, untouched), they're just not part
// of the PRAMAAN product surface a Procurement Officer should see. See the
// product-transformation report for the full PRAMAAN-surface classification.
const navItems = [{ to: "/", label: "Overview", icon: LayoutDashboard }, { to: "/procurement-verification", label: "Procurements", icon: ShieldCheck }];

// Visually present (per the redesign brief's sidebar density target) but
// genuinely not backed by a route yet -- rendered disabled with a "Soon"
// pill rather than either being hidden (which would look sparse next to
// the reference) or linking somewhere fake. The moment a real /bidders,
// /verification-queue, /findings, /reports (SIH), or /audit-trail route
// exists, move its entry up into navItems instead of adding a new list.
const comingSoonNavItems = [
  { label: "Bidders", icon: Users },
  { label: "Verification Queue", icon: FileSearch },
  { label: "Findings", icon: ShieldAlert },
  { label: "Reports", icon: FileText },
  { label: "Audit Trail", icon: History },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  const currentLabel =
    navItems.find((item) => (item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to)))
      ?.label ?? "PRAMAAN";

  return (
    <div className="min-h-screen flex bg-background">
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden animate-fade-in"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Always `fixed` (never `lg:static`) so `inset-y-0` actually pins it
          to the viewport height on every screen size -- see prior comment
          history for why. w-64 lg:w-64 keeps the sidebar inside the
          240-260px band the redesign brief asks for while fitting the
          denser nav + category list without text wrapping. */}
      <aside
        aria-label="Sidebar"
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-64 border-r border-border bg-surface flex flex-col shrink-0 transition-transform duration-200 ease-out",
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        )}
      >
        <div className="px-5 h-16 flex items-center justify-between gap-2 border-b border-border shrink-0">
          <Logo size={26} wordmarkClassName="text-[15px]" />
          <button
            onClick={() => setMobileOpen(false)}
            className="lg:hidden text-muted-foreground hover:text-foreground"
            aria-label="Close menu"
          >
            <X size={18} />
          </button>
        </div>

        <nav aria-label="Main navigation" className="flex-1 px-3 py-4 overflow-y-auto">
          <div className="space-y-0.5">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  cn(
                    "group flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-all duration-150",
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-surface-hover hover:text-foreground hover:translate-x-0.5"
                  )
                }
              >
                <item.icon size={16} strokeWidth={2} />
                {item.label}
              </NavLink>
            ))}

            {comingSoonNavItems.map((item) => (
              <div
                key={item.label}
                aria-disabled="true"
                title="Not available yet"
                className="flex items-center justify-between gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground/60 cursor-not-allowed select-none"
              >
                <span className="flex items-center gap-2.5">
                  <item.icon size={16} strokeWidth={2} />
                  {item.label}
                </span>
                <span className="text-[9px] font-semibold uppercase tracking-wide bg-muted text-muted-foreground rounded px-1.5 py-0.5 shrink-0">
                  Soon
                </span>
              </div>
            ))}
          </div>
        </nav>

        {/* Static, non-interactive -- there is no AI-assistant feature/
            endpoint in the product yet, so this deliberately makes no
            promises and calls nothing; it exists purely because the
            redesign brief's reference layout has this element and hiding
            it would look like a missing chunk of sidebar. */}
        <div className="p-3 shrink-0 border-t border-border">
          <div className="rounded-lg bg-primary/5 border border-primary/10 px-3 py-2.5 flex items-center gap-2.5 opacity-70 cursor-not-allowed" title="Coming soon">
            <Sparkles size={15} className="text-primary shrink-0" />
            <div className="min-w-0">
              <p className="text-xs font-semibold text-foreground truncate">AI Assistant</p>
              <p className="text-[10px] text-muted-foreground truncate">Coming soon</p>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col lg:ml-64">
        <header className="h-16 shrink-0 border-b border-border bg-surface flex items-center justify-between px-4 sm:px-6 lg:px-8 sticky top-0 z-30">
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={() => setMobileOpen(true)}
              className="lg:hidden text-muted-foreground hover:text-foreground shrink-0"
              aria-label="Open menu"
            >
              <MenuIcon size={20} />
            </button>
            <span className="text-base font-semibold tracking-tight text-foreground truncate">{currentLabel}</span>
          </div>

          <div className="flex items-center gap-4 sm:gap-5 shrink-0">
            <div className="hidden sm:flex items-center gap-2">
              <Switch checked={theme === "dark"} onChange={toggleTheme} label="Toggle dark mode" />
              <span className="text-xs text-muted-foreground">{theme === "dark" ? "Dark" : "Light"} mode</span>
            </div>

            <div className="hidden md:block h-8 w-px bg-border" />

            <LiveClock stacked className="hidden md:flex" />

            <div className="hidden md:block h-8 w-px bg-border" />

            <Menu
              label={`Account menu for ${user?.name ?? "current user"}`}
              trigger={
                <span className="flex items-center gap-2.5">
                  <div
                    aria-hidden="true"
                    className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center text-xs font-semibold shrink-0"
                  >
                    {user?.name?.[0]?.toUpperCase() ?? "?"}
                  </div>
                  <span className="hidden lg:block text-left leading-tight">
                    <span className="block text-sm font-medium">{user?.name}</span>
                    <span className="block text-xs text-muted-foreground capitalize">{user?.role?.replace(/_/g, " ")}</span>
                  </span>
                  <ChevronDown size={14} className="hidden lg:block text-muted-foreground" />
                </span>
              }
            >
              <div className="px-3.5 py-2 border-b border-border sm:hidden">
                <Switch checked={theme === "dark"} onChange={toggleTheme} label="Toggle dark mode" />
              </div>
              <MenuItem icon={<UserCircle size={15} />} onClick={() => navigate("/profile")}>
                Profile
              </MenuItem>
              <MenuItem icon={<Settings size={15} />} onClick={() => navigate("/settings")}>
                Settings
              </MenuItem>
              <MenuDivider />
              <MenuItem icon={<LogOut size={15} />} danger onClick={() => { logout(); navigate("/login"); }}>
                Log out
              </MenuItem>
            </Menu>
          </div>
        </header>

        <main aria-label={currentLabel} className="flex-1 min-w-0">
          <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-6 lg:py-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
