// =============================================================================
// AI · Reports tab — FRS dashboard summary.
//
// GET /api/ai/frs/reports/summary (since, until) →
//   { total_events, unique_persons, unknown_count, spoof_count,
//     by_camera: [{camera_id, count}], by_hour: [{hour, count}] }
//
// Renders stat cards + two simple inline-SVG bar charts (by camera, by hour).
// recharts is not a dependency, so charts are hand-rolled SVG (no extra deps).
// =============================================================================

import React, { useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  Activity,
  Users,
  UserX,
  ShieldAlert,
  BarChart3,
  Clock,
  Loader2,
} from "lucide-react";

import { frsSummary, getScenarioCameras } from "../../../api/frs";
import { Input } from "../../../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../../components/ui/select";
import { cameraNameMap } from "./frsShared";

function isoDaysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  d.setHours(0, 0, 0, 0);
  // datetime-local wants "YYYY-MM-DDTHH:mm"
  return d.toISOString().slice(0, 16);
}
function isoNow() {
  return new Date().toISOString().slice(0, 16);
}

const RANGE_PRESETS = [
  { value: "1", label: "Last 24 hours" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "custom", label: "Custom" },
];

function StatCard({ icon: Icon, label, value, accent }) {
  return (
    <div
      className="rounded-lg border p-4"
      style={{
        borderColor: "var(--console-border)",
        background: "var(--console-panel)",
      }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-telemetry">
          {label}
        </span>
        <Icon className={`h-4 w-4 ${accent}`} />
      </div>
      <div className="mt-2 text-2xl font-semibold text-zinc-100 font-telemetry">
        {value}
      </div>
    </div>
  );
}

// Horizontal bar chart (inline SVG). data: [{ label, value }].
function HBarChart({ data, color = "#3b82f6", emptyLabel }) {
  if (!data || data.length === 0) {
    return (
      <p className="text-xs text-zinc-500 py-6 text-center">{emptyLabel}</p>
    );
  }
  const max = Math.max(...data.map((d) => d.value), 1);
  const rowH = 26;
  const labelW = 120;
  const barW = 280;
  const valW = 44;
  const width = labelW + barW + valW;
  const height = data.length * rowH;

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="xMinYMin meet"
      role="img"
    >
      {data.map((d, i) => {
        const w = Math.max(2, (d.value / max) * barW);
        const y = i * rowH;
        return (
          <g key={`${d.label}-${i}`}>
            <text
              x={labelW - 8}
              y={y + rowH / 2}
              textAnchor="end"
              dominantBaseline="middle"
              fontSize="11"
              fill="#a1a1aa"
            >
              {d.label.length > 16 ? `${d.label.slice(0, 15)}…` : d.label}
            </text>
            <rect
              x={labelW}
              y={y + 5}
              width={barW}
              height={rowH - 10}
              rx="3"
              fill="#27272a"
            />
            <rect
              x={labelW}
              y={y + 5}
              width={w}
              height={rowH - 10}
              rx="3"
              fill={color}
              opacity="0.85"
            />
            <text
              x={labelW + barW + valW - 4}
              y={y + rowH / 2}
              textAnchor="end"
              dominantBaseline="middle"
              fontSize="11"
              fill="#d4d4d8"
            >
              {d.value}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// Vertical bar chart for the 24-hour distribution.
function HourChart({ byHour, color = "#10b981" }) {
  // Normalize to a full 0..23 grid so gaps are visible.
  const counts = useMemo(() => {
    const arr = new Array(24).fill(0);
    (byHour || []).forEach((h) => {
      if (h.hour >= 0 && h.hour <= 23) arr[h.hour] = h.count;
    });
    return arr;
  }, [byHour]);

  const max = Math.max(...counts, 1);
  const colW = 18;
  const gap = 4;
  const chartH = 120;
  const labelH = 16;
  const width = 24 * (colW + gap);
  const height = chartH + labelH;

  if (!byHour || byHour.length === 0) {
    return (
      <p className="text-xs text-zinc-500 py-6 text-center">
        No events in range.
      </p>
    );
  }

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="xMinYMin meet"
      role="img"
    >
      {counts.map((c, h) => {
        const barH = c === 0 ? 0 : Math.max(2, (c / max) * chartH);
        const x = h * (colW + gap);
        const y = chartH - barH;
        return (
          <g key={h}>
            <rect
              x={x}
              y={0}
              width={colW}
              height={chartH}
              rx="2"
              fill="#27272a"
              opacity="0.5"
            />
            <rect
              x={x}
              y={y}
              width={colW}
              height={barH}
              rx="2"
              fill={color}
              opacity="0.85"
            >
              <title>{`${h}:00 — ${c} event${c === 1 ? "" : "s"}`}</title>
            </rect>
            {h % 3 === 0 && (
              <text
                x={x + colW / 2}
                y={chartH + labelH - 3}
                textAnchor="middle"
                fontSize="9"
                fill="#71717a"
              >
                {h}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function Panel({ title, icon: Icon, children }) {
  return (
    <div
      className="rounded-lg border p-4"
      style={{
        borderColor: "var(--console-border)",
        background: "var(--console-panel)",
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <Icon className="h-4 w-4 text-zinc-400" />
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-telemetry">
          {title}
        </span>
      </div>
      {children}
    </div>
  );
}

export default function ReportsTab({ scenario }) {
  const scenarioId = scenario?.id;
  const [preset, setPreset] = useState("7");
  const [customSince, setCustomSince] = useState(isoDaysAgo(7));
  const [customUntil, setCustomUntil] = useState(isoNow());

  const { since, until } = useMemo(() => {
    if (preset === "custom") {
      return {
        since: customSince ? new Date(customSince).toISOString() : undefined,
        until: customUntil ? new Date(customUntil).toISOString() : undefined,
      };
    }
    const d = new Date();
    d.setDate(d.getDate() - Number(preset));
    return { since: d.toISOString(), until: undefined };
  }, [preset, customSince, customUntil]);

  const { data: cameras = [] } = useQuery({
    queryKey: ["frs", "scenario-cameras", scenarioId],
    queryFn: () => getScenarioCameras(scenarioId),
    enabled: !!scenarioId,
  });
  const camMap = useMemo(() => cameraNameMap(cameras), [cameras]);

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["frs", "summary", since, until],
    queryFn: () => frsSummary({ since, until }),
    placeholderData: keepPreviousData,
  });

  const byCameraData = useMemo(
    () =>
      (data?.by_camera || []).map((c) => ({
        label: camMap[c.camera_id] || c.camera_id || "Unknown",
        value: c.count,
      })),
    [data, camMap],
  );

  return (
    <div className="p-4 space-y-4">
      {/* Range controls */}
      <div
        className="flex flex-wrap items-end gap-3 rounded-lg border p-3"
        style={{
          borderColor: "var(--console-border)",
          background: "var(--console-panel)",
        }}
      >
        <div className="w-44">
          <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">
            Range
          </label>
          <Select value={preset} onValueChange={setPreset}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RANGE_PRESETS.map((p) => (
                <SelectItem key={p.value} value={p.value}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {preset === "custom" && (
          <>
            <div>
              <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">
                From
              </label>
              <Input
                type="datetime-local"
                className="h-8 text-xs"
                value={customSince}
                onChange={(e) => setCustomSince(e.target.value)}
              />
            </div>
            <div>
              <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">
                To
              </label>
              <Input
                type="datetime-local"
                className="h-8 text-xs"
                value={customUntil}
                onChange={(e) => setCustomUntil(e.target.value)}
              />
            </div>
          </>
        )}
        {isFetching && (
          <Loader2 className="h-4 w-4 animate-spin text-zinc-400 self-center" />
        )}
      </div>

      {isError ? (
        <div className="py-16 text-center text-sm text-rose-400">
          Couldn't load the summary.
        </div>
      ) : (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard
              icon={Activity}
              label="Total events"
              value={isLoading ? "—" : (data?.total_events ?? 0)}
              accent="text-blue-400"
            />
            <StatCard
              icon={Users}
              label="Unique persons"
              value={isLoading ? "—" : (data?.unique_persons ?? 0)}
              accent="text-emerald-400"
            />
            <StatCard
              icon={UserX}
              label="Unknown"
              value={isLoading ? "—" : (data?.unknown_count ?? 0)}
              accent="text-amber-400"
            />
            <StatCard
              icon={ShieldAlert}
              label="Spoof attempts"
              value={isLoading ? "—" : (data?.spoof_count ?? 0)}
              accent="text-rose-400"
            />
          </div>

          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel title="Events by camera" icon={BarChart3}>
              {isLoading ? (
                <div className="h-32 rounded animate-pulse bg-zinc-800/40" />
              ) : (
                <HBarChart
                  data={byCameraData}
                  color="#3b82f6"
                  emptyLabel="No events in range."
                />
              )}
            </Panel>
            <Panel title="Events by hour (UTC)" icon={Clock}>
              {isLoading ? (
                <div className="h-32 rounded animate-pulse bg-zinc-800/40" />
              ) : (
                <HourChart byHour={data?.by_hour} color="#10b981" />
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
