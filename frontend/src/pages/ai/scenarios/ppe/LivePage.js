// =============================================================================
// PPE · Live — /ai/modules/ppe/live
// =============================================================================
// SSE feed of ppe_violation events with missing-item badges.
// =============================================================================

import React, { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ShieldAlert,
  AlertTriangle,
  HardHat,
  Activity,
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
    params: { event_type: "ppe_violation", limit: 1, offset: 0 },
  });
  return r.data;
};

const LivePage = () => {
  const [feed, setFeed] = useState([]);

  const onEvent = useCallback((ev) => {
    if (ev.event_type !== "ppe_violation") return;
    setFeed((prev) => {
      const next = [{ ...ev, _seen: Date.now() }, ...prev];
      return next.length > MAX_FEED ? next.slice(0, MAX_FEED) : next;
    });
  }, []);

  useEventStream({ scenario: "ppe", onEvent });
  const detsByCamera = useLiveDetections({ scenario: "ppe" });

  const { data: bundle } = useQuery({
    queryKey: ["ai-active-cameras", "ppe"],
    queryFn: () => getActiveCamerasBundle("ppe"),
    refetchInterval: 30_000,
  });

  const { data: stats } = useQuery({
    queryKey: ["ppe-today"],
    queryFn: fetchTodayStats,
    refetchInterval: 30_000,
  });
  const todayTotal = stats?.total || 0;

  // Aggregate missing-item counts in last N feed entries
  const itemCounts = feed.reduce((m, ev) => {
    (ev.missing_items || []).forEach((it) => {
      m[it] = (m[it] || 0) + 1;
    });
    return m;
  }, {});

  return (
    <div className="p-4 md:p-6 space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Kpi label="Violations today" value={todayTotal} icon={ShieldAlert} tone="rose" />
        <Kpi label="In feed" value={feed.length} icon={Activity} tone="amber" />
        <Kpi
          label="Top missing"
          value={
            Object.entries(itemCounts)
              .sort((a, b) => b[1] - a[1])
              .map(([k]) => k)[0] || "—"
          }
          icon={HardHat}
          tone="teal"
        />
      </div>

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
          <AlertTriangle className="h-4 w-4 text-rose-300" />
          <h2 className="text-sm font-semibold">Live violations</h2>
        </div>
        <div className="divide-y divide-white/5 max-h-[60vh] overflow-y-auto">
          {feed.length === 0 ? (
            <p className="px-4 py-8 text-sm text-center text-muted-foreground">
              Listening for PPE violations…
            </p>
          ) : (
            feed.map((ev, i) => (
              <div
                key={`${ev.track_id || i}-${ev._seen}`}
                className="px-4 py-2.5 flex items-center gap-3 text-sm bg-rose-500/[0.04]"
              >
                <ShieldAlert className="h-4 w-4 text-rose-300 shrink-0" />
                <span className="font-medium">PPE violation</span>
                {(ev.missing_items || []).map((it) => (
                  <Badge
                    key={it}
                    className="text-[10px] bg-rose-500/15 text-rose-300 border-rose-500/30"
                  >
                    no {it}
                  </Badge>
                ))}
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
            ))
          )}
        </div>
      </div>
    </div>
  );
};

const TONE = {
  teal: "text-teal-300 bg-teal-500/15",
  rose: "text-rose-300 bg-rose-500/15",
  amber: "text-amber-300 bg-amber-500/15",
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
