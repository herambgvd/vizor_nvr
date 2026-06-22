// =============================================================================
// AI · ANPR · Reports tab — plate-read summary: total reads, blacklist /
// whitelist hits, by-vehicle-type, by-camera and by-hour breakdowns. Scoped to
// ANPR only. Plugin /reports/summary drives the plate-read panels.
// =============================================================================

import React, { useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  Activity,
  Users,
  ShieldAlert,
  BarChart3,
  Clock,
  Loader2,
} from "lucide-react";

import { listScenarioCameras, listScenarioEvents, scenarioReportsSummary } from "../../../../api/ai";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../../../components/ui/select";
import { cameraNameMap } from "../frs/frsShared";

const RANGE_PRESETS = [
  { value: "1", label: "Last 24 hours" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
];

const SCOPE = {
  activeLabel: "Recognition active",
  scopeTitle: "ANPR model scope",
  blurb:
    "License plate reports are plugin-driven. Plate reads, vehicle types and watchlist hits are produced by the ANPR scenario.",
  footnote:
    "Detailed plate-read counts will populate here once the ANPR engine publishes plugin report metrics.",
};

function scenarioScopeItems(scenario) {
  if (Array.isArray(scenario?.event_types) && scenario.event_types.length) return scenario.event_types;
  return [];
}

function StatCard({ icon: Icon, label, value, accent }) {
  return (
    <div className="rounded-lg border p-4" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-telemetry">{label}</span>
        <Icon className={`h-4 w-4 ${accent}`} />
      </div>
      <div className="mt-2 text-2xl font-semibold text-zinc-100 font-telemetry">{value}</div>
    </div>
  );
}

function HBarChart({ data, color = "#3b82f6", emptyLabel }) {
  if (!data || data.length === 0) {
    return <p className="text-xs text-zinc-500 py-6 text-center">{emptyLabel}</p>;
  }
  const max = Math.max(...data.map((d) => d.value), 1);
  const rowH = 26;
  const labelW = 120;
  const barW = 280;
  const valW = 44;
  const width = labelW + barW + valW;
  const height = data.length * rowH;
  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMinYMin meet" role="img">
      {data.map((d, i) => {
        const w = Math.max(2, (d.value / max) * barW);
        const y = i * rowH;
        return (
          <g key={`${d.label}-${i}`}>
            <text x={labelW - 8} y={y + rowH / 2} textAnchor="end" dominantBaseline="middle" fontSize="11" fill="#a1a1aa">
              {d.label.length > 16 ? `${d.label.slice(0, 15)}…` : d.label}
            </text>
            <rect x={labelW} y={y + 5} width={barW} height={rowH - 10} rx="3" fill="#27272a" />
            <rect x={labelW} y={y + 5} width={w} height={rowH - 10} rx="3" fill={color} opacity="0.85" />
            <text x={labelW + barW + valW - 4} y={y + rowH / 2} textAnchor="end" dominantBaseline="middle" fontSize="11" fill="#d4d4d8">
              {d.value}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function Panel({ title, icon: Icon, children }) {
  return (
    <div className="rounded-lg border p-4" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
      <div className="flex items-center gap-2 mb-3">
        <Icon className="h-4 w-4 text-zinc-400" />
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-telemetry">{title}</span>
      </div>
      {children}
    </div>
  );
}

export default function ReportsTab({ scenario }) {
  const scenarioId = scenario?.id;
  const [preset, setPreset] = useState("7");

  const { since, until } = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - Number(preset));
    return { since: d.toISOString(), until: undefined };
  }, [preset]);

  const { data: cameras = [], isLoading: camerasLoading } = useQuery({
    queryKey: ["scenario-cameras", scenarioId],
    queryFn: () => listScenarioCameras(scenarioId),
    enabled: !!scenarioId,
  });

  const hasPluginSummary = useMemo(
    () => (scenario?.proxy_routes || []).some((route) => route?.path === "/reports/summary"),
    [scenario?.proxy_routes],
  );
  const { data: events, isLoading: eventsLoading, isFetching } = useQuery({
    queryKey: ["scenario-events-summary", "anpr", since, until],
    queryFn: () => listScenarioEvents(scenario.slug, { since, until, limit: 500 }),
    enabled: !!scenario?.slug,
    placeholderData: keepPreviousData,
  });

  const { data: pluginSummary } = useQuery({
    queryKey: ["scenario-plugin-summary", "anpr", since, until],
    queryFn: () => scenarioReportsSummary(scenario.slug, { since, until }),
    enabled: !!scenario?.slug && hasPluginSummary,
    placeholderData: keepPreviousData,
  });

  const enabledCount = useMemo(() => (cameras || []).filter((c) => c.enabled).length, [cameras]);
  const cameraNames = useMemo(() => cameraNameMap(cameras || []), [cameras]);
  const byHourData = useMemo(
    () => (pluginSummary?.by_hour || []).map((b) => ({ label: `${b.hour}:00`, value: b.count })),
    [pluginSummary],
  );
  const summaryByCamera = useMemo(
    () => (pluginSummary?.by_camera || []).map((b) => ({
      label: cameraNames[b.camera_id] || b.camera_id || "Unknown",
      value: b.count,
    })),
    [pluginSummary, cameraNames],
  );
  const anprByVehicle = useMemo(
    () => (pluginSummary?.by_vehicle_type || []).map((b) => ({
      label: b.vehicle_type || "unknown",
      value: b.count,
    })),
    [pluginSummary],
  );
  const scopeItems = useMemo(() => scenarioScopeItems(scenario), [scenario]);

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-end gap-3 rounded-lg border p-3" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
        <div className="w-44">
          <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">Range</label>
          <Select value={preset} onValueChange={setPreset}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RANGE_PRESETS.map((p) => (
                <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {isFetching && <Loader2 className="h-4 w-4 animate-spin text-zinc-400 self-center" />}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          icon={Activity}
          label="Plate reads"
          value={eventsLoading ? "—" : (pluginSummary?.total_reads ?? events?.total ?? (events?.items || []).length)}
          accent="text-blue-400"
        />
        <StatCard icon={Users} label="Assigned cameras" value={camerasLoading ? "—" : cameras.length} accent="text-emerald-400" />
        <StatCard icon={ShieldAlert} label={SCOPE.activeLabel} value={camerasLoading ? "—" : enabledCount} accent="text-amber-400" />
        <StatCard icon={BarChart3} label="Detection classes" value={scopeItems.length} accent="text-purple-400" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title={SCOPE.scopeTitle} icon={Clock}>
          <div className="space-y-3 text-[12px] text-zinc-400">
            <p>{SCOPE.blurb}</p>
            {scopeItems.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {scopeItems.map((item) => (
                  <span key={item} className="rounded border border-white/10 bg-black px-2 py-1 text-[11px] uppercase tracking-wide">
                    {String(item).replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            )}
            <p className="text-zinc-600">{SCOPE.footnote}</p>
          </div>
        </Panel>
      </div>

      {/* Plate-read summary — counts + breakdowns. */}
      {pluginSummary && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard icon={Activity} label="Total reads" value={pluginSummary.total_reads ?? 0} accent="text-blue-400" />
            <StatCard icon={ShieldAlert} label="Blacklist hits" value={pluginSummary.blacklist_hits ?? 0} accent="text-rose-400" />
            <StatCard icon={Users} label="Whitelist hits" value={pluginSummary.whitelist_hits ?? 0} accent="text-emerald-400" />
            <StatCard icon={BarChart3} label="Vehicle types" value={anprByVehicle.length} accent="text-purple-400" />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel title="Reads by camera" icon={BarChart3}>
              <HBarChart data={summaryByCamera} color="#228B22" emptyLabel="No plate reads in this range yet." />
            </Panel>
            <Panel title="By vehicle type" icon={BarChart3}>
              <HBarChart data={anprByVehicle} color="#14b8a6" emptyLabel="No plate reads in this range yet." />
            </Panel>
          </div>
          <Panel title="Reads by hour" icon={Clock}>
            <HBarChart data={byHourData} color="#3b82f6" emptyLabel="No reads in this range yet." />
          </Panel>
        </>
      )}
    </div>
  );
}
