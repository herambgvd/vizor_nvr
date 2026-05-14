// =============================================================================
// AIEventTimeline — horizontal swimlane of AI detection events for one camera.
//
// Sits below the playback timeline. Renders one row per detection_type
// (face, ppe_violation, vehicle, person_count, etc.) with color-coded
// dots positioned by timestamp. Filter chips let the operator hide types.
// Clicking a dot triggers an `onSeek(timestamp)` callback that the
// parent playback timeline uses to jump to that moment.
//
// Pulls from /api/events with source_service prefix=metropolis-* OR
// source_service=vizor-app-legacy. Hides native NVR events (motion,
// onvif, video loss) — those have their own timeline layer.
// =============================================================================

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";

import { getEvents } from "../../api/events";

// Stable color per detection_type
const TYPE_COLORS = {
  face: "bg-blue-500",
  facematch: "bg-blue-600",
  face_detected: "bg-blue-500",
  recognized: "bg-blue-700",
  unknown: "bg-slate-400",
  ppe_violation: "bg-orange-500",
  ppe: "bg-orange-500",
  person: "bg-yellow-500",
  person_count: "bg-yellow-600",
  vehicle: "bg-green-500",
  vehicle_detected: "bg-green-500",
  car: "bg-green-600",
  truck: "bg-green-700",
  license_plate: "bg-emerald-500",
  intrusion: "bg-red-500",
  line_crossing: "bg-red-400",
  loitering: "bg-destructive",
  action: "bg-purple-500",
  fighting: "bg-red-800",
  falling: "bg-red-700",
  anomaly: "bg-pink-500",
  weapon: "bg-red-900",
  object_detected: "bg-cyan-500",
};


function colorFor(type) {
  if (!type) return "bg-slate-400";
  const norm = type.toLowerCase();
  return TYPE_COLORS[norm] || "bg-slate-500";
}


export default function AIEventTimeline({
  cameraId,
  windowStart,
  windowEnd,
  onSeek,
  height = 80,
}) {
  const [hiddenTypes, setHiddenTypes] = useState(new Set());

  const { data, isLoading } = useQuery({
    queryKey: ["camera-ai-events", cameraId, windowStart, windowEnd],
    queryFn: () =>
      getEvents({
        camera_id: cameraId,
        from: windowStart?.toISOString(),
        to: windowEnd?.toISOString(),
        limit: 1000,
      }),
    enabled: !!cameraId && !!windowStart && !!windowEnd,
    keepPreviousData: true,
  });

  // Filter to AI-source events only
  const aiEvents = useMemo(() => {
    const arr = data?.events || data || [];
    return arr.filter((e) => {
      const src = e.source_service || "";
      return src.startsWith("metropolis") || src === "vizor-app-legacy";
    });
  }, [data]);

  // Group by detection_type for swimlanes
  const grouped = useMemo(() => {
    const g = {};
    for (const e of aiEvents) {
      const t = (e.detection_type || e.event_type || "other").toLowerCase();
      if (!g[t]) g[t] = [];
      g[t].push(e);
    }
    return g;
  }, [aiEvents]);

  const types = useMemo(() => Object.keys(grouped).sort(), [grouped]);

  const windowMs = useMemo(() => {
    if (!windowStart || !windowEnd) return 1;
    return windowEnd.getTime() - windowStart.getTime();
  }, [windowStart, windowEnd]);

  if (!cameraId || !windowStart || !windowEnd) return null;

  const toggleType = (t) => {
    setHiddenTypes((prev) => {
      const n = new Set(prev);
      if (n.has(t)) n.delete(t);
      else n.add(t);
      return n;
    });
  };

  return (
    <div className="space-y-2 px-2 py-3 bg-card border-t border-zinc-800">
      {/* Filter chips */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-muted-foreground mr-1">AI events:</span>
        {types.length === 0 && !isLoading ? (
          <span className="text-xs text-muted-foreground/70">none in window</span>
        ) : null}
        {types.map((t) => {
          const hidden = hiddenTypes.has(t);
          return (
            <button
              key={t}
              onClick={() => toggleType(t)}
              className={`flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] border transition ${
                hidden
                  ? "border-zinc-800 text-muted-foreground/70"
                  : "border-zinc-700 text-zinc-200 bg-primary"
              }`}
              title={hidden ? "Show" : "Hide"}
            >
              <span className={`w-2 h-2 rounded-full ${colorFor(t)}`} />
              {t.replace(/_/g, " ")}
              <span className="text-muted-foreground">{grouped[t].length}</span>
            </button>
          );
        })}
      </div>

      {/* Swimlanes */}
      <div
        className="relative w-full"
        style={{ height: `${Math.max(types.length, 1) * 14}px` }}
      >
        {types.map((t, rowIdx) => {
          if (hiddenTypes.has(t)) return null;
          return (
            <div
              key={t}
              className="absolute left-0 right-0 h-3 border-b border-zinc-900"
              style={{ top: `${rowIdx * 14}px` }}
            >
              {grouped[t].map((ev) => {
                const ts = new Date(
                  ev.triggered_at || ev.created_at
                ).getTime();
                const pct = ((ts - windowStart.getTime()) / windowMs) * 100;
                if (pct < 0 || pct > 100) return null;
                return (
                  <button
                    key={ev.id}
                    className={`absolute top-0.5 w-2 h-2 rounded-full ${colorFor(
                      t
                    )} hover:scale-150 transition-transform z-10`}
                    style={{ left: `${pct}%`, transform: "translateX(-50%)" }}
                    title={`${t} ${ev.confidence ? `(${(ev.confidence * 100).toFixed(0)}%)` : ""} — ${format(
                      new Date(ev.triggered_at),
                      "HH:mm:ss"
                    )}`}
                    onClick={() =>
                      onSeek?.(new Date(ev.triggered_at), ev)
                    }
                  />
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
