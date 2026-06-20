// =============================================================================
// AI · PPE Detect tab — live compliance overview.
//
// The PPE scenario runs compliance continuously on its assigned cameras and
// owns its own event store; it does NOT expose on-demand image/video detect
// endpoints. This view therefore surfaces the LIVE compliance picture:
//   • a summary strip (recent events, violations, compliant, compliance rate)
//     from the plugin report summary, and
//   • a live-updating feed of the most recent violations from /events.
// Both read through the generic scenario proxy (proxyScenario / plugin helpers)
// — no hardcoded scenario slug paths.
// =============================================================================

import React, { useEffect, useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  HardHat,
  ShieldAlert,
  ShieldCheck,
  Activity,
  BarChart3,
  ImageOff,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { formatDateTime } from "../../../lib/datetime";

import { getScenarioCameras } from "../../../api/frs";
import {
  listScenarioPluginEvents,
  scenarioReportsSummary,
  scenarioSnapshotUrl,
} from "../../../api/ai";
import { cn } from "../../../lib/utils";
import { cameraNameMap } from "./frsShared";

const FEED_LIMIT = 20;
const REFRESH_MS = 10000;

const EVENT_LABEL = {
  ppe_missing: "PPE Missing",
  ppe_removed: "PPE Restored",
  ppe_compliant: "Compliant",
};

function fmtTime(iso) {
  if (!iso) return "—";
  try { return formatDateTime(iso); } catch { return iso; }
}

function eventBadgeClass(type) {
  switch (type) {
    case "ppe_compliant":
      return "border-emerald-500/40 bg-emerald-500/15 text-emerald-300";
    case "ppe_removed":
      return "border-amber-500/40 bg-amber-500/15 text-amber-300";
    default:
      return "border-rose-500/40 bg-rose-500/15 text-rose-300";
  }
}

const cardStyle = { background: "var(--console-panel)", border: "1px solid var(--console-border)" };

function StatCard({ icon: Icon, label, value, accent }) {
  return (
    <div className="rounded-lg border p-4" style={cardStyle}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-telemetry">{label}</span>
        <Icon className={`h-4 w-4 ${accent}`} />
      </div>
      <div className="mt-2 text-2xl font-semibold text-zinc-100 font-telemetry">{value}</div>
    </div>
  );
}

// Authenticated plate/worker snapshot thumbnail through the scenario proxy.
function SnapshotThumb({ ev, slug }) {
  const [blobUrl, setBlobUrl] = useState(null);
  const path = ev.snapshot_path;
  const isPluginSnap = typeof path === "string" && path.startsWith("/snapshot");
  useEffect(() => {
    if (!isPluginSnap || !slug || !path) return undefined;
    let active = true;
    let obj = null;
    scenarioSnapshotUrl(slug, path).then((u) => {
      if (!active) { if (u) URL.revokeObjectURL(u); return; }
      obj = u;
      setBlobUrl(u);
    });
    return () => { active = false; if (obj) URL.revokeObjectURL(obj); };
  }, [isPluginSnap, slug, path]);

  if (!path || (isPluginSnap && !blobUrl)) {
    return (
      <div className="h-12 w-16 rounded flex items-center justify-center border" style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}>
        {isPluginSnap && path ? <Loader2 className="h-4 w-4 animate-spin text-zinc-500" /> : <ImageOff className="h-4 w-4 text-zinc-600" />}
      </div>
    );
  }
  return <img src={blobUrl} alt="snapshot" loading="lazy" className="h-12 w-16 rounded object-cover border" style={{ borderColor: "var(--console-border)" }} />;
}

export default function PPEDetectTab({ scenario }) {
  const slug = scenario?.slug || "ppe";
  const scenarioId = scenario?.id;

  const { data: cameras = [] } = useQuery({
    queryKey: ["frs", "scenario-cameras", scenarioId],
    queryFn: () => getScenarioCameras(scenarioId),
    enabled: !!scenarioId,
  });
  const camMap = useMemo(() => cameraNameMap(cameras), [cameras]);

  // Summary window: last 24h (today's live picture).
  const since = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return d.toISOString();
  }, []);

  const summaryQuery = useQuery({
    queryKey: ["ppe-live-summary", slug, since],
    queryFn: () => scenarioReportsSummary(slug, { since }),
    refetchInterval: REFRESH_MS,
    placeholderData: keepPreviousData,
  });

  // Recent violations feed — newest first, auto-refreshing.
  const feedQuery = useQuery({
    queryKey: ["ppe-live-feed", slug],
    queryFn: () => listScenarioPluginEvents(slug, { limit: FEED_LIMIT, offset: 0 }),
    refetchInterval: REFRESH_MS,
    placeholderData: keepPreviousData,
  });

  const summary = summaryQuery.data || {};
  const events = feedQuery.data?.items || [];
  const rate = summary.compliance_rate != null ? `${Math.round(summary.compliance_rate * 100)}%` : "—";

  return (
    <div className="p-6 h-full overflow-y-auto flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <HardHat className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
          <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            Live compliance · last 24 hours
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-zinc-500 font-telemetry">
          <RefreshCw className={cn("h-3 w-3", (summaryQuery.isFetching || feedQuery.isFetching) && "animate-spin")} />
          Auto-refresh
        </div>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard icon={Activity} label="Recent events" value={summaryQuery.isLoading ? "—" : (summary.total_events ?? 0)} accent="text-blue-400" />
        <StatCard icon={ShieldAlert} label="Violations" value={summaryQuery.isLoading ? "—" : (summary.violations ?? 0)} accent="text-rose-400" />
        <StatCard icon={ShieldCheck} label="Compliant" value={summaryQuery.isLoading ? "—" : (summary.compliant ?? 0)} accent="text-emerald-400" />
        <StatCard icon={BarChart3} label="Compliance rate" value={summaryQuery.isLoading ? "—" : rate} accent="text-purple-400" />
      </div>

      {/* Recent feed */}
      <section className="rounded-lg flex flex-col gap-3 p-4" style={cardStyle}>
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
          <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            Recent compliance events
          </span>
        </div>

        {feedQuery.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-14 rounded animate-pulse bg-zinc-800/50" />
            ))}
          </div>
        ) : feedQuery.isError ? (
          <p className="py-10 text-center text-sm text-rose-400">Couldn't load compliance events.</p>
        ) : events.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-12 rounded" style={{ border: "1px dashed var(--console-border)" }}>
            <HardHat className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
            <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
              No compliance events yet — they appear here as workers are checked
            </span>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {events.map((ev) => (
              <div
                key={ev.id}
                className="flex items-center gap-3 rounded p-2.5"
                style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
              >
                <SnapshotThumb ev={ev} slug={slug} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium", eventBadgeClass(ev.event_type))}>
                      {EVENT_LABEL[ev.event_type] || ev.event_type}
                    </span>
                    {ev.worker_track_id != null && (
                      <span className="font-telemetry text-[11px] text-zinc-400">Worker #{ev.worker_track_id}</span>
                    )}
                  </div>
                  {Array.isArray(ev.missing_items) && ev.missing_items.length > 0 && (
                    <div className="mt-1 font-telemetry text-[10px] uppercase tracking-widest text-rose-300">
                      Missing: {ev.missing_items.join(", ")}
                    </div>
                  )}
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[11px] text-zinc-400 font-telemetry whitespace-nowrap">{fmtTime(ev.triggered_at)}</div>
                  <div className="text-[10px] text-zinc-500 max-w-[160px] truncate">{camMap[ev.camera_id] || ev.camera_id || "—"}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
