import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { googleLogin, login as loginRequest, registerCompany } from "../api/endpoints";
import { extractErrorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { Button, Input, Logo } from "../components/kit";
import { ArrowLeft, Eye, EyeOff, Lock, Mail, ShieldCheck, Sparkles, Users } from "lucide-react";

// Set by whoever creates the OAuth Client ID in Google Cloud Console
// (APIs & Services -> Credentials) -- unset in every environment until
// then, which is exactly when the graceful fallback below applies. Not a
// secret: this ID is meant to be public, embedded in frontend code.
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;

// Minimal shape of the bits of Google Identity Services this page actually
// calls -- avoids pulling in a full @types/google.accounts dependency for
// three method calls.
interface GoogleIdentityServices {
  accounts: {
    id: {
      initialize: (config: { client_id: string; callback: (response: { credential: string }) => void }) => void;
      renderButton: (parent: HTMLElement, options: { theme: string; size: string; width: number; text: string }) => void;
    };
  };
}
declare global {
  interface Window {
    google?: GoogleIdentityServices;
  }
}

const FORGOT_PASSWORD_MAILTO =
  "mailto:team.pramaan@gmail.com?subject=" + encodeURIComponent("Password reset request — PRAMAAN");

// Standard 4-color "G" mark -- lucide-react has no Google logo, so this is
// a small inline SVG rather than pulling in a whole icon-pack dependency.
function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#FFC107"
        d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 8 3l5.7-5.7C34.6 6 29.6 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.7-.4-3.5Z"
      />
      <path
        fill="#FF3D00"
        d="m6.3 14.7 6.6 4.8C14.6 15.9 18.9 13 24 13c3.1 0 5.8 1.1 8 3l5.7-5.7C34.6 6 29.6 4 24 4c-7.4 0-13.8 4.2-17.1 10.3Z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.5 0 10.4-1.9 14.3-5.1l-6.6-5.6C29.6 34.9 26.9 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.2 39.7 16 44 24 44Z"
      />
      <path
        fill="#1976D2"
        d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.2 4.2-4 5.6l6.6 5.6C41.6 36 44 30.7 44 24c0-1.3-.1-2.7-.4-3.5Z"
      />
    </svg>
  );
}

// Honest, already-established claims restated as short cards -- no new
// capabilities invented for this page.
const loginHighlights = [
  {
    icon: ShieldCheck,
    color: { bg: "bg-blue-50", text: "text-blue-600" },
    title: "Secure & Private",
    description: "Your data is access-scoped to your company and never shared.",
  },
  {
    icon: Sparkles,
    color: { bg: "bg-emerald-50", text: "text-emerald-600" },
    title: "AI-Powered Extraction",
    description: "Extract and normalize bidder documents automatically — always reviewed by an officer before it counts.",
  },
  {
    icon: Users,
    color: { bg: "bg-violet-50", text: "text-violet-600" },
    title: "Built for Procurement Officers",
    description: "Verify bidder submissions against simulated government registries with confidence.",
  },
];

