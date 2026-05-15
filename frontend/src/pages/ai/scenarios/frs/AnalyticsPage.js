// =============================================================================
// FRS · Analytics — /ai/modules/frs/analytics
// =============================================================================
// Daily recognitions trend + top-N persons by sightings.
// =============================================================================

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, TrendingUp, UserCheck } from "lucide-react";
import { format, subDays } from "date-fns";
import apiClient from "../../../../api/client";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../../../components/ui/select";

const fetchEvents = async (since) => {
  const r = await apiClient.get("/events", {
    params: {
      event_type: "face_recognized",
      start_date: since,
      limit: 1000,
      offset: 0,
    },
  });
  return r.data;
};

const RANGES = {
  "24h": { label: "Last 24 hours", days: 1 },
  "7d": { label: "Last 7 days", days: 7 },
  "30d": { label: "Last 30 days", days: 30 },
};

const AnalyticsPage = () => {
  const [rangeKey, setRangeKey] = useState("7d");
  const since = useMemo(
    () => subDays(new Date(), RANGES[rangeKey].days).toISOString(),
    [rangeKey],
  );

  const { data, isLoading } = useQuery({
    queryKey: ["frs-analytics", rangeKey],
    queryFn: () => fetchEvents(since),
    refetchInterval: 60_000,
  });
  const events = data?.events || [];

  const byDay = useMemo(() => {
    const m = {};
    events.forEach((e) => {
      const key = e.triggered_at
        ? format(new Date(e.triggered_at), "MMM dd")
        : "—";
      m[key] = (m[key] || 0) + 1;
    });
    return Object.entries(m).reverse();
  }, [events]);

  const byPerson = useMemo(() => {
    const m = {};
    events.forEach((e) => {
      const pid = e.person_id || "unknown";
      m[pid] = (m[pid] || 0) + 1;
    });
    return Object.entries(m)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10);
  }, [events]);

  const maxByDay = Math.max(1, ...byDay.map(([, n]) => n));
  const maxByPerson = Math.max(1, ...byPerson.map(([, n]) => n));

  return (
    <div className="p-4 md:p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Analytics
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Recognition events across all cameras.
          </p>
        </div>
        <Select value={rangeKey} onValueChange={setRangeKey}>
          <SelectTrigger className="w-44 h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(RANGES).map(([k, v]) => (
              <SelectItem key={k} value={k}>
                {v.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="rounded-lg border border-border bg-card/40 p-4 md:p-5">
        <h3 className="text-sm font-semibold flex items-center gap-2 mb-3">
          <BarChart3 className="h-4 w-4 text-teal-300" />
          Recognitions per day
        </h3>
        {isLoading ? (
          <p className="text-xs text-muted-foreground py-8 text-center">Loading…</p>
        ) : byDay.length === 0 ? (
          <p className="text-xs text-muted-foreground py-8 text-center">No data</p>
        ) : (
          <div className="space-y-1.5">
            {byDay.map(([day, n]) => (
              <div key={day} className="flex items-center gap-3 text-xs">
                <span className="w-20 text-muted-foreground font-mono">{day}</span>
                <div className="flex-1 h-3 bg-white/5 rounded-sm overflow-hidden">
                  <div
                    className="h-full bg-teal-400"
                    style={{ width: `${(n / maxByDay) * 100}%` }}
                  />
                </div>
                <span className="w-10 text-right font-mono">{n}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-border bg-card/40">
        <div className="px-4 py-3 border-b border-white/5 flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-teal-300" />
          <h3 className="text-sm font-semibold">Top persons</h3>
        </div>
        {byPerson.length === 0 ? (
          <p className="px-4 py-6 text-sm text-center text-muted-foreground">
            No data
          </p>
        ) : (
          <div className="divide-y divide-white/5">
            {byPerson.map(([pid, n]) => (
              <div key={pid} className="px-4 py-2.5 flex items-center gap-3 text-sm">
                <UserCheck className="h-4 w-4 text-teal-300 shrink-0" />
                <span className="font-mono text-xs text-muted-foreground truncate flex-1">
                  {pid.slice(0, 12)}
                </span>
                <div className="w-32 h-2 bg-white/5 rounded-sm overflow-hidden">
                  <div
                    className="h-full bg-teal-400"
                    style={{ width: `${(n / maxByPerson) * 100}%` }}
                  />
                </div>
                <span className="font-semibold tabular-nums w-10 text-right">{n}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default AnalyticsPage;
