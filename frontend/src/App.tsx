import { Navigate, Route, BrowserRouter, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import { ToastProvider } from "./context/ToastContext";
import { usePasteSanitizer } from "./lib/usePasteSanitizer";
import Layout from "./components/Layout";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import ActionCenter from "./pages/ActionCenter";
import Documents from "./pages/Documents";
import Capabilities from "./pages/Capabilities";
import TenderUpload from "./pages/TenderUpload";
import Missions from "./pages/Missions";
import Evaluation from "./pages/Evaluation";
import Profile from "./pages/Profile";
import Settings from "./pages/Settings";
import ProcurementsList from "./pages/sih/ProcurementsList";
import ProcurementSubmissions from "./pages/sih/ProcurementSubmissions";
import BidderVerification from "./pages/sih/BidderVerification";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
}

function AppRoutes() {
  const { isAuthenticated } = useAuth();

  return (
    <Routes>
      <Route path="/login" element={isAuthenticated ? <Navigate to="/" replace /> : <Login />} />
      {/* Public marketing landing page -- only reachable at "/" while
          signed out. Once authenticated, the second "/" route below
          (inside RequireAuth + Layout) takes over instead, so this
          doesn't touch any existing authenticated route or internal
          link -- every "/documents", "/tenders/new" etc. link in the
          app is untouched by this. */}
      {!isAuthenticated && <Route path="/" element={<Landing />} />}
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/action-center" element={<ActionCenter />} />
        <Route path="/documents" element={<Documents />} />
        <Route path="/capabilities" element={<Capabilities />} />
        <Route path="/tenders/new" element={<TenderUpload />} />
        <Route path="/missions" element={<Missions />} />
        <Route path="/missions/:missionId" element={<Evaluation />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/settings" element={<Settings />} />
        {/* SIH26100 -- Procurement Officer bidder-verification workflow.
            A separate sibling domain from Tender/Requirement/Mission above
            (see backend Phase 0/1/2 reports); nested routes mirror the
            product's own drill-down: Procurements -> Bidder Submissions ->
            Verification Dashboard. */}
        <Route path="/procurement-verification" element={<ProcurementsList />} />
        <Route path="/procurement-verification/:procurementId" element={<ProcurementSubmissions />} />
        <Route
          path="/procurement-verification/:procurementId/bidders/:submissionId"
          element={<BidderVerification />}
        />
        {/* Reports.tsx retired -- it was a strictly smaller, less capable
            duplicate view over the same list_missions() data Tender
            Workspace already fully contains (Tender Workspace already
            lists every non-archived mission at every status; Reports only
            ever showed the subset with a recommendation_id, with no
            actions beyond Open). Redirected rather than dropped through
            the catch-all so any existing bookmark or external link to
            /reports still lands somewhere useful instead of the
            dashboard. */}
        <Route path="/reports" element={<Navigate to="/missions" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  // App-wide: strips leading/trailing whitespace introduced by pasting
  // clipboard content (very commonly copied out of a tender PDF, which
  // often carries leading whitespace from list indentation) into any text
  // field, anywhere -- see usePasteSanitizer.ts's own docstring.
  usePasteSanitizer();

  return (
    <ThemeProvider>
      <ToastProvider>
        <BrowserRouter>
          <AuthProvider>
            <AppRoutes />
          </AuthProvider>
        </BrowserRouter>
      </ToastProvider>
    </ThemeProvider>
  );
}
