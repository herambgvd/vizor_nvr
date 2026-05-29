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
import ControlRoomLayout from "./components/shell/ControlRoomLayout";
import "./App.css";

// Lazy-loaded pages
const Login = lazy(() => import("./pages/Login"));
const LiveWall = lazy(() => import("./pages/LiveWall"));
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
const CameraDetailSnapshots = lazy(() =>
  import("./pages/camera-detail/SnapshotsPage"),
);
// Playback page replaced by unified MultiPlayback. Kept removed.
const LiveStream = lazy(() => import("./pages/LiveStream"));
const SettingsLayout = lazy(() =>
  import("./pages/settings/SettingsLayout"),
);
const SettingsConfiguration = lazy(() => import("./pages/Settings"));
const SettingsLicense = lazy(() => import("./pages/settings/LicensePage"));
const SettingsTime = lazy(() => import("./pages/settings/TimeSettingsPage"));
const SettingsNetwork = lazy(() => import("./pages/settings/NetworkSettingsPage"));
const SettingsIntegrations = lazy(() =>
  import("./pages/settings/IntegrationsPage"),
);
const SettingsResources = lazy(() =>
  import("./pages/monitoring/ResourcesPage"),
);
const SettingsStorage = lazy(() => import("./pages/Storage"));
const Events = lazy(() => import("./pages/Events"));
const AuditLog = lazy(() => import("./pages/AuditLog"));
const Notifications = lazy(() => import("./pages/Notifications"));
const Users = lazy(() => import("./pages/Users"));
const Bookmarks = lazy(() => import("./pages/Bookmarks"));
const MultiPlayback = lazy(() => import("./pages/MultiPlayback"));
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

      {/* Protected — control-room shell */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <ControlRoomLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<LiveWall />} />
        {/* Legacy dashboard route now redirects to the live wall */}
        <Route path="dashboard" element={<Navigate to="/" replace />} />
        <Route path="cameras" element={<Cameras />} />
        <Route path="cameras/:cameraId" element={<CameraDetailLayout />}>
          <Route index element={<Navigate to="live" replace />} />
          <Route path="live" element={<CameraDetailLive />} />
          <Route path="recordings" element={<CameraDetailRecordings />} />
          <Route path="onvif" element={<CameraDetailOnvif />} />
          <Route path="settings" element={<CameraDetailSettings />} />
          <Route path="snapshots" element={<CameraDetailSnapshots />} />
        </Route>
        {/* Playback is now a single unified page (MultiPlayback). Old
            single-cam Playback retired. /playback/multi kept as alias. */}
        <Route path="playback" element={<MultiPlayback />} />
        <Route path="events" element={<Events />} />
        <Route path="settings" element={<SettingsLayout />}>
          <Route index element={<Navigate to="configuration" replace />} />
          <Route path="configuration" element={<SettingsConfiguration />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="resources" element={<SettingsResources />} />
          <Route path="storage" element={<SettingsStorage />} />
          <Route path="license" element={<AdminRoute><SettingsLicense /></AdminRoute>} />
          <Route path="time" element={<AdminRoute><SettingsTime /></AdminRoute>} />
          <Route path="network" element={<AdminRoute><SettingsNetwork /></AdminRoute>} />
          <Route path="integrations" element={<AdminRoute><SettingsIntegrations /></AdminRoute>} />
          <Route path="users" element={<AdminRoute><Users /></AdminRoute>} />
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
        <Route path="bookmarks" element={<Bookmarks />} />
        {/* Legacy aliases */}
        <Route path="users" element={<Navigate to="/settings/users" replace />} />
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
