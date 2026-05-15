// =============================================================================
// People Counting · Events — /ai/modules/people_counting/events
// =============================================================================
// Crowd alert + line-crossing event log. Pulls from /api/events with
// scenario filter. Live-patched via SSE.
// =============================================================================

import React, { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRightLeft,
  Bell,
} from "lucide-react";
import { format } from "date-fns";
import apiClient from "../../../../api/client";
import { useEventStream } from "../../../../hooks/useEventStream";
import { Badge } from "../../../../components/ui/badge";

const fetchEvents = async () => {
  // People counting emits two event types: line_crossing + crowd_alert.
  // Backend doesn't filter by source_service, so we drop the filter and
  // narrow client-side.
  const res = await apiClient.get("/events", {
    params: { limit: 100, offset: 0 },
  });
  const events = (res.data?.events || []).filter(
    (e) => e.event_type === "line_crossing" || e.event_type === "crowd_alert",
  );
  return { ...res.data, events };
};

const ICON = (etype) =>
  etype === "crowd_alert" ? AlertTriangle : etype === "line_crossing" ? ArrowRightLeft : Bell;

const EventsPage = () => {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["people-events"],
    queryFn: fetchEvents,
    refetchInterval: 30_000,
  });
  const events = data?.events || [];

  // Live patch — append SSE events that match our scenario
  const [livePatched, setLivePatched] = useState(0);
  const onEvent = useCallback(() => {
    setLivePatched((n) => n + 1);
    qc.invalidateQueries({ queryKey: ["people-events"] });
  }, [qc]);
  useEventStream({ scenario: "people_counting", onEvent });

  return (
    <div className="p-4 md:p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Recent events
        </h2>
        <span className="text-xs text-muted-foreground">
          {events.length} loaded
        </span>
      </div>

      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-card/50 text-zinc-400 uppercase text-[11px] tracking-wider">
              <tr>
                <th className="text-left p-3 font-medium">Time</th>
                <th className="text-left p-3 font-medium">Type</th>
                <th className="text-left p-3 font-medium">Severity</th>
                <th className="text-left p-3 font-medium">Camera</th>
                <th className="text-left p-3 font-medium">Title</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-muted-foreground">
                    Loading…
                  </td>
                </tr>
              ) : events.length === 0 ? (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-muted-foreground">
                    No events yet
                  </td>
                </tr>
              ) : (
                events.map((e) => {
                  const Icon = ICON(e.event_type);
                  return (
                    <tr
                      key={e.id}
                      className="border-t border-white/5 hover:bg-card/50"
                    >
                      <td className="p-3 text-muted-foreground whitespace-nowrap">
                        {e.triggered_at
                          ? format(new Date(e.triggered_at), "MMM dd HH:mm:ss")
                          : "—"}
                      </td>
                      <td className="p-3">
                        <span className="inline-flex items-center gap-1.5">
                          <Icon className="h-3.5 w-3.5" />
                          {(e.event_type || "").replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="p-3">
                        <Badge variant="outline" className="text-[10px]">
                          {e.severity}
                        </Badge>
                      </td>
                      <td className="p-3 text-xs font-mono text-muted-foreground">
                        {e.camera_id?.slice(0, 8) || "—"}
                      </td>
                      <td className="p-3 truncate max-w-[400px]">{e.title}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default EventsPage;
