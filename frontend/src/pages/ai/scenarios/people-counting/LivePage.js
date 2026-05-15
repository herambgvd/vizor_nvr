// =============================================================================
// People Counting · Live — /ai/modules/people_counting/live
// =============================================================================
// Real-time per-zone occupancy + today's in/out + recent events feed.
// Reads /api/ai/people/live (every 10s) and patches via SSE.
// =============================================================================

import React, { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Users,
  ArrowRightLeft,
  AlertTriangle,
  Bell,
  RefreshCw,
} from "lucide-react";
import { format } from "date-fns";
import {
  getLiveSnapshot,
  triggerAIReload,
  getActiveCamerasBundle,
} from "../../../../api/people";
import { useEventStream } from "../../../../hooks/useEventStream";
import { useLiveDetections } from "../../../../hooks/useLiveDetections";
import LiveCameraTile from "../../../../components/ai/LiveCameraTile";
import { Badge } from "../../../../components/ui/badge";
import { Button } from "../../../../components/ui/button";
import { toast } from "sonner";
import { cn } from "../../../../lib/utils";

const MAX_FEED = 30;

const LivePage = () => {
  const { data: rows = [], isLoading, refetch } = useQuery({
    queryKey: ["people-live"],
    queryFn: getLiveSnapshot,
    refetchInterval: 10_000,
  });

  const { data: bundle } = useQuery({
    queryKey: ["ai-active-cameras", "people_counting"],
    queryFn: () => getActiveCamerasBundle("people_counting"),
    refetchInterval: 30_000,
  });

  const detsByCamera = useLiveDetections({ scenario: "people_counting" });

  const zonesByCamera = (bundle?.zones || []).reduce((acc, z) => {
    const points = (z.geometry && (z.geometry.points || z.geometry.line)) || [];
    if (!acc[z.camera_id]) acc[z.camera_id] = [];
    acc[z.camera_id].push({
      id: z.id,
      name: z.name,
      points,
      severity: z.scenario === "crowd" ? "warning" : "info",
    });
    return acc;
  }, {});

  const [feed, setFeed] = useState([]);

  const handleEvent = useCallback(
    (ev) => {
      setFeed((prev) => {
        const next = [{ ...ev, _seen: Date.now() }, ...prev];
        return next.length > MAX_FEED ? next.slice(0, MAX_FEED) : next;
      });
      // Best-effort refetch on alert
      if (ev.event_type === "crowd_alert") refetch();
    },
    [refetch],
  );

  useEventStream({
    scenario: "people_counting",
    onEvent: handleEvent,
  });

  const totalIn = rows.reduce((a, r) => a + (r.in_today || 0), 0);
  const totalOut = rows.reduce((a, r) => a + (r.out_today || 0), 0);
  const totalOccupancy = rows.reduce((a, r) => a + (r.occupancy || 0), 0);
  const totalAlerts = rows.reduce((a, r) => a + (r.alerts_today || 0), 0);

  const handleReload = async () => {
    try {
      await triggerAIReload();
      toast.success("Reload signal sent to AI workers");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Reload failed");
    }
  };

  return (
    <div className="p-4 md:p-6 space-y-5">
      <div className="flex items-center justify-end">
        <Button variant="outline" size="sm" onClick={handleReload}>
          <RefreshCw className="h-3.5 w-3.5 mr-1" />
          Reload AI workers
        </Button>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="In today" value={totalIn} icon={ArrowRightLeft} tone="emerald" />
        <Kpi label="Out today" value={totalOut} icon={ArrowRightLeft} tone="blue" />
        <Kpi label="Live occupancy" value={totalOccupancy} icon={Users} tone="teal" />
        <Kpi
          label="Alerts today"
          value={totalAlerts}
          icon={AlertTriangle}
          tone={totalAlerts ? "rose" : "muted"}
        />
      </div>

      {/* Live tiles */}
      {bundle?.cameras?.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {bundle.cameras.map((c) => (
            <LiveCameraTile
              key={c.id}
              cameraId={c.id}
              label={c.name}
              zones={zonesByCamera[c.id] || []}
              detections={detsByCamera[c.id] || []}
            />
          ))}
        </div>
      )}

      {/* Zones list */}
      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <Users className="h-4 w-4 text-teal-300" />
            Per-zone snapshot
          </h2>
          <span className="text-xs text-muted-foreground">
            {rows.length} zones
          </span>
        </div>
        {isLoading ? (
          <p className="px-4 py-8 text-sm text-center text-muted-foreground">
            Loading…
          </p>
        ) : rows.length === 0 ? (
          <p className="px-4 py-8 text-sm text-center text-muted-foreground">
            No zones configured. Add one from a camera's AI tab.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-card/50 text-zinc-400 uppercase text-[11px] tracking-wider">
                <tr>
                  <th className="text-left p-3 font-medium">Zone</th>
                  <th className="text-left p-3 font-medium">Type</th>
                  <th className="text-right p-3 font-medium">In</th>
                  <th className="text-right p-3 font-medium">Out</th>
                  <th className="text-right p-3 font-medium">Occupancy</th>
                  <th className="text-right p-3 font-medium">Alerts</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.zone_id}
                    className="border-t border-white/5 hover:bg-card/50"
                  >
                    <td className="p-3 font-medium">{r.name}</td>
                    <td className="p-3">
                      <Badge
                        variant="outline"
                        className={cn(
                          "text-[10px]",
                          r.scenario === "in_out"
                            ? "bg-blue-500/15 text-blue-300 border-blue-500/30"
                            : "bg-amber-500/15 text-amber-300 border-amber-500/30",
                        )}
                      >
                        {r.scenario === "in_out" ? "In/Out" : "Crowd"}
                      </Badge>
                    </td>
                    <td className="p-3 text-right font-mono text-emerald-300">
                      {r.in_today}
                    </td>
                    <td className="p-3 text-right font-mono text-blue-300">
                      {r.out_today}
                    </td>
                    <td className="p-3 text-right font-mono">
                      {r.occupancy}
                      {r.threshold ? (
                        <span className="text-muted-foreground">
                          {" "}
                          / {r.threshold}
                        </span>
                      ) : null}
                    </td>
                    <td
                      className={cn(
                        "p-3 text-right font-mono",
                        r.alerts_today > 0
                          ? "text-rose-300"
                          : "text-muted-foreground",
                      )}
                    >
                      {r.alerts_today}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Live feed */}
      <div className="rounded-lg border border-border bg-card/40">
        <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <Bell className="h-4 w-4 text-teal-300" />
            Live feed
          </h2>
          <span className="text-xs text-muted-foreground">
            {feed.length} recent
          </span>
        </div>
        <div className="divide-y divide-white/5 max-h-80 overflow-y-auto">
          {feed.length === 0 ? (
            <p className="px-4 py-6 text-sm text-center text-muted-foreground">
              Listening for live events…
            </p>
          ) : (
            feed.map((ev, i) => (
              <div
                key={`${ev.zone_id || "x"}-${ev._seen}-${i}`}
                className="px-4 py-2.5 flex items-center gap-3 text-sm"
              >
                {ev.event_type === "crowd_alert" ? (
                  <AlertTriangle className="h-4 w-4 text-rose-300 shrink-0" />
                ) : (
                  <ArrowRightLeft className="h-4 w-4 text-teal-300 shrink-0" />
                )}
                <span className="font-medium capitalize">
                  {(ev.event_type || "").replace(/_/g, " ")}
                </span>
                {ev.direction && (
                  <Badge variant="outline" className="text-[10px]">
                    {ev.direction}
                  </Badge>
                )}
                {ev.count != null && (
                  <span className="text-xs text-muted-foreground font-mono">
                    count {ev.count}
                    {ev.threshold ? ` / ${ev.threshold}` : ""}
                  </span>
                )}
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
  emerald: "text-emerald-300 bg-emerald-500/15",
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
