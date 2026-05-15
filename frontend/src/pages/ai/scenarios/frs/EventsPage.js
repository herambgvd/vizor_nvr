// =============================================================================
// FRS · Events — /ai/modules/frs/events
// =============================================================================

import React, { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { UserCheck, ShieldAlert } from "lucide-react";
import { format } from "date-fns";
import apiClient from "../../../../api/client";
import { useEventStream } from "../../../../hooks/useEventStream";
import { Badge } from "../../../../components/ui/badge";

const fetchEvents = async () => {
  const r = await apiClient.get("/events", {
    params: { event_type: "face_recognized", limit: 100, offset: 0 },
  });
  return r.data;
};

const ICON = (etype) =>
  etype === "face_alert" ? ShieldAlert : UserCheck;

const EventsPage = () => {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["frs-events"],
    queryFn: fetchEvents,
    refetchInterval: 30_000,
  });
  const events = data?.events || [];

  const onEvent = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["frs-events"] });
  }, [qc]);
  useEventStream({ scenario: "frs", onEvent });

  return (
    <div className="p-4 md:p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Recent events
        </h2>
        <span className="text-xs text-muted-foreground">{events.length} loaded</span>
      </div>

      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-card/50 text-zinc-400 uppercase text-[11px] tracking-wider">
              <tr>
                <th className="text-left p-3 font-medium">Time</th>
                <th className="text-left p-3 font-medium">Type</th>
                <th className="text-left p-3 font-medium">Person</th>
                <th className="text-left p-3 font-medium">Camera</th>
                <th className="text-right p-3 font-medium">Confidence</th>
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
                    <tr key={e.id} className="border-t border-white/5 hover:bg-card/50">
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
                      <td className="p-3 font-mono text-xs">
                        {e.person_id?.slice(0, 8) || "—"}
                      </td>
                      <td className="p-3 text-xs font-mono text-muted-foreground">
                        {e.camera_id?.slice(0, 8) || "—"}
                      </td>
                      <td className="p-3 text-right">
                        {e.confidence != null ? (
                          <Badge variant="outline" className="text-[10px]">
                            {(e.confidence * 100).toFixed(0)}%
                          </Badge>
                        ) : (
                          "—"
                        )}
                      </td>
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
