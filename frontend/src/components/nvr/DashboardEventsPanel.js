// =============================================================================
// DashboardEventsPanel — inline 30% right column on Dashboard
// =============================================================================
// Real-time event feed embedded in the Dashboard grid. Pulls recent
// events from the API on mount, then patches the list in-place via
// WebSocket `new_event` broadcasts.
// =============================================================================

import React, { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bell,
  BellRing,
  AlertTriangle,
  Shield,
  Activity,
  Video,
  VideoOff,
  XCircle,
  Check,
  ArrowUpRight,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { toast } from "sonner";
import { cn } from "../../lib/utils";
import { eventTypeLabel } from "../../lib/eventLabels";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { useWebSocket } from "../../hooks/useWebSocket";
import { acknowledgeEvent } from "../../api/events";

const SEVERITY_STYLE = {
  info: {
    bar: "bg-blue-500",
    badge: "bg-blue-500/15 text-blue-300 border border-blue-500/30",
    label: "Info",
  },
  warning: {
    bar: "bg-amber-500",
    badge: "bg-amber-500/15 text-amber-300 border border-amber-500/30",
    label: "Warning",
  },
  critical: {
    bar: "bg-rose-500",
    badge: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
    label: "Critical",
  },
  alarm: {
    bar: "bg-rose-600 animate-pulse",
    badge: "bg-rose-500/25 text-rose-200 border border-rose-500/50",
    label: "Alarm",
  },
};

const ICON_FOR_TYPE = (type) => {
  if (!type) return Bell;
  if (type.startsWith("motion")) return Activity;
  if (type.includes("tamper")) return Shield;
  if (type === "video_loss" || type === "camera_offline") return VideoOff;
  if (type === "camera_online") return Video;
  if (type.includes("error") || type.includes("disk")) return XCircle;
  return AlertTriangle;
};

const MAX_BUFFER = 40;

const DashboardEventsPanel = ({ cameras = [] }) => {
  const qc = useQueryClient();
  const navigate = useNavigate();

  // Realtime-only buffer — no API fetch. Populated solely by WS
  // `new_event` broadcasts. Acknowledged events are removed.
  const [liveEvents, setLiveEvents] = useState([]);

  const cameraNameById = useMemo(() => {
    const m = new Map();
    (cameras || []).forEach((c) => m.set(c.id, c.name));
    return m;
  }, [cameras]);

  const handleNewEvent = useCallback((payload) => {
    if (!payload) return;
    setLiveEvents((prev) => {
      if (prev.some((e) => e.id === payload.id)) return prev;
      const next = [payload, ...prev];
      return next.length > MAX_BUFFER ? next.slice(0, MAX_BUFFER) : next;
    });
    qc.invalidateQueries({ queryKey: ["events"] });
    qc.invalidateQueries({ queryKey: ["events-unack-count"] });
    qc.invalidateQueries({ queryKey: ["event-stats"] });
  }, [qc]);

  useWebSocket({
    channels: ["events", "system"],
    onNewEvent: handleNewEvent,
  });

  const handleAck = async (id) => {
    try {
      await acknowledgeEvent(id, null);
      // Acknowledged events leave the live feed — they remain in the
      // full Events page for history. Live panel only shows actionable
      // realtime items.
      setLiveEvents((prev) => prev.filter((e) => e.id !== id));
      qc.invalidateQueries({ queryKey: ["events"] });
    } catch {
      toast.error("Acknowledge failed");
    }
  };

  return (
    <aside className="h-full flex flex-col rounded-lg border border-border bg-card/40 overflow-hidden">
      <header className="px-4 py-3 border-b border-white/5 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <BellRing className="h-4 w-4 text-teal-300" />
          Live Events
          <Badge variant="outline" className="ml-1 text-[10px]">
            {liveEvents.length}
          </Badge>
        </div>
        <button
          type="button"
          onClick={() => navigate("/events")}
          className="text-xs text-muted-foreground hover:text-white inline-flex items-center gap-1"
        >
          View all
          <ArrowUpRight className="h-3.5 w-3.5" />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1.5">
        {liveEvents.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center text-muted-foreground py-12">
            <Bell className="h-7 w-7 mb-2 opacity-40" />
            <p className="text-xs">No events yet</p>
            <p className="text-[11px] mt-1 opacity-70">
              New alarms appear here in real time
            </p>
          </div>
        ) : (
          liveEvents.map((evt) => {
            const sev = SEVERITY_STYLE[evt.severity] || SEVERITY_STYLE.info;
            const Icon = ICON_FOR_TYPE(evt.event_type);
            const camName =
              cameraNameById.get(evt.camera_id) ||
              (evt.camera_id ? evt.camera_id.slice(0, 8) : "System");
            return (
              <div
                key={evt.id}
                className="relative rounded-md border border-white/5 bg-card/50 overflow-hidden"
              >
                <div className={cn("absolute left-0 top-0 bottom-0 w-[3px]", sev.bar)} />
                <div className="pl-3 pr-2 py-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span className="text-[13px] font-medium truncate">
                        {evt.title || eventTypeLabel(evt.event_type)}
                      </span>
                    </div>
                    <Badge className={cn("shrink-0 text-[10px] py-0 px-1.5", sev.badge)}>
                      {sev.label}
                    </Badge>
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <span className="truncate">{camName}</span>
                    <span>·</span>
                    <span>
                      {evt.triggered_at
                        ? format(new Date(evt.triggered_at), "HH:mm:ss")
                        : "now"}
                    </span>
                  </div>
                  <div className="mt-1.5 flex items-center gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-6 px-1.5 text-[11px]"
                      onClick={() => handleAck(evt.id)}
                    >
                      <Check className="h-3 w-3 mr-1" />
                      Ack
                    </Button>
                    {evt.camera_id && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 px-1.5 text-[11px]"
                        onClick={() =>
                          navigate(`/playback?camera=${evt.camera_id}`)
                        }
                      >
                        <ArrowUpRight className="h-3 w-3 mr-1" />
                        Playback
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
};

export default DashboardEventsPanel;
