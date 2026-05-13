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
const CameraDetail = lazy(() => import("./pages/CameraDetail"));
const Playback = lazy(() => import("./pages/Playback"));
const LiveStream = lazy(() => import("./pages/LiveStream"));
const SystemMonitoring = lazy(() => import("./pages/SystemMonitoring"));
const Settings = lazy(() => import("./pages/Settings"));
const Events = lazy(() => import("./pages/Events"));
const AuditLog = lazy(() => import("./pages/AuditLog"));
const Notifications = lazy(() => import("./pages/Notifications"));
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
        <Route path="cameras/:cameraId" element={<CameraDetail />} />
        <Route path="playback" element={<Playback />} />
        <Route path="events" element={<Events />} />
        <Route path="monitoring" element={<SystemMonitoring />} />
        <Route path="settings" element={<Settings />} />
        <Route path="playback/multi" element={<MultiPlayback />} />
        <Route path="notifications" element={<Notifications />} />
        <Route
          path="audit"
          element={
            <AdminRoute>
              <AuditLog />
            </AdminRoute>
          }
        />
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
            <Toaster position="top-right" richColors />
          </AuthProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
