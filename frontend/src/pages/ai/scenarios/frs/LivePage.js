// =============================================================================
// FRS · Live — /ai/modules/frs/live
// =============================================================================
// SSE-driven feed of face_recognized + face_alert events. Top KPI strip
// shows today's recognitions + watchlist hits.
// =============================================================================

import React, { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  UserCheck,
  AlertTriangle,
  ShieldAlert,
  Bell,
} from "lucide-react";
import { format } from "date-fns";
import apiClient from "../../../../api/client";
import { useEventStream } from "../../../../hooks/useEventStream";
import { useLiveDetections } from "../../../../hooks/useLiveDetections";
import { getActiveCamerasBundle } from "../../../../api/people";
import LiveCameraTile from "../../../../components/ai/LiveCameraTile";
import { Badge } from "../../../../components/ui/badge";
import { cn } from "../../../../lib/utils";

const MAX_FEED = 50;

const fetchTodayStats = async () => {
  const r = await apiClient.get("/events", {
    params: { event_type: "face_recognized", limit: 1, offset: 0 },
  });
  return r.data;
};

const LivePage = () => {
  const [feed, setFeed] = useState([]);

  const onEvent = useCallback((ev) => {
    setFeed((prev) => {
      const next = [{ ...ev, _seen: Date.now() }, ...prev];
      return next.length > MAX_FEED ? next.slice(0, MAX_FEED) : next;
    });
  }, []);

  useEventStream({ scenario: "frs", onEvent });
  const detsByCamera = useLiveDetections({ scenario: "frs" });

  const { data: bundle } = useQuery({
    queryKey: ["ai-active-cameras", "frs"],
    queryFn: () => getActiveCamerasBundle("frs"),
    refetchInterval: 30_000,
  });

  const { data: stats } = useQuery({
    queryKey: ["frs-today"],
    queryFn: fetchTodayStats,
    refetchInterval: 30_000,
  });
  const todayTotal = stats?.total || 0;

  const watchlistAlerts = feed.filter((e) => e.event_type === "face_alert").length;

  return (
    <div className="p-4 md:p-6 space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Kpi label="Today" value={todayTotal} icon={UserCheck} tone="teal" />
        <Kpi label="Watchlist hits" value={watchlistAlerts} icon={ShieldAlert} tone={watchlistAlerts ? "rose" : "muted"} />
        <Kpi label="Live feed" value={feed.length} icon={Bell} tone="blue" />
      </div>

      {/* Live tiles */}
      {bundle?.cameras?.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {bundle.cameras.map((c) => (
            <LiveCameraTile
              key={c.id}
              cameraId={c.id}
              label={c.name}
              detections={detsByCamera[c.id] || []}
            />
          ))}
        </div>
      )}

      <div className="rounded-lg border border-border bg-card/40">
        <div className="px-4 py-3 border-b border-white/5 flex items-center gap-2">
          <Bell className="h-4 w-4 text-teal-300" />
          <h2 className="text-sm font-semibold">Live recognitions</h2>
        </div>
        <div className="divide-y divide-white/5 max-h-[60vh] overflow-y-auto">
          {feed.length === 0 ? (
            <p className="px-4 py-8 text-sm text-center text-muted-foreground">
              Listening for face events…
            </p>
          ) : (
            feed.map((ev, i) => {
              const isAlert = ev.event_type === "face_alert";
              return (
                <div
                  key={`${ev.track_id || i}-${ev._seen}`}
                  className={cn(
                    "px-4 py-2.5 flex items-center gap-3 text-sm",
                    isAlert && "bg-rose-500/[0.05]",
                  )}
                >
                  {isAlert ? (
                    <AlertTriangle className="h-4 w-4 text-rose-300 shrink-0" />
                  ) : (
                    <UserCheck className="h-4 w-4 text-teal-300 shrink-0" />
                  )}
                  <span className="font-medium capitalize">
                    {(ev.event_type || "").replace(/_/g, " ")}
                  </span>
                  {ev.confidence != null && (
                    <Badge variant="outline" className="text-[10px]">
                      {(ev.confidence * 100).toFixed(0)}%
                    </Badge>
                  )}
                  <span className="text-[11px] text-muted-foreground font-mono">
                    cam {(ev.camera_id || "—").slice(0, 8)}
                  </span>
                  <span className="ml-auto text-[11px] text-muted-foreground">
                    {ev.ts
                      ? format(new Date(ev.ts), "HH:mm:ss")
                      : format(new Date(ev._seen), "HH:mm:ss")}
                  </span>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

const TONE = {
  teal: "text-teal-300 bg-teal-500/15",
  blue: "text-blue-300 bg-blue-500/15",
  rose: "text-rose-300 bg-rose-500/15",
  muted: "text-muted-foreground bg-card/60",
};

const Kpi = ({ label, value, icon: Icon, tone }) => {
  const cls = TONE[tone] || TONE.muted;
  return (
    <div className="rounded-lg border border-border bg-card/40 p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className={cn("inline-flex p-1.5 rounded-md", cls)}>
          <Icon className="h-3.5 w-3.5" />
        </span>
      </div>
      <p className="mt-1.5 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
};

export default LivePage;
