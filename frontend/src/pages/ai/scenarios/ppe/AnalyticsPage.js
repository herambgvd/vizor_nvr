// =============================================================================
// PPE · Analytics — /ai/modules/ppe/analytics
// =============================================================================
// Compliance % per camera + missing-item breakdown.
// =============================================================================

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, ShieldAlert, HardHat } from "lucide-react";
import { format, subDays } from "date-fns";
import apiClient from "../../../../api/client";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../../../components/ui/select";
import { Badge } from "../../../../components/ui/badge";

const fetchEvents = async (since) => {
  const r = await apiClient.get("/events", {
    params: {
      event_type: "ppe_violation",
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
    queryKey: ["ppe-analytics", rangeKey],
    queryFn: () => fetchEvents(since),
    refetchInterval: 60_000,
  });
  const events = data?.events || [];

  const byCamera = useMemo(() => {
    const m = {};
    events.forEach((e) => {
      const c = e.camera_id || "unknown";
      m[c] = (m[c] || 0) + 1;
    });
    return Object.entries(m).sort((a, b) => b[1] - a[1]).slice(0, 10);
  }, [events]);

  const byItem = useMemo(() => {
    const m = {};
    events.forEach((e) => {
      (e.attributes?.missing_items || []).forEach((it) => {
        m[it] = (m[it] || 0) + 1;
      });
    });
    return Object.entries(m).sort((a, b) => b[1] - a[1]);
  }, [events]);

  const byHour = useMemo(() => {
    const m = {};
    events.forEach((e) => {
      const key = e.triggered_at
        ? format(new Date(e.triggered_at), "HH:00")
        : "—";
      m[key] = (m[key] || 0) + 1;
    });
    return Object.entries(m).sort((a, b) => a[0].localeCompare(b[0]));
  }, [events]);

  const maxByCamera = Math.max(1, ...byCamera.map(([, n]) => n));
  const maxByItem = Math.max(1, ...byItem.map(([, n]) => n));
  const maxByHour = Math.max(1, ...byHour.map(([, n]) => n));

  return (
    <div className="p-4 md:p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Analytics
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            PPE violations across all cameras.
          </p>
        </div>
        <Select value={rangeKey} onValueChange={setRangeKey}>
          <SelectTrigger className="w-44 h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(RANGES).map(([k, v]) => (
              <SelectItem key={k} value={k}>{v.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-lg border border-border bg-card/40 p-4">
          <h3 className="text-sm font-semibold flex items-center gap-2 mb-3">
            <HardHat className="h-4 w-4 text-rose-300" />
            Missing items
          </h3>
          {byItem.length === 0 ? (
            <p className="text-xs text-muted-foreground py-6 text-center">No data</p>
          ) : (
            <div className="space-y-1.5">
              {byItem.map(([it, n]) => (
                <div key={it} className="flex items-center gap-3 text-xs">
                  <span className="w-20 capitalize">{it}</span>
                  <div className="flex-1 h-3 bg-white/5 rounded-sm overflow-hidden">
                    <div
                      className="h-full bg-rose-400"
                      style={{ width: `${(n / maxByItem) * 100}%` }}
                    />
                  </div>
                  <span className="w-10 text-right font-mono">{n}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-border bg-card/40 p-4">
          <h3 className="text-sm font-semibold flex items-center gap-2 mb-3">
            <ShieldAlert className="h-4 w-4 text-rose-300" />
            Top cameras
          </h3>
          {byCamera.length === 0 ? (
            <p className="text-xs text-muted-foreground py-6 text-center">No data</p>
          ) : (
            <div className="space-y-1.5">
              {byCamera.map(([c, n]) => (
                <div key={c} className="flex items-center gap-3 text-xs">
                  <span className="w-24 font-mono text-muted-foreground truncate">
                    {c.slice(0, 12)}
                  </span>
                  <div className="flex-1 h-3 bg-white/5 rounded-sm overflow-hidden">
                    <div
                      className="h-full bg-amber-400"
                      style={{ width: `${(n / maxByCamera) * 100}%` }}
                    />
                  </div>
                  <span className="w-10 text-right font-mono">{n}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card/40 p-4">
        <h3 className="text-sm font-semibold flex items-center gap-2 mb-3">
          <BarChart3 className="h-4 w-4 text-teal-300" />
          Violations by hour
        </h3>
        {isLoading ? (
          <p className="text-xs text-muted-foreground py-6 text-center">Loading…</p>
        ) : byHour.length === 0 ? (
          <p className="text-xs text-muted-foreground py-6 text-center">No data</p>
        ) : (
          <div className="h-32 flex items-end gap-0.5">
            {byHour.map(([h, n]) => (
              <div
                key={h}
                className="flex-1 flex flex-col-reverse"
                title={`${h} · ${n} violations`}
              >
                <div
                  className="bg-rose-400 rounded-t-sm"
                  style={{ height: `${(n / maxByHour) * 100}%` }}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default AnalyticsPage;
