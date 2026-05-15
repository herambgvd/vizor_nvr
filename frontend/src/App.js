// =============================================================================
// GVD Pro — Main Application Entry Point
// =============================================================================

import React, { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import ErrorBoundary from "./components/ErrorBoundary";
import { Toaster } from "./components/ui/sonner";
import Layout from "./pages/Layout";
import "./App.css";

// Lazy-loaded pages
const Login = lazy(() => import("./pages/Login"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Cameras = lazy(() => import("./pages/Cameras"));
const CameraDetailLayout = lazy(() =>
  import("./pages/camera-detail/CameraDetailLayout"),
);
const CameraDetailLive = lazy(() =>
  import("./pages/camera-detail/LiveViewPage"),
);
const CameraDetailRecordings = lazy(() =>
  import("./pages/camera-detail/RecordingsPage"),
);
const CameraDetailOnvif = lazy(() =>
  import("./pages/camera-detail/OnvifPage"),
);
const CameraDetailSettings = lazy(() =>
  import("./pages/camera-detail/SettingsPage"),
);
// Playback page replaced by unified MultiPlayback. Kept removed.
const LiveStream = lazy(() => import("./pages/LiveStream"));
const SettingsLayout = lazy(() =>
  import("./pages/settings/SettingsLayout"),
);
const SettingsConfiguration = lazy(() => import("./pages/Settings"));
const SettingsLicense = lazy(() => import("./pages/settings/LicensePage"));
const SettingsResources = lazy(() =>
  import("./pages/monitoring/ResourcesPage"),
);
const SettingsStorage = lazy(() => import("./pages/Storage"));
const Events = lazy(() => import("./pages/Events"));
const AuditLog = lazy(() => import("./pages/AuditLog"));
const Notifications = lazy(() => import("./pages/Notifications"));
const MultiPlayback = lazy(() => import("./pages/MultiPlayback"));
const AIModulesIndex = lazy(() => import("./pages/ai/AIModulesIndex"));
const ScenarioLayout = lazy(() => import("./pages/ai/scenarios/ScenarioLayout"));
const ScenarioStub = lazy(() => import("./pages/ai/scenarios/ScenarioStub"));
const PCLive = lazy(() =>
  import("./pages/ai/scenarios/people-counting/LivePage"),
);
const PCEvents = lazy(() =>
  import("./pages/ai/scenarios/people-counting/EventsPage"),
);
const PCAnalytics = lazy(() =>
  import("./pages/ai/scenarios/people-counting/AnalyticsPage"),
);
const FRSLive = lazy(() => import("./pages/ai/scenarios/frs/LivePage"));
const FRSInvestigate = lazy(() =>
  import("./pages/ai/scenarios/frs/InvestigatePage"),
);
const FRSAttendance = lazy(() =>
  import("./pages/ai/scenarios/frs/AttendancePage"),
);
const FRSEvents = lazy(() => import("./pages/ai/scenarios/frs/EventsPage"));
const FRSGroups = lazy(() => import("./pages/ai/scenarios/frs/GroupsPage"));
const FRSAnalytics = lazy(() =>
  import("./pages/ai/scenarios/frs/AnalyticsPage"),
);
const PPELive = lazy(() => import("./pages/ai/scenarios/ppe/LivePage"));
const PPEEvents = lazy(() => import("./pages/ai/scenarios/ppe/EventsPage"));
const PPEAnalytics = lazy(() =>
  import("./pages/ai/scenarios/ppe/AnalyticsPage"),
);
const FRSPersons = lazy(() => import("./pages/FRSPersons"));
const CameraAILayout = lazy(() =>
  import("./pages/camera-detail/ai/CameraAILayout"),
);
const CameraScenarioConfig = lazy(() =>
  import("./pages/camera-detail/ai/CameraScenarioConfig"),
);
const NotFound = lazy(() => import("./pages/NotFound"));

// React Query client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5000, retry: 1 },
  },
});

// Shared loading fallback
const PageSpinner = () => (
  <div className="min-h-screen flex items-center justify-center bg-white">
    <div className="flex flex-col items-center gap-3">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-slate-900" />
      <span className="text-sm text-slate-500">Loading…</span>
    </div>
  </div>
);

// ---------- route guards ----------

const ProtectedRoute = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth();
  if (isLoading) return <PageSpinner />;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
};

const PublicRoute = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth();
  if (isLoading) return <PageSpinner />;
  if (isAuthenticated) return <Navigate to="/" replace />;
  return children;
};

const AdminRoute = ({ children }) => {
  const { isAuthenticated, isAdmin, isLoading } = useAuth();
  if (isLoading) return <PageSpinner />;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  if (!isAdmin) return <Navigate to="/" replace />;
  return children;
};

// ---------- routes ----------

