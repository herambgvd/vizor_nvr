// =============================================================================
// AI · Reports tab — generic scenario-level report shell.
//
// This tab must not call FRS/PPE hardcoded APIs. All scenarios are moving to
// plugin ownership, so this uses only generic scenario camera assignments and
// scenario-filtered NVR events.
// =============================================================================

import React, { useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  Activity,
  Briefcase,
  Users,
  ShieldAlert,
  BarChart3,
  Clock,
  Loader2,
} from "lucide-react";

import { listScenarioCameras, listScenarioEvents, scenarioReportsSummary } from "../../../api/ai";
import { listFrsEvents } from "../../../api/frs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../../components/ui/select";
import { cameraNameMap } from "./frsShared";

const RANGE_PRESETS = [
  { value: "1", label: "Last 24 hours" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
];

// Per-scenario copy for the "model scope" panel + the activity stat label.
// Falls back to a generic plugin description for any unknown scenario.
const SCOPE_BY_SLUG = {
  "suspect-search": {
    activeLabel: "Indexing active",
    scopeTitle: "Scenario model scope",
    blurb:
      "Suspect Search reports are plugin-driven. Indexed detections remain searchable even after a camera is disabled.",
    footnote:
      "Detailed detection counts will populate here once the ONNX detector/ReID engine publishes plugin report metrics.",
  },
  ppe: {
    activeLabel: "Compliance active",
    scopeTitle: "PPE model scope",
    blurb:
      "PPE compliance reports are plugin-driven. Violations and compliant verdicts are produced per worker by the PPE scenario.",
    footnote:
      "Detailed compliance counts will populate here once the PPE detector publishes plugin report metrics.",
  },
  frs: {
    activeLabel: "Recognition active",
    scopeTitle: "FRS model scope",
    blurb:
      "Face recognition reports are plugin-driven. Recognition events and attendance are owned by the FRS scenario.",
    footnote:
      "Detailed recognition counts will populate here once the FRS detector/embedding engine publishes plugin report metrics.",
  },
};

const DEFAULT_SCOPE = {
  activeLabel: "Active cameras",
  scopeTitle: "Scenario model scope",
  blurb:
    "Reports for this scenario are plugin-driven. Detections are produced by the scenario microservice.",
  footnote:
    "Detailed counts will populate here once the scenario publishes plugin report metrics.",
};

// Pull the most meaningful "scope" chips a scenario exposes: suspect-search uses
// object_types; PPE exposes required PPE items; FRS lists its event types.
function scenarioScopeItems(scenario) {
  const fields = scenario?.camera_config_schema?.fields || [];
  const byKey = (k) => fields.find((f) => f.key === k)?.default;
  const fromSchema =
    byKey("object_types") ||
    byKey("required_items") ||
    byKey("required_ppe") ||
    byKey("required_items");
  if (Array.isArray(fromSchema) && fromSchema.length) return fromSchema;
  if (Array.isArray(scenario?.event_types) && scenario.event_types.length) {
    return scenario.event_types;
  }
  return [];
}

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

  // FRS owns its events in the plugin DB (full isolation), so its reports read
  // the plugin's /events; other scenarios aggregate from the unified NVR store.
  const isFrs = (scenario?.slug || "") === "frs";
  const hasPluginSummary = useMemo(
    () => (scenario?.proxy_routes || []).some((route) => route?.path === "/reports/summary"),
    [scenario?.proxy_routes],
  );
  const { data: events, isLoading: eventsLoading, isFetching } = useQuery({
    queryKey: ["scenario-events-summary", scenario?.slug, since, until],
    queryFn: () =>
      isFrs
        ? listFrsEvents({ since, until, limit: 500 })
        : listScenarioEvents(scenario.slug, { since, until, limit: 500 }),
    enabled: !!scenario?.slug,
    placeholderData: keepPreviousData,
  });

  const { data: pluginSummary } = useQuery({
    queryKey: ["scenario-plugin-summary", scenario?.slug, since, until],
    queryFn: () => scenarioReportsSummary(scenario.slug, { since, until }),
    enabled: !!scenario?.slug && hasPluginSummary,
    placeholderData: keepPreviousData,
  });

  const enabledCount = useMemo(
    () => (cameras || []).filter((camera) => camera.enabled).length,
    [cameras],
  );
  const byHourData = useMemo(
    () => (pluginSummary?.by_hour || []).map((b) => ({ label: `${b.hour}:00`, value: b.count })),
    [pluginSummary],
  );
  const eventsList = useMemo(() => events?.items || [], [events]);
  const byCameraData = useMemo(() => {
    const names = cameraNameMap(cameras || []);
    const counts = new Map();
    eventsList.forEach((event) => {
      const cameraId = event.camera_id || event.cameraId || "system";
      counts.set(cameraId, (counts.get(cameraId) || 0) + 1);
    });
    return Array.from(counts.entries()).map(([cameraId, count]) => ({
      label: names[cameraId] || cameraId || "Unknown",
      value: count,
    }));
  }, [eventsList, cameras]);

  // FRS demographics — gender + age-range distribution from event attributes.
  const genderData = useMemo(() => {
    if (!isFrs) return [];
    const counts = new Map();
    eventsList.forEach((event) => {
      const gender = event?.attributes?.gender;
      if (!gender) return;
      const key = String(gender).toLowerCase();
      counts.set(key, (counts.get(key) || 0) + 1);
    });
    return Array.from(counts.entries()).map(([key, value]) => ({
      label: key.charAt(0).toUpperCase() + key.slice(1),
      value,
    }));
  }, [isFrs, eventsList]);

  const ageRangeData = useMemo(() => {
    if (!isFrs) return [];
    const counts = new Map();
    eventsList.forEach((event) => {
      const ageRange = event?.attributes?.age_range;
      if (!ageRange) return;
      const key = String(ageRange);
      counts.set(key, (counts.get(key) || 0) + 1);
    });
    return Array.from(counts.entries())
      .sort((a, b) => a[0].localeCompare(b[0], undefined, { numeric: true }))
      .map(([label, value]) => ({ label, value }));
  }, [isFrs, eventsList]);

  // FRS confidence histogram — bucket confidences (0..1) into percent ranges.
  const confidenceData = useMemo(() => {
    if (!isFrs) return [];
    const buckets = [
      { label: "<50%", min: 0, max: 0.5 },
      { label: "50-60%", min: 0.5, max: 0.6 },
      { label: "60-70%", min: 0.6, max: 0.7 },
      { label: "70-80%", min: 0.7, max: 0.8 },
      { label: "80-90%", min: 0.8, max: 0.9 },
      { label: "90-100%", min: 0.9, max: Infinity },
    ];
    const counts = new Array(buckets.length).fill(0);
    let any = false;
    eventsList.forEach((event) => {
      const c = event?.confidence;
      if (typeof c !== "number" || Number.isNaN(c)) return;
      any = true;
      const idx = buckets.findIndex((b) => c >= b.min && c < b.max);
      if (idx >= 0) counts[idx] += 1;
    });
    if (!any) return [];
    return buckets.map((b, i) => ({ label: b.label, value: counts[i] }));
  }, [isFrs, eventsList]);

  const hasDemographics = genderData.length > 0 || ageRangeData.length > 0;

  const scope = SCOPE_BY_SLUG[scenario?.slug] || DEFAULT_SCOPE;
  const scopeItems = useMemo(() => scenarioScopeItems(scenario), [scenario]);

  return (
    <div className="p-4 space-y-4">
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
        {isFetching && (
          <Loader2 className="h-4 w-4 animate-spin text-zinc-400 self-center" />
        )}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          icon={Activity}
          label="Scenario events"
          value={eventsLoading ? "—" : (pluginSummary?.results_total ?? events?.total ?? eventsList.length)}
          accent="text-blue-400"
        />
        <StatCard
          icon={Users}
          label="Assigned cameras"
          value={camerasLoading ? "—" : cameras.length}
          accent="text-emerald-400"
        />
        <StatCard
          icon={ShieldAlert}
          label={scope.activeLabel}
          value={camerasLoading ? "—" : enabledCount}
          accent="text-amber-400"
        />
        <StatCard
          icon={BarChart3}
          label={scenario?.slug === "suspect-search" ? "Qdrant points" : "Detection classes"}
          value={scenario?.slug === "suspect-search" ? (pluginSummary?.qdrant_points ?? 0) : scopeItems.length}
          accent="text-purple-400"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title="Events by camera" icon={BarChart3}>
          {eventsLoading ? (
            <div className="h-32 rounded animate-pulse bg-zinc-800/40" />
          ) : (
            <HBarChart
              data={byCameraData}
              color="#228B22"
              emptyLabel="No scenario events in this range yet."
            />
          )}
        </Panel>
        <Panel title={scope.scopeTitle} icon={Clock}>
          <div className="space-y-3 text-[12px] text-zinc-400">
            <p>{scope.blurb}</p>
            {scopeItems.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {scopeItems.map((item) => (
                  <span key={item} className="rounded border border-white/10 bg-black px-2 py-1 text-[11px] uppercase tracking-wide">
                    {String(item).replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            )}
            <p className="text-zinc-600">{scope.footnote}</p>
          </div>
        </Panel>
      </div>

      {scenario?.slug === "suspect-search" && pluginSummary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatCard icon={Briefcase} label="Jobs" value={pluginSummary.jobs_total ?? 0} accent="text-blue-400" />
          <StatCard icon={BarChart3} label="Indexed candidates" value={pluginSummary.indexed_candidates ?? 0} accent="text-emerald-400" />
          <StatCard icon={Activity} label="Model ready" value={pluginSummary.model_ready ? "yes" : "no"} accent={pluginSummary.model_ready ? "text-emerald-400" : "text-amber-400"} />
          <StatCard
            icon={ShieldAlert}
            label="Models present"
            value={`${(pluginSummary.detector_model_present ? 1 : 0) + (pluginSummary.reid_model_present ? 1 : 0)}/2`}
            accent="text-amber-400"
          />
        </div>
      )}

      {/* FRS recognition summary — counts + hourly distribution. */}
      {isFrs && pluginSummary && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard icon={Activity} label="Total events" value={pluginSummary.total_events ?? 0} accent="text-blue-400" />
            <StatCard icon={Users} label="Unique persons" value={pluginSummary.unique_persons ?? 0} accent="text-emerald-400" />
            <StatCard icon={ShieldAlert} label="Unknown" value={pluginSummary.unknown_count ?? 0} accent="text-amber-400" />
            <StatCard icon={ShieldAlert} label="Spoof" value={pluginSummary.spoof_count ?? 0} accent="text-rose-400" />
          </div>
          <Panel title="Events by hour" icon={Clock}>
            <HBarChart data={byHourData} color="#3b82f6" emptyLabel="No events in this range yet." />
          </Panel>
        </>
      )}

      {/* FRS demographics — gender + age-range distribution from event attributes. */}
      {isFrs && hasDemographics && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Panel title="By gender" icon={Users}>
            <HBarChart data={genderData} color="#a855f7" emptyLabel="No gender data in this range yet." />
          </Panel>
          <Panel title="By age range" icon={BarChart3}>
            <HBarChart data={ageRangeData} color="#14b8a6" emptyLabel="No age data in this range yet." />
          </Panel>
        </div>
      )}

      {/* FRS confidence histogram — distribution of recognition confidence. */}
      {isFrs && confidenceData.length > 0 && (
        <Panel title="Confidence distribution" icon={BarChart3}>
          <HBarChart data={confidenceData} color="#f59e0b" emptyLabel="No confidence data in this range yet." />
        </Panel>
      )}
    </div>
  );
}
