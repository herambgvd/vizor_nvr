// =============================================================================
// CameraAILayout — /cameras/:id/ai/*
// =============================================================================
// Left sub-nav lists every AI scenario (GA + planned). Active scenario
// route renders its own config form via Outlet. Replaces the legacy
// CameraAITab single-page component.
// =============================================================================

import React from "react";
import {
  Outlet,
  Link,
  useLocation,
  useNavigate,
  useOutletContext,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Sparkles, Lock, RefreshCw } from "lucide-react";
import apiClient from "../../../api/client";
import { cn } from "../../../lib/utils";

const fetchScenarios = async () => {
  const r = await apiClient.get("/ai/scenarios");
  return r.data;
};

const fetchCameraConfigs = async (cameraId) => {
  const r = await apiClient.get(`/ai/cameras/${cameraId}/scenarios`);
  return r.data;
};

const CameraAILayout = () => {
  const { cameraId, camera } = useOutletContext();
  const location = useLocation();
  const navigate = useNavigate();

  const { data: scenarios = [], isLoading } = useQuery({
    queryKey: ["ai-scenarios"],
    queryFn: fetchScenarios,
    staleTime: 60_000,
  });

  const { data: cameraConfigs = [] } = useQuery({
    queryKey: ["camera-ai-configs", cameraId],
    queryFn: () => fetchCameraConfigs(cameraId),
    enabled: !!cameraId,
  });

  const enabledSlugs = new Set(
    cameraConfigs.filter((c) => c.enabled).map((c) => c.scenario_slug),
  );

  // Active scenario slug from URL: /cameras/:id/ai/:slug
  const segments = location.pathname.split("/").filter(Boolean);
  const activeSlug = segments[3];

  // Redirect /cameras/:id/ai → first GA scenario
  React.useEffect(() => {
    if (!activeSlug && scenarios.length > 0) {
      const first = scenarios.find((s) => s.status === "ga");
      if (first) {
        navigate(`/cameras/${cameraId}/ai/${first.slug}`, { replace: true });
      }
    }
  }, [activeSlug, scenarios, cameraId, navigate]);

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <RefreshCw className="h-6 w-6 text-muted-foreground animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-[240px] flex-shrink-0 border-r border-border bg-card/30 flex flex-col py-2 overflow-y-auto">
        <div className="px-4 pt-2 pb-1 text-[11px] uppercase tracking-wider text-muted-foreground">
          Scenarios
        </div>
        {scenarios.map((s) => {
          const isActive = activeSlug === s.slug;
          const isGa = s.status === "ga";
          const isLicensed = s.licensed !== false;
          const unlocked = isGa && isLicensed;
          const isEnabled = enabledSlugs.has(s.slug);
          return (
            <Link
              key={s.slug}
              to={unlocked ? `/cameras/${cameraId}/ai/${s.slug}` : "#"}
              onClick={(e) => !unlocked && e.preventDefault()}
              className={cn(
                "group flex items-center gap-2 px-4 py-2 text-sm transition-colors relative",
                isActive
                  ? "text-white bg-card"
                  : unlocked
                    ? "text-zinc-400 hover:text-white hover:bg-card/60"
                    : "text-muted-foreground/50 cursor-not-allowed",
              )}
            >
              {isActive && (
                <span className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r-full bg-gradient-to-b from-teal-400 to-blue-400" />
              )}
              <Sparkles
                className={cn(
                  "h-4 w-4",
                  isEnabled ? "text-teal-300" : "text-muted-foreground/50",
                )}
              />
              <span className="flex-1 truncate">{s.name}</span>
              {(!isGa || !isLicensed) && (
                <Lock className="h-3 w-3 text-amber-300/70" />
              )}
              {isEnabled && (
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              )}
            </Link>
          );
        })}
      </aside>

      <main className="flex-1 min-w-0 overflow-y-auto">
        <Outlet context={{ cameraId, camera, scenarios, cameraConfigs }} />
      </main>
    </div>
  );
};

export default CameraAILayout;
