import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getCompany } from "../api/endpoints";
import { useAuth } from "../context/AuthContext";
import { Badge, Card, CardBody, Skeleton } from "../components/kit";
import { roleDescription } from "../lib/roleDescriptions";
import { Building2 } from "lucide-react";

// Profile -- a single, read-only identity card, built strictly from
// fields UserRead actually has: name, email, role, status, company_id,
// created_at. No avatar upload (no `avatar` field exists -- the initials
// circle below is a generated visual over real name text, same
// convention already used in Layout.tsx's account-menu trigger, not a
// stand-in for missing data), no department/designation/phone/timezone
// (none exist on the backend), and no edit affordance of any kind --
// there is no update-profile endpoint yet. This page describes the
// product as it exists today, not a mock-up of a future one.
export default function Profile() {
  const { user } = useAuth();
  const [companyName, setCompanyName] = useState<string | null>(null);
  const [loadingCompany, setLoadingCompany] = useState(true);

  useEffect(() => {
    if (!user?.company_id) {
      setLoadingCompany(false);
      return;
    }
    getCompany(user.company_id)
      .then((c) => setCompanyName(c.name))
      .catch(() => setCompanyName(null))
      .finally(() => setLoadingCompany(false));
  }, [user?.company_id]);

  if (!user) return null;

  const initial = user.name?.[0]?.toUpperCase() ?? "?";

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Profile</h1>
        <p className="text-sm text-muted-foreground mt-1">Your account identity within PRAMAAN.</p>
      </div>

      <Card>
        <CardBody className="space-y-6">
          <div className="flex items-center gap-4">
            <div
              aria-hidden="true"
              className="w-16 h-16 rounded-full bg-primary/10 text-primary flex items-center justify-center text-2xl font-semibold shrink-0"
            >
              {initial}
            </div>
            <div className="min-w-0">
              <p className="text-lg font-semibold truncate">{user.name}</p>
              <p className="text-sm text-muted-foreground truncate">{user.email}</p>
            </div>
          </div>

          <div className="grid sm:grid-cols-2 gap-5 pt-5 border-t border-border">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">Role</p>
              <Badge value={user.role} />
              <p className="text-xs text-muted-foreground mt-2 leading-relaxed">{roleDescription(user.role)}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">Account Status</p>
              <Badge value={user.status} withIcon />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">Organization</p>
              {loadingCompany ? (
                <Skeleton className="h-5 w-32" />
              ) : (
                <Link
                  to="/settings"
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-accent hover:underline"
                >
                  <Building2 size={14} />
                  {companyName ?? "—"}
                </Link>
              )}
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">Member Since</p>
              <p className="text-sm font-medium">{new Date(user.created_at).toLocaleDateString()}</p>
            </div>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
