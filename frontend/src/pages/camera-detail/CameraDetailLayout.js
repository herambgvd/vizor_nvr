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
import { cn, maskStreamUrl } from "../../lib/utils";

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

  const { data: camera, isLoading } = useQuery({
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
      <div className="h-full flex items-center justify-center">
        <RefreshCw className="h-6 w-6 text-muted-foreground animate-spin" />
      </div>
    );
  }

  if (!camera) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <CameraIcon className="h-10 w-10 text-slate-300 mx-auto mb-3" />
          <p className="text-muted-foreground mb-3">Camera not found</p>
          <Button variant="outline" onClick={() => navigate("/cameras")}>
            Back to Cameras
          </Button>
        </div>
      </div>
    );
  }

  const isActive = (sub) => location.pathname.endsWith(`/${sub}`);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Compact header */}
      <header className="flex-shrink-0 flex items-center gap-3 px-4 md:px-6 h-14 border-b border-border bg-card/30">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 -ml-2"
          onClick={() => navigate("/cameras")}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <h1 className="text-base md:text-lg font-semibold truncate">
            {camera.name}
          </h1>
          <StatusBadge status={camera.status} />
          {camera.is_recording && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-rose-500/15 text-rose-300 border border-rose-500/30">
              <span className="h-1.5 w-1.5 rounded-full bg-rose-500 animate-pulse" />
              REC
            </span>
          )}
          <HealthPill data={health} />
        </div>
        <span className="hidden md:inline text-xs text-muted-foreground font-mono truncate max-w-[28ch]">
          {maskStreamUrl(camera.main_stream_url)}
        </span>
      </header>

      {/* Body: left nav + content */}
      <div className="flex-1 min-h-0 flex">
        <aside className="w-[220px] flex-shrink-0 border-r border-border bg-card/30 hidden md:flex flex-col py-2">
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.path);
            return (
              <Link
                key={item.path}
                to={item.path}
                className={cn(
                  "group relative flex items-center gap-2 px-4 py-2.5 text-sm transition-colors",
                  active
                    ? "text-white bg-card"
                    : "text-zinc-400 hover:text-white hover:bg-card/60",
                )}
              >
                {active && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r-full bg-gradient-to-b from-teal-400 to-blue-400" />
                )}
                <Icon className="h-4 w-4 shrink-0" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </aside>

        {/* Mobile horizontal nav */}
        <div className="md:hidden flex-shrink-0 fixed top-14 left-0 right-0 z-10 bg-card/95 backdrop-blur-xl border-b border-border overflow-x-auto">
          <div className="flex gap-1 px-2 py-1.5">
            {NAV.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.path);
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={cn(
                    "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors",
                    active
                      ? "bg-card text-white"
                      : "text-zinc-400 hover:text-white hover:bg-card/60",
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        </div>

        <main className="flex-1 min-w-0 overflow-y-auto pt-16 md:pt-0">
          <Outlet context={{ camera, cameraId }} />
        </main>
      </div>
    </div>
  );
};

export default CameraDetailLayout;
