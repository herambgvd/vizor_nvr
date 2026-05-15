// =============================================================================
// PPE · Events — /ai/modules/ppe/events
// =============================================================================

import React, { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert, RefreshCw } from "lucide-react";
import { format } from "date-fns";
import apiClient from "../../../../api/client";
import { useEventStream } from "../../../../hooks/useEventStream";
import { Badge } from "../../../../components/ui/badge";
import { Button } from "../../../../components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../../../components/ui/select";

const ITEM_OPTIONS = [
  "helmet", "vest", "mask", "gloves", "goggles", "boots",
];

const fetchEvents = async () => {
  const params = {
    event_type: "ppe_violation",
    limit: 100,
    offset: 0,
  };
  const r = await apiClient.get("/events", { params });
  return r.data;
};

const EventsPage = () => {
  const qc = useQueryClient();
  const [item, setItem] = useState("all");

  const { data, isLoading } = useQuery({
    queryKey: ["ppe-events"],
    queryFn: fetchEvents,
    refetchInterval: 30_000,
  });
  const allEvents = data?.events || [];
  // Filter client-side by missing_items presence
  const events = item === "all"
    ? allEvents
    : allEvents.filter((e) => (e.attributes?.missing_items || []).includes(item));

  const onEvent = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["ppe-events"] });
  }, [qc]);
  useEventStream({ scenario: "ppe", onEvent });

  return (
    <div className="p-4 md:p-6 space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <Select value={item} onValueChange={setItem}>
          <SelectTrigger className="w-44 h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All violations</SelectItem>
            {ITEM_OPTIONS.map((opt) => (
              <SelectItem key={opt} value={opt}>
                Missing {opt}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          onClick={() => qc.invalidateQueries({ queryKey: ["ppe-events"] })}
        >
          <RefreshCw className="h-3.5 w-3.5 mr-1" />
          Refresh
        </Button>
        <span className="ml-auto text-xs text-muted-foreground">
          {events.length} shown
        </span>
      </div>

      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-card/50 text-zinc-400 uppercase text-[11px] tracking-wider">
              <tr>
                <th className="text-left p-3 font-medium">Time</th>
                <th className="text-left p-3 font-medium">Missing items</th>
                <th className="text-left p-3 font-medium">Camera</th>
                <th className="text-right p-3 font-medium">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={4} className="p-8 text-center text-muted-foreground">
                    Loading…
                  </td>
                </tr>
              ) : events.length === 0 ? (
                <tr>
                  <td colSpan={4} className="p-8 text-center text-muted-foreground">
                    No violations
                  </td>
                </tr>
              ) : (
                events.map((e) => (
                  <tr key={e.id} className="border-t border-white/5 hover:bg-card/50">
                    <td className="p-3 text-muted-foreground whitespace-nowrap">
                      {e.triggered_at
                        ? format(new Date(e.triggered_at), "MMM dd HH:mm:ss")
                        : "—"}
                    </td>
                    <td className="p-3">
                      <div className="flex flex-wrap gap-1">
                        {(e.attributes?.missing_items || []).length === 0 ? (
                          <span className="text-xs text-muted-foreground">—</span>
                        ) : (
                          (e.attributes.missing_items || []).map((it) => (
                            <Badge
                              key={it}
                              className="text-[10px] bg-rose-500/15 text-rose-300 border-rose-500/30"
                            >
                              {it}
                            </Badge>
                          ))
                        )}
                      </div>
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
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default EventsPage;
