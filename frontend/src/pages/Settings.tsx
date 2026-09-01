import { useEffect, useState } from "react";
import { getCompany, updateCompany } from "../api/endpoints";
import { extractErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { useTheme } from "../context/ThemeContext";
import { Button, Card, CardBody, CardHeader, Input, Skeleton, Switch } from "../components/kit";
import type { CompanyRead } from "../api/types";
import { Building2, Info, Palette, Pencil } from "lucide-react";

// Settings -- three sections, each backed by something that actually
// exists today. No Security, Notifications, Billing, Integrations, or AI
// preferences: none of those have any backend support yet (no
// password-change endpoint, no notification system, no billing or API
// product, only one working AI provider), so they're not represented
// here at all -- not even as "Coming Soon" placeholders. This page
// describes the product as it exists, not a roadmap.
//
// Organization editing closes the gap this section itself used to
// document: "so that when a real PATCH /company endpoint exists, this
// same layout gains input elements instead of being rebuilt." That
// endpoint now exists (Administrator-only) -- see api/endpoints.ts's
// updateCompany() and the backend's require_administrator-gated
// PATCH /company/{id}. Registration Number stays permanently read-only
// (it's the tenant's legal/uniqueness identity, not an ordinary editable
// detail -- backend CompanyUpdate has no field for it at all, so this
// is describing a real contract limit, not a UI choice).
function OrganizationSection() {
  const { user } = useAuth();
  const { notify } = useToast();
  const [company, setCompany] = useState<CompanyRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [draftIndustry, setDraftIndustry] = useState("");
  const [draftCountry, setDraftCountry] = useState("");

  const canEdit = user?.role === "administrator";

  const load = () => {
    if (!user?.company_id) {
      setLoading(false);
      return;
    }
    return getCompany(user.company_id)
      .then(setCompany)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.company_id]);

  const startEditing = () => {
    if (!company) return;
    setDraftName(company.name);
    setDraftIndustry(company.industry ?? "");
    setDraftCountry(company.country ?? "");
    setEditing(true);
  };

  const handleSave = async () => {
    if (!company || !draftName.trim()) {
      notify("error", "Organization name can't be empty.");
      return;
    }
    setSaving(true);
    try {
      const updated = await updateCompany(company.id, {
        name: draftName.trim(),
        industry: draftIndustry.trim() || null,
        country: draftCountry.trim() || null,
      });
      setCompany(updated);
      setEditing(false);
      notify("success", "Organization details updated.");
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Building2 size={15} className="text-muted-foreground" />
            Organization
          </span>
        }
        description="Your company's registered details."
        action={
          canEdit && company && !editing && !loading ? (
            <Button variant="outline" size="sm" icon={<Pencil size={14} />} onClick={startEditing}>
              Edit
            </Button>
          ) : undefined
        }
      />
      <CardBody>
        {loading ? (
          <div className="grid sm:grid-cols-2 gap-5">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : !company ? (
          <p className="text-sm text-muted-foreground">Organization details are unavailable.</p>
        ) : editing ? (
          <div className="space-y-4">
            <div className="grid sm:grid-cols-2 gap-5">
              <Input label="Name" value={draftName} onChange={(e) => setDraftName(e.target.value)} />
              <Input label="Industry" value={draftIndustry} onChange={(e) => setDraftIndustry(e.target.value)} />
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                  Registration Number
                </p>
                <p className="text-sm font-medium">{company.registration_number}</p>
                <p className="text-xs text-muted-foreground mt-1">Not editable -- your organization's fixed legal identifier.</p>
              </div>
              <Input label="Country" value={draftCountry} onChange={(e) => setDraftCountry(e.target.value)} />
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={handleSave} loading={saving}>
                Save Changes
              </Button>
              <Button size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saving}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 gap-5">
            {(
              [
                { label: "Name", value: company.name },
                { label: "Industry", value: company.industry },
                { label: "Registration Number", value: company.registration_number },
                { label: "Country", value: company.country },
              ] as { label: string; value: string | null | undefined }[]
            ).map((f) => (
              <div key={f.label}>
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">{f.label}</p>
                <p className="text-sm font-medium">{f.value ?? "—"}</p>
              </div>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function AppearanceSection() {
  const { theme, toggleTheme } = useTheme();
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Palette size={15} className="text-muted-foreground" />
            Appearance
          </span>
        }
        description="Applies to this browser."
      />
      <CardBody className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">Dark mode</p>
          <p className="text-xs text-muted-foreground mt-0.5">Currently {theme === "dark" ? "on" : "off"}.</p>
        </div>
        <Switch checked={theme === "dark"} onChange={toggleTheme} label="Toggle dark mode" />
      </CardBody>
    </Card>
  );
}

function AboutSection() {
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Info size={15} className="text-muted-foreground" />
            About
          </span>
        }
      />
      <CardBody className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">PRAMAAN</span>
        <span className="font-medium tabular-nums">v{__APP_VERSION__}</span>
      </CardBody>
    </Card>
  );
}

export default function Settings() {
  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">Organization details and app preferences.</p>
      </div>

      <div className="space-y-6">
        <AppearanceSection />
        <OrganizationSection />
        <AboutSection />
      </div>
    </div>
  );
}
