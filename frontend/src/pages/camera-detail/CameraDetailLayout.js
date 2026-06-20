// =============================================================================
// CameraDetailLayout — shell for /cameras/:cameraId sub-pages
// =============================================================================
// Header (back, name, status, REC, health pill, actions) + left nav with
// 6 sub-pages. Each sub-page is its own route so URLs are bookmarkable.
// =============================================================================

import React from "react";
import {
  Outlet,
  Link,
  useParams,
  useNavigate,
  useLocation,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  Video,
  Film,
  Radio,
  SlidersHorizontal,
  RefreshCw,
  Camera as CameraIcon,
  Activity,
  ImageIcon,
} from "lucide-react";
import { getCamera, getLatestHealth } from "../../api/cameras";
import { Button } from "../../components/ui/button";
import { StatusBadge } from "../../components/nvr/StatusBadge";
import { cn } from "../../lib/utils";

const NAV = [
  { path: "live", label: "Live View", icon: Video },
  { path: "recordings", label: "Recordings", icon: Film },
  { path: "onvif", label: "ONVIF", icon: Radio },
  { path: "settings", label: "Settings", icon: SlidersHorizontal },
  { path: "snapshots", label: "Snapshots", icon: ImageIcon },
];

const HealthPill = ({ data }) => {
  if (!data) return null;
  const k = data.bitrate_kbps;
  const f = data.fps_actual;
  const tone =
    (k != null && k < 64) || (f != null && f < 5)
      ? "bg-amber-500/10 text-amber-300 border-amber-500/20"
      : "bg-emerald-500/10 text-emerald-300 border-emerald-500/20";
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-[11px] font-mono",
        tone,
      )}
    >
      <Activity className="h-3 w-3" />
      {k != null ? `${k} kbps` : "—"}
      <span className="opacity-50">·</span>
      {f != null ? `${Math.round(f)} fps` : "—"}
    </div>
  );
};

const CameraDetailLayout = () => {
  const { cameraId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  const { data: camera, isLoading, isError, refetch } = useQuery({
    queryKey: ["camera", cameraId],
    queryFn: () => getCamera(cameraId),
    // Status flips are pushed via WS; no need for tight polling.
    refetchInterval: 60_000,
  });

  const { data: healthMap = {} } = useQuery({
    queryKey: ["camera-health-latest"],
    queryFn: getLatestHealth,
    refetchInterval: 30_000,
  });
  const health = healthMap[cameraId];

  if (isLoading) {
    return (
      <div
        className="h-full flex items-center justify-center"
        style={{ background: "var(--console-bg)" }}
      >
        <RefreshCw
          className="h-6 w-6 animate-spin"
          style={{ color: "var(--console-muted)" }}
        />
      </div>
    );
  }

  // A transient fetch error (e.g. a 500 / network blip) must NOT look like the
  // camera was deleted. Show a distinct "failed to load" + Retry state and keep
  // the "Camera not found" copy only for a genuinely empty successful response.
  if (isError && !camera) {
    return (
      <div
        className="h-full flex items-center justify-center"
        style={{ background: "var(--console-bg)" }}
      >
        <div className="text-center">
          <Activity
            className="h-10 w-10 mx-auto mb-3"
            style={{ color: "var(--console-rec)" }}
          />
          <p className="mb-3" style={{ color: "var(--console-rec)" }}>
            Failed to load camera
          </p>
          <div className="flex items-center justify-center gap-2">
            <Button variant="outline" onClick={() => refetch()}>
              <RefreshCw className="h-4 w-4 mr-1.5" />
              Retry
            </Button>
            <Button variant="ghost" onClick={() => navigate("/cameras")}>
              Back to Cameras
            </Button>
          </div>
        </div>
      </div>
    );
  }

  if (!camera) {
    return (
      <div
        className="h-full flex items-center justify-center"
        style={{ background: "var(--console-bg)" }}
      >
        <div className="text-center">
          <CameraIcon
            className="h-10 w-10 mx-auto mb-3"
            style={{ color: "var(--console-muted)" }}
          />
          <p className="mb-3" style={{ color: "var(--console-muted)" }}>
            Camera not found
          </p>
          <Button variant="outline" onClick={() => navigate("/cameras")}>
            Back to Cameras
          </Button>
        </div>
      </div>
    );
  }

  const isActive = (sub) => location.pathname.endsWith(`/${sub}`);

  return (
    <div
      className="flex flex-col h-full overflow-hidden console-root"
      style={{ background: "var(--console-bg)" }}
    >
      {/* Compact header */}
      <header
        className="flex-shrink-0 flex items-center gap-3 px-4 md:px-6 h-11 border-b console-panel"
        style={{ borderColor: "var(--console-border)" }}
      >
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 -ml-2 text-zinc-400 hover:text-white"
          onClick={() => navigate("/cameras")}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <h1
            className="text-sm font-semibold truncate"
            style={{ color: "var(--console-text)" }}
          >
            {camera.name}
          </h1>
          <StatusBadge status={camera.status} />
          {camera.is_recording && (
            <span
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-telemetry uppercase tracking-wide border"
              style={{
                background: "rgba(239,68,68,0.12)",
                color: "var(--console-rec)",
                borderColor: "rgba(239,68,68,0.3)",
              }}
            >
              <span
                className="h-1.5 w-1.5 rounded-full animate-pulse"
                style={{ background: "var(--console-rec)" }}
              />
              REC
            </span>
          )}
          <HealthPill data={health} />
        </div>
        <span
          className="hidden md:inline text-xs font-telemetry truncate max-w-[28ch]"
          style={{ color: "var(--console-muted)" }}
        >
          {camera.location || (camera.main_stream_url ? "Stream configured ✓" : "")}
        </span>
      </header>

      {/* Body: left nav + content */}
      <div className="flex-1 min-h-0 flex">
        <aside
          className="w-[200px] flex-shrink-0 border-r console-panel hidden md:flex flex-col py-2"
          style={{ borderColor: "var(--console-border)" }}
        >
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.path);
            return (
              <Link
                key={item.path}
                to={item.path}
                className="group relative flex items-center gap-2.5 px-4 py-2.5 text-xs font-telemetry uppercase tracking-wide transition-colors"
                style={{
                  color: active ? "var(--console-text)" : "var(--console-muted)",
                  background: active ? "var(--console-raised)" : "transparent",
                }}
              >
                {active && (
                  <span
                    className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r-full"
                    style={{ background: "var(--console-accent)" }}
                  />
                )}
                <Icon
                  className="h-4 w-4 shrink-0"
                  style={active ? { color: "var(--console-accent)" } : undefined}
                />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </aside>

        {/* Mobile horizontal nav */}
        <div
          className="md:hidden flex-shrink-0 fixed top-11 left-0 right-0 z-10 backdrop-blur-xl border-b console-panel overflow-x-auto"
          style={{ borderColor: "var(--console-border)" }}
        >
          <div className="flex gap-1 px-2 py-1.5">
            {NAV.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.path);
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-telemetry uppercase tracking-wide whitespace-nowrap transition-colors"
                  style={{
                    color: active ? "#06231f" : "var(--console-muted)",
                    background: active ? "var(--console-accent)" : "transparent",
                  }}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        </div>

        <main
          className="flex-1 min-w-0 overflow-y-auto pt-14 md:pt-0"
          style={{ background: "var(--console-bg)" }}
        >
          <Outlet context={{ camera, cameraId }} />
        </main>
      </div>
    </div>
  );
};

export default CameraDetailLayout;
