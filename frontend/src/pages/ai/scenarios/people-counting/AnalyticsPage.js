// =============================================================================
// People Counting · Analytics — /ai/modules/people_counting/analytics
// =============================================================================
// 24h in/out chart + peak occupancy per zone.
// =============================================================================

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, TrendingUp } from "lucide-react";
import { format } from "date-fns";
import { getCounts } from "../../../../api/people";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../../../components/ui/select";

const RANGES = {
  "24h": { label: "Last 24 hours", hours: 24, granularity: "hour" },
  "7d": { label: "Last 7 days", hours: 24 * 7, granularity: "day" },
  "30d": { label: "Last 30 days", hours: 24 * 30, granularity: "day" },
};

const AnalyticsPage = () => {
  const [rangeKey, setRangeKey] = useState("24h");
  const range = RANGES[rangeKey];

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ["people-analytics", rangeKey],
    queryFn: () => {
      const since = new Date(Date.now() - range.hours * 3600 * 1000).toISOString();
      return getCounts({
        granularity: range.granularity,
        since,
        limit: 2000,
      });
    },
    refetchInterval: 60_000,
  });

  // Aggregate across zones per bucket for chart
  const series = useMemo(() => {
    const buckets = {};
    rows.forEach((r) => {
      const key = r.bucket_ts;
      if (!buckets[key]) buckets[key] = { ts: key, in: 0, out: 0, occupancy: 0 };
      buckets[key].in += r.in_count;
      buckets[key].out += r.out_count;
      buckets[key].occupancy = Math.max(buckets[key].occupancy, r.occupancy);
    });
    return Object.values(buckets).sort((a, b) => a.ts.localeCompare(b.ts));
  }, [rows]);

  const maxIO = Math.max(1, ...series.map((b) => Math.max(b.in, b.out)));

  // Top zones by peak occupancy
  const topZones = useMemo(() => {
    const byZone = {};
    rows.forEach((r) => {
      const z = byZone[r.zone_id] || { zone_id: r.zone_id, in: 0, out: 0, peak: 0 };
      z.in += r.in_count;
      z.out += r.out_count;
      z.peak = Math.max(z.peak, r.occupancy);
      byZone[r.zone_id] = z;
    });
    return Object.values(byZone)
      .sort((a, b) => b.peak - a.peak)
      .slice(0, 10);
  }, [rows]);

  return (
    <div className="p-4 md:p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Analytics
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Aggregated across all configured zones.
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
          In vs Out
        </h3>
        {isLoading ? (
          <p className="text-xs text-muted-foreground py-8 text-center">Loading…</p>
        ) : series.length === 0 ? (
          <p className="text-xs text-muted-foreground py-8 text-center">
            No data in this range
          </p>
        ) : (
          <div className="h-48 flex items-end gap-0.5">
            {series.map((b) => (
              <div
                key={b.ts}
                className="flex-1 flex flex-col-reverse gap-px"
                title={`${format(new Date(b.ts), "MMM d HH:mm")} · in ${b.in} · out ${b.out}`}
              >
                <div
                  className="bg-emerald-400 rounded-t-sm"
                  style={{ height: `${(b.in / maxIO) * 100}%` }}
                />
                <div
                  className="bg-blue-400 rounded-t-sm"
                  style={{ height: `${(b.out / maxIO) * 100}%` }}
                />
              </div>
            ))}
          </div>
        )}
        <div className="mt-2 flex items-center gap-4 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-emerald-400" /> In
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-blue-400" /> Out
          </span>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card/40">
        <div className="px-4 py-3 border-b border-white/5 flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-teal-300" />
          <h3 className="text-sm font-semibold">Top zones by peak occupancy</h3>
        </div>
        {topZones.length === 0 ? (
          <p className="px-4 py-6 text-sm text-center text-muted-foreground">
            No data
          </p>
        ) : (
          <div className="divide-y divide-white/5">
            {topZones.map((z) => (
              <div
                key={z.zone_id}
                className="px-4 py-2.5 flex items-center gap-3 text-sm"
              >
                <span className="font-mono text-xs text-muted-foreground truncate flex-1">
                  {z.zone_id.slice(0, 12)}
                </span>
                <span className="text-emerald-300 font-mono">+{z.in}</span>
                <span className="text-blue-300 font-mono">-{z.out}</span>
                <span className="font-semibold tabular-nums">peak {z.peak}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default AnalyticsPage;
