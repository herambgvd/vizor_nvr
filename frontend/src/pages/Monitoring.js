// =============================================================================
// Monitoring — System resources & bandwidth dashboard
// =============================================================================

import React, { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Cpu,
  MemoryStick,
  HardDrive,
  Network,
  Activity,
  RefreshCw,
  AlertTriangle,
} from "lucide-react";
import {
  getResources,
  getResourceHistory,
  getBandwidthSummary,
  getBandwidthAlerts,
} from "../api/monitoring";
import { Button } from "../components/ui/button";
import { cn } from "../lib/utils";

const Monitoring = () => {
  const {
    data: resources,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ["monitoring-resources"],
    queryFn: getResources,
    refetchInterval: 5000,
  });

  const { data: history } = useQuery({
    queryKey: ["monitoring-history"],
    queryFn: () => getResourceHistory({ minutes: 60 }),
    refetchInterval: 30000,
  });

  const { data: rawBandwidth } = useQuery({
    queryKey: ["monitoring-bandwidth"],
    queryFn: getBandwidthSummary,
    refetchInterval: 10000,
  });

  const { data: bwAlerts = [] } = useQuery({
    queryKey: ["monitoring-bw-alerts"],
    queryFn: getBandwidthAlerts,
    refetchInterval: 30000,
  });

  // Backend returns dict {camera_id: {kbps, ...}} — normalize to array
  const bandwidth = useMemo(() => {
    if (!rawBandwidth) return [];
    if (Array.isArray(rawBandwidth)) return rawBandwidth;
    return Object.entries(rawBandwidth).map(([id, data]) => ({
      camera_id: id,
      kbps: data?.kbps ?? 0,
    }));
  }, [rawBandwidth]);

  // Backend returns flat keys: cpu_percent, memory_percent, etc.
  const cpu = resources?.cpu_percent ?? 0;
  const memPct = resources?.memory_percent ?? 0;
  const memUsed = resources?.memory_used_mb ?? 0;
  const memTotal = resources?.memory_total_mb ?? 0;
  const diskPct = resources?.disk_percent ?? 0;
  const diskUsed = resources?.disk_used_gb ?? 0;
  const diskTotal = resources?.disk_total_gb ?? 0;
  const netSent = resources?.network_sent_mbps ?? 0;
  const netRecv = resources?.network_recv_mbps ?? 0;

  return (
    <div className="p-8 h-full overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1
            className="text-3xl font-bold text-white tracking-tight"
            style={{ fontFamily: "Manrope, sans-serif" }}
          >
            Monitoring
          </h1>
          <p className="text-muted-foreground mt-1">
            Real-time system resource overview
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => refetch()}
          disabled={isLoading}
        >
          <RefreshCw
            className={`h-4 w-4 mr-2 ${isLoading ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </div>

      {/* Gauge cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <GaugeCard
          label="CPU Usage"
          value={cpu}
          max={100}
          unit="%"
          icon={Cpu}
          color="blue"
        />
        <GaugeCard
          label="Memory"
          value={memPct}
          max={100}
          unit="%"
          icon={MemoryStick}
          color="purple"
          sub={
            memTotal > 0
              ? `${fmt(memUsed)} / ${fmt(memTotal)} MB`
              : memUsed > 0
                ? `${fmt(memUsed)} MB used`
                : ""
          }
        />
        <GaugeCard
          label="Disk"
          value={diskPct}
          max={100}
          unit="%"
          icon={HardDrive}
          color="amber"
          sub={diskTotal > 0 ? `${fmt(diskUsed)} / ${fmt(diskTotal)} GB` : ""}
        />
        <GaugeCard
          label="Network I/O"
          value={netSent + netRecv}
          max={100}
          unit="Mbps"
          icon={Network}
          color="emerald"
          sub={`↑${fmt(netSent)} ↓${fmt(netRecv)} Mbps`}
        />
      </div>

      {/* History charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <HistoryCard
          title="CPU History (60 min)"
          history={history}
          accessor={(p) => p.cpu_percent ?? 0}
          color="#3B82F6"
        />
        <HistoryCard
          title="Memory History (60 min)"
          history={history}
          accessor={(p) => p.memory_percent ?? 0}
          color="#A855F7"
        />
      </div>

      {/* Bandwidth summary */}
      <div className="bg-card border border-border rounded-lg p-6">
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <Activity className="h-5 w-5 text-zinc-400" />
          Bandwidth per Camera
        </h2>
        {bandwidth.length > 0 ? (
          <div className="space-y-3">
            {bandwidth.map((entry) => (
              <div
                key={entry.camera_id}
                className="flex items-center justify-between text-sm"
              >
                <span className="text-zinc-200 font-medium font-mono text-xs">
                  {entry.camera_name || entry.camera_id}
                </span>
                <span className="text-muted-foreground">
                  {fmt(entry.kbps ?? 0)} kbps
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No bandwidth data available</p>
        )}
      </div>

      {/* Bandwidth alerts */}
      <div className="bg-card border border-border rounded-lg p-6">
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-amber-400" />
          Bandwidth Budget Alerts
          <span className="ml-auto text-xs text-zinc-500 font-normal">Last 24 h</span>
        </h2>
        {bwAlerts.length === 0 ? (
          <p className="text-sm text-muted-foreground">No bandwidth alerts in the last 24 hours.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-zinc-500 border-b border-border">
                  <th className="pb-2 font-medium">Time</th>
                  <th className="pb-2 font-medium">Camera</th>
                  <th className="pb-2 font-medium text-right">Current</th>
                  <th className="pb-2 font-medium text-right">Limit</th>
                  <th className="pb-2 font-medium text-right">Threshold</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {bwAlerts.map((a) => (
                  <tr key={a.id} className="text-zinc-300">
                    <td className="py-2 font-mono text-xs text-zinc-400">
                      {a.timestamp ? new Date(a.timestamp).toLocaleString() : "—"}
                    </td>
                    <td className="py-2">{a.camera_name || a.camera_id}</td>
                    <td className="py-2 text-right text-amber-400 font-mono">
                      {a.current_kbps != null ? `${a.current_kbps} kbps` : "—"}
                    </td>
                    <td className="py-2 text-right font-mono">
                      {a.limit_kbps != null ? `${a.limit_kbps} kbps` : "—"}
                    </td>
                    <td className="py-2 text-right font-mono">
                      {a.threshold_pct != null ? `${a.threshold_pct}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

// ---------- helpers ----------

const fmt = (v) => (typeof v === "number" ? v.toFixed(1) : "-");

const gaugeColors = {
  blue: { ring: "stroke-blue-500", bg: "bg-blue-50", text: "text-blue-600" },
  purple: {
    ring: "stroke-purple-500",
    bg: "bg-purple-50",
    text: "text-purple-600",
  },
  amber: {
    ring: "stroke-amber-500",
    bg: "bg-amber-50",
    text: "text-amber-600",
  },
  emerald: {
    ring: "stroke-emerald-500",
    bg: "bg-emerald-50",
    text: "text-emerald-600",
  },
};

const GaugeCard = ({ label, value, max, unit, icon: Icon, color, sub }) => {
  const c = gaugeColors[color] || gaugeColors.blue;
  const pct = Math.min((value / max) * 100, 100);
  const circum = 2 * Math.PI * 40;
  const offset = circum - (pct / 100) * circum;

  return (
    <div className="bg-card border border-border rounded-lg p-6 flex flex-col items-center">
      <div className="relative mb-3">
        <svg className="h-24 w-24 -rotate-90" viewBox="0 0 100 100">
          <circle
            cx="50"
            cy="50"
            r="40"
            fill="none"
            stroke="#e2e8f0"
            strokeWidth="8"
          />
          <circle
            cx="50"
            cy="50"
            r="40"
            fill="none"
            className={c.ring}
            strokeWidth="8"
            strokeDasharray={circum}
            strokeDashoffset={offset}
            strokeLinecap="round"
            style={{ transition: "stroke-dashoffset 0.6s ease" }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={cn("text-lg font-bold", c.text)}>
            {fmt(value)}
            {unit}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <div className={cn("p-1.5 rounded-md", c.bg)}>
          <Icon className={cn("h-4 w-4", c.text)} />
        </div>
        <span className="text-sm font-medium text-zinc-200">{label}</span>
      </div>
      {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
    </div>
  );
};

// ---------- mini chart ----------

const HistoryCard = ({ title, history, accessor, color }) => {
  const points = useMemo(() => {
    if (!Array.isArray(history) || history.length === 0) return [];
    return history.map((p, i) => ({ x: i, y: accessor(p) }));
  }, [history, accessor]);

  if (points.length === 0) {
    return (
      <div className="bg-card border border-border rounded-lg p-6">
        <h3 className="text-sm font-semibold text-zinc-200 mb-3">{title}</h3>
        <p className="text-sm text-muted-foreground">No history data</p>
      </div>
    );
  }

  const maxY = Math.max(...points.map((p) => p.y), 1);
  const w = 400;
  const h = 100;
  const pathD = points
    .map((p, i) => {
      const px = (p.x / (points.length - 1)) * w;
      const py = h - (p.y / maxY) * h;
      return `${i === 0 ? "M" : "L"}${px},${py}`;
    })
    .join(" ");

  return (
    <div className="bg-card border border-border rounded-lg p-6">
      <h3 className="text-sm font-semibold text-zinc-200 mb-3">{title}</h3>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-24">
        <path d={pathD} fill="none" stroke={color} strokeWidth="2" />
      </svg>
    </div>
  );
};

export default Monitoring;