const AppRoutes = () => (
  <Suspense fallback={<PageSpinner />}>
    <Routes>
      {/* Public */}
      <Route
        path="/login"
        element={
          <PublicRoute>
            <Login />
          </PublicRoute>
        }
      />

      {/* Protected — no Layout (fullscreen) */}
      <Route
        path="/live/:cameraId"
        element={
          <ProtectedRoute>
            <LiveStream />
          </ProtectedRoute>
        }
      />

      {/* Protected — with Layout */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="cameras" element={<Cameras />} />
        <Route path="cameras/:cameraId" element={<CameraDetailLayout />}>
          <Route index element={<Navigate to="live" replace />} />
          <Route path="live" element={<CameraDetailLive />} />
          <Route path="recordings" element={<CameraDetailRecordings />} />
          <Route path="onvif" element={<CameraDetailOnvif />} />
          <Route path="ai" element={<CameraAILayout />}>
            <Route path=":slug" element={<CameraScenarioConfig />} />
          </Route>
          <Route path="settings" element={<CameraDetailSettings />} />
        </Route>
        {/* Playback is now a single unified page (MultiPlayback). Old
            single-cam Playback retired. /playback/multi kept as alias. */}
        <Route path="playback" element={<MultiPlayback />} />
        <Route path="events" element={<Events />} />
        {/* AI Modules — system-wide scenario workspace */}
        <Route path="ai/modules" element={<AIModulesIndex />} />
        {/* People Counting workspace */}
        <Route path="ai/modules/people_counting" element={<ScenarioLayout />}>
          <Route index element={<Navigate to="live" replace />} />
          <Route path="live" element={<PCLive />} />
          <Route path="events" element={<PCEvents />} />
          <Route path="analytics" element={<PCAnalytics />} />
        </Route>
        {/* FRS workspace */}
        <Route path="ai/modules/frs" element={<ScenarioLayout />}>
          <Route index element={<Navigate to="persons" replace />} />
          <Route path="persons" element={<FRSPersons />} />
          <Route path="live" element={<FRSLive />} />
          <Route path="events" element={<FRSEvents />} />
          <Route path="attendance" element={<FRSAttendance />} />
          <Route path="investigate" element={<FRSInvestigate />} />
          <Route path="groups" element={<FRSGroups />} />
          <Route path="analytics" element={<FRSAnalytics />} />
        </Route>
        {/* PPE workspace */}
        <Route path="ai/modules/ppe" element={<ScenarioLayout />}>
          <Route index element={<Navigate to="live" replace />} />
          <Route path="live" element={<PPELive />} />
          <Route path="events" element={<PPEEvents />} />
          <Route path="analytics" element={<PPEAnalytics />} />
        </Route>
        {/* Generic catch-all for other scenarios — stubs until built */}
        <Route path="ai/modules/:slug" element={<ScenarioLayout />}>
          <Route index element={<ScenarioStub />} />
          <Route path="live" element={<ScenarioStub />} />
          <Route path="events" element={<ScenarioStub />} />
          <Route path="analytics" element={<ScenarioStub />} />
          <Route path="reports" element={<ScenarioStub />} />
        </Route>
        {/* Legacy aliases — keep so existing top-nav links don't 404 */}
        <Route path="ai/scenarios" element={<Navigate to="/ai/modules" replace />} />
        <Route path="ai/persons" element={<Navigate to="/ai/modules/frs/persons" replace />} />
        <Route path="settings" element={<SettingsLayout />}>
          <Route index element={<Navigate to="configuration" replace />} />
          <Route path="configuration" element={<SettingsConfiguration />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="resources" element={<SettingsResources />} />
          <Route path="storage" element={<SettingsStorage />} />
          <Route path="license" element={<AdminRoute><SettingsLicense /></AdminRoute>} />
          <Route
            path="audit"
            element={
              <AdminRoute>
                <AuditLog />
              </AdminRoute>
            }
          />
        </Route>
        <Route path="playback/multi" element={<MultiPlayback />} />
        {/* Legacy aliases */}
        <Route path="notifications" element={<Navigate to="/settings/notifications" replace />} />
        <Route path="monitoring" element={<Navigate to="/settings/resources" replace />} />
        <Route path="monitoring/resources" element={<Navigate to="/settings/resources" replace />} />
        <Route path="monitoring/storage" element={<Navigate to="/settings/storage" replace />} />
        <Route path="monitoring/audit" element={<Navigate to="/settings/audit" replace />} />
        <Route path="audit" element={<Navigate to="/settings/audit" replace />} />
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  </Suspense>
);

// ---------- root ----------

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <AuthProvider>
            <BrowserRouter>
              <AppRoutes />
            </BrowserRouter>
            <Toaster position="bottom-right" richColors closeButton />
          </AuthProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