export default function Login() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showAdminPassword, setShowAdminPassword] = useState(false);
  const { login } = useAuth();
  const { notify } = useToast();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [companyName, setCompanyName] = useState("");
  const [registrationNumber, setRegistrationNumber] = useState("");
  const [industry, setIndustry] = useState("");
  const [country, setCountry] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");

  // Google Sign-In: only wired up when GOOGLE_CLIENT_ID is actually
  // configured (see the module-level comment above). Until then, the
  // button below keeps its existing "coming soon" behavior unchanged --
  // this never breaks local development or a deploy that hasn't set up
  // Google Cloud Console credentials yet.
  const googleButtonRef = useRef<HTMLDivElement>(null);

  const handleGoogleCredential = async (response: { credential: string }) => {
    setLoading(true);
    try {
      const res = await googleLogin({ id_token: response.credential });
      login(res.access_token, res.user);
      navigate("/");
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || mode !== "login") return;

    let cancelled = false;

    const render = () => {
      if (cancelled || !window.google || !googleButtonRef.current) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (response) => void handleGoogleCredential(response),
      });
      googleButtonRef.current.innerHTML = "";
      window.google.accounts.id.renderButton(googleButtonRef.current, {
        theme: "outline",
        size: "large",
        width: 400,
        text: "signin_with",
      });
    };

    if (window.google) {
      render();
      return;
    }

    // Loaded once and reused on later mounts -- Google's own script is
    // idempotent about being included twice, but this avoids the network
    // request and a flash of the fallback button on every mode toggle.
    const existing = document.getElementById("google-identity-services");
    if (existing) {
      existing.addEventListener("load", render, { once: true });
      return () => existing.removeEventListener("load", render);
    }

    const script = document.createElement("script");
    script.id = "google-identity-services";
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = render;
    document.head.appendChild(script);

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- handleGoogleCredential is stable enough for this effect's purpose; re-running it isn't the intent of remounting the button.
  }, [mode]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await loginRequest({ email, password });
      login(res.access_token, res.user);
      navigate("/");
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await registerCompany({
        company_name: companyName,
        registration_number: registrationNumber,
        industry: industry || null,
        country: country || null,
        admin_name: adminName,
        admin_email: adminEmail,
        admin_password: adminPassword,
      });
      login(res.access_token, res.user);
      navigate("/");
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Top bar */}
      <header className="border-b border-border shrink-0">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link to="/">
            <Logo size={24} />
          </Link>
          <Link
            to="/"
            className="text-sm font-medium text-primary inline-flex items-center gap-1.5 hover:underline"
          >
            <ArrowLeft size={14} />
            Back to Home
          </Link>
        </div>
      </header>

      <div className="flex-1 relative overflow-hidden">
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_60%_50%_at_15%_25%,hsl(var(--primary)/0.08),transparent)]"
        />
        {/* No dashboard mockup on this page -- the homepage already shows
            the real product; this side just needs to sell the "why," then
            get out of the way of the form. items-center (not items-start)
            keeps the shorter left column vertically centered against the
            auth card now that the mockup is gone, rather than pinned to
            the top with a growing gap beneath it. */}
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10 lg:py-14 grid lg:grid-cols-[1.1fr_1fr] gap-12 items-center">
          {/* Left: pitch */}
          <div className="hidden lg:block">
            <h1 className="font-display text-4xl font-bold tracking-tight text-foreground">
              {mode === "login" ? "Welcome Back!" : "Get Started"}
            </h1>
            <p className="mt-2 text-base text-muted-foreground">
              {mode === "login" ? "Sign in to PRAMAAN" : "Register your organization to get started"}
            </p>

            <div className="mt-10 space-y-6">
              {loginHighlights.map((h) => (
                <div key={h.title} className="flex items-start gap-3.5">
                  <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${h.color.bg} ${h.color.text}`}>
                    <h.icon size={18} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-foreground">{h.title}</p>
                    <p className="text-sm text-muted-foreground mt-0.5">{h.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right: auth card */}
          <div className="w-full max-w-md lg:ml-auto">
            <div className="rounded-2xl border border-border bg-surface shadow-elevated p-6 lg:p-8">
              <div className="lg:hidden flex justify-center mb-6">
                <Logo size={22} />
              </div>

              <h2 className="font-display text-2xl font-bold text-center tracking-tight text-foreground">
                {mode === "login" ? "Login" : "Create your workspace"}
              </h2>
              <p className="text-sm text-muted-foreground text-center mt-1 mb-6">
                {mode === "login" ? "Enter your credentials to access your account" : "Register your company to get started."}
              </p>

              {mode === "login" ? (
                <form onSubmit={handleLogin} className="space-y-4">
                  <Input
                    label="Email Address"
                    type="email"
                    required
                    icon={Mail}
                    placeholder="Enter your email address"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                  <Input
                    label="Password"
                    type={showPassword ? "text" : "password"}
                    required
                    icon={Lock}
                    placeholder="Enter your password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    trailing={
                      <button
                        type="button"
                        onClick={() => setShowPassword((v) => !v)}
                        className="text-muted-foreground hover:text-foreground"
                        aria-label={showPassword ? "Hide password" : "Show password"}
                      >
                        {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                    }
                  />

                  <div className="flex justify-end">
                    <a href={FORGOT_PASSWORD_MAILTO} className="text-xs font-medium text-primary hover:underline">
                      Forgot Password?
                    </a>
                  </div>

                  <Button type="submit" loading={loading} className="w-full" size="lg">
                    Sign In
                  </Button>

                  <div className="flex items-center gap-3 py-1">
                    <div className="h-px flex-1 bg-border" />
                    <span className="text-xs text-muted-foreground">OR</span>
                    <div className="h-px flex-1 bg-border" />
                  </div>

                  {GOOGLE_CLIENT_ID ? (
                    // Google's own rendered button -- required by their
                    // terms for the One Tap/GIS flow (a custom button
                    // triggering the same flow isn't a supported
                    // integration). Centered via flex since it sizes
                    // itself rather than filling the container.
                    <div className="flex justify-center" ref={googleButtonRef} />
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      size="lg"
                      className="w-full"
                      onClick={() => notify("info", "Google sign-in is coming soon.")}
                      icon={<GoogleIcon />}
                    >
                      Sign in with Google
                    </Button>
                  )}
                </form>
              ) : (
                <form onSubmit={handleRegister} className="space-y-3">
                  <Input label="Company Name" required value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
                  <Input
                    label="Registration Number"
                    required
                    value={registrationNumber}
                    onChange={(e) => setRegistrationNumber(e.target.value)}
                  />
                  <div className="grid grid-cols-2 gap-3">
                    <Input label="Industry" value={industry} onChange={(e) => setIndustry(e.target.value)} />
                    <Input label="Country" value={country} onChange={(e) => setCountry(e.target.value)} />
                  </div>
                  <Input label="Admin Name" required value={adminName} onChange={(e) => setAdminName(e.target.value)} />
                  <Input
                    label="Admin Email"
                    type="email"
                    required
                    value={adminEmail}
                    onChange={(e) => setAdminEmail(e.target.value)}
                  />
                  <Input
                    label="Admin Password"
                    type={showAdminPassword ? "text" : "password"}
                    required
                    minLength={8}
                    value={adminPassword}
                    onChange={(e) => setAdminPassword(e.target.value)}
                    trailing={
                      <button
                        type="button"
                        onClick={() => setShowAdminPassword((v) => !v)}
                        className="text-muted-foreground hover:text-foreground"
                        aria-label={showAdminPassword ? "Hide password" : "Show password"}
                      >
                        {showAdminPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                    }
                  />
                  <Button type="submit" loading={loading} className="w-full" size="lg">
                    Create workspace
                  </Button>
                </form>
              )}

              <p className="text-sm text-center text-muted-foreground mt-6">
                {mode === "login" ? "New to PRAMAAN? " : "Already registered? "}
                <button
                  onClick={() => setMode(mode === "login" ? "register" : "login")}
                  className="text-primary font-medium hover:underline"
                >
                  {mode === "login" ? "Register your organization" : "Sign in"}
                </button>
              </p>
            </div>
          </div>
        </div>
      </div>

      <footer className="shrink-0 py-6">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <p className="text-xs text-muted-foreground">© 2026 PRAMAAN. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}
