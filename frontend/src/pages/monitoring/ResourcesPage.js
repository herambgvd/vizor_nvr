// =============================================================================
// ResourcesPage — /monitoring/resources
// =============================================================================
// CPU / Memory / Disk / Network gauges + 60-min history sparklines +
// per-camera bandwidth list. Dark-theme tokens throughout.
// =============================================================================

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Cpu,
  MemoryStick,
  HardDrive,
  Network,
  Activity,
  RefreshCw,
  Zap,
  Thermometer,
  MonitorCog,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Download,
  FileArchive,
} from "lucide-react";
import {
  getResources,
  getResourceHistory,
  getBandwidthSummary,
  getSystemInfo,
  getDiskHealth,
} from "../../api/monitoring";
import { downloadDiagnosticsBundle } from "../../api/system";
import { useAuth } from "../../context/AuthContext";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";

const fmt = (v) => (typeof v === "number" ? v.toFixed(1) : "—");

// Severity coloring based on percent
const tone = (pct) => {
  if (pct >= 85) return "rose";
  if (pct >= 65) return "amber";
  return "teal";
};

const TONES = {
  teal: {
    ring: "stroke-teal-400",
    text: "text-teal-300",
    icon: "text-teal-300",
    iconBg: "bg-teal-500/15",
  },
  amber: {
    ring: "stroke-amber-400",
    text: "text-amber-300",
    icon: "text-amber-300",
    iconBg: "bg-amber-500/15",
  },
  rose: {
    ring: "stroke-rose-400",
    text: "text-rose-300",
    icon: "text-rose-300",
    iconBg: "bg-rose-500/15",
  },
  blue: {
    ring: "stroke-blue-400",
    text: "text-blue-300",
    icon: "text-blue-300",
    iconBg: "bg-blue-500/15",
  },
};

const GaugeCard = ({ label, value, max, unit, icon: Icon, color, sub }) => {
  const c = TONES[color] || TONES.teal;
  const pct = Math.min((value / max) * 100, 100);
  const circum = 2 * Math.PI * 40;
  const offset = circum - (pct / 100) * circum;

  return (
    <div className="rounded-lg border border-border bg-card/40 p-5 flex flex-col items-center">
      <div className="relative mb-3">
        <svg className="h-24 w-24 -rotate-90" viewBox="0 0 100 100">
          <circle
            cx="50"
            cy="50"
            r="40"
            fill="none"
            className="stroke-white/10"
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
          <span className={cn("text-lg font-bold tabular-nums", c.text)}>
            {fmt(value)}
            {unit}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <div className={cn("p-1.5 rounded-md", c.iconBg)}>
          <Icon className={cn("h-4 w-4", c.icon)} />
        </div>
        <span className="text-sm font-medium">{label}</span>
      </div>
      {sub && (
        <p className="text-[11px] text-muted-foreground mt-1 font-mono">{sub}</p>
      )}
    </div>
  );
};

const HistoryCard = ({ title, history, accessor, stroke }) => {
  const points = useMemo(() => {
    if (!Array.isArray(history) || history.length === 0) return [];
    return history.map((p, i) => ({ x: i, y: accessor(p) }));
  }, [history, accessor]);

  if (points.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card/40 p-5">
        <h3 className="text-sm font-semibold mb-3">{title}</h3>
        <p className="text-sm text-muted-foreground">No history data</p>
      </div>
    );
  }

  const maxY = Math.max(...points.map((p) => p.y), 1);
  const w = 400;
  const h = 100;
  const pathD = points
    .map((p, i) => {
      const px = (p.x / Math.max(points.length - 1, 1)) * w;
      const py = h - (p.y / maxY) * h;
      return `${i === 0 ? "M" : "L"}${px},${py}`;
    })
    .join(" ");
  const areaD = `${pathD} L${w},${h} L0,${h} Z`;
  const last = points[points.length - 1]?.y ?? 0;

  return (
    <div className="rounded-lg border border-border bg-card/40 p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="text-xs text-muted-foreground font-mono">
          now: {fmt(last)}%
        </span>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-24" preserveAspectRatio="none">
        <path d={areaD} fill={stroke} fillOpacity="0.12" />
        <path d={pathD} fill="none" stroke={stroke} strokeWidth="2" />
      </svg>
    </div>
  );
};

// SMART status pill
const SmartPill = ({ status }) => {
  if (status === "ok")
    return (
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium bg-teal-500/15 text-teal-300">
        <CheckCircle className="h-3 w-3" /> OK
      </span>
    );
  if (status === "warning")
    return (
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium bg-amber-500/15 text-amber-300">
        <AlertTriangle className="h-3 w-3" /> Warning
      </span>
    );
  if (status === "fail")
    return (
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium bg-rose-500/15 text-rose-300">
        <XCircle className="h-3 w-3" /> Fail
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium bg-zinc-500/15 text-zinc-400">
      Unknown
    </span>
  );
};

const fmtBytes = (b) => {
  if (!b) return "—";
  if (b >= 1e12) return `${(b / 1e12).toFixed(1)} TB`;
  if (b >= 1e9) return `${(b / 1e9).toFixed(1)} GB`;
  return `${(b / 1e6).toFixed(0)} MB`;
};

const DiskCard = ({ disk }) => {
  const pct = disk.used_pct || 0;
  const barColor =
    pct >= 90 ? "bg-rose-400" : pct >= 75 ? "bg-amber-400" : "bg-teal-400";

  return (
    <div className="rounded-lg border border-border bg-card/40 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-mono text-zinc-200 truncate">
            {disk.mount_path || disk.device || "—"}
          </p>
          <p className="text-[11px] text-muted-foreground font-mono truncate">
            {disk.device !== disk.mount_path ? disk.device : ""}
            {disk.filesystem ? ` · ${disk.filesystem}` : ""}
          </p>
        </div>
        <SmartPill status={disk.smart_status} />
      </div>

      {/* Usage bar */}
      {disk.total_bytes > 0 && (
        <div>
          <div className="flex items-center justify-between text-[11px] text-muted-foreground mb-1">
            <span>{fmtBytes(disk.used_bytes)} used</span>
            <span>{fmtBytes(disk.free_bytes)} free / {fmtBytes(disk.total_bytes)}</span>
          </div>
          <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
            <div
              className={cn("h-full transition-all", barColor)}
              style={{ width: `${Math.min(pct, 100)}%` }}
            />
          </div>
          <p className="text-[11px] text-right text-muted-foreground mt-0.5">
            {pct.toFixed(1)}%
          </p>
        </div>
      )}

      {/* SMART details */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
        {disk.model && (
          <>
            <span className="text-muted-foreground">Model</span>
            <span className="font-mono truncate">{disk.model}</span>
          </>
        )}
        {disk.temp_c != null && (
          <>
            <span className="text-muted-foreground flex items-center gap-1">
              <Thermometer className="h-3 w-3" />Temp
            </span>
            <span
              className={cn(
                "font-mono",
                disk.temp_c >= 65 ? "text-rose-300" : disk.temp_c >= 50 ? "text-amber-300" : "",
              )}
            >
              {disk.temp_c}°C
            </span>
          </>
        )}
        {disk.reallocated_sectors != null && (
          <>
            <span className="text-muted-foreground">Reallocated</span>
            <span
              className={cn(
                "font-mono",
                disk.reallocated_sectors >= 50
                  ? "text-rose-300"
                  : disk.reallocated_sectors >= 1
                    ? "text-amber-300"
                    : "",
              )}
            >
              {disk.reallocated_sectors}
            </span>
          </>
        )}
        {disk.power_on_hours != null && (
          <>
            <span className="text-muted-foreground">Power-on hrs</span>
            <span className="font-mono">{disk.power_on_hours.toLocaleString()}</span>
          </>
        )}
      </div>

      {/* Alerts */}
      {disk.alerts && disk.alerts.length > 0 && (
        <div className="space-y-1">
          {disk.alerts.map((alert, i) => (
            <div
              key={i}
              className="flex items-start gap-1.5 text-[11px] text-amber-300"
            >
              <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" />
              {alert}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ─── Diagnostics card ─────────────────────────────────────────────────────────

const DiagnosticsCard = () => {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState(null);

  const handleDownload = async () => {
    setDownloading(true);
    setError(null);
    try {
      const blob = await downloadDiagnosticsBundle();
      const now = new Date();
      const ts = now.toISOString().replace(/[-:T]/g, "").slice(0, 15);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `gvd-nvr-diagnostics-${ts}.tar.gz`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Download failed");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card/40">
      <div className="flex items-center gap-2 px-5 py-3 border-b border-white/5">
        <FileArchive className="h-4 w-4 text-teal-300" />
        <h2 className="text-sm font-semibold">Diagnostics</h2>
      </div>
      <div className="p-5 space-y-3">
        <p className="text-sm text-muted-foreground">
          Download a support bundle for troubleshooting. The archive contains
          system manifest, sanitized config files, the last 5 000 log lines,
          camera inventory (ONVIF passwords stripped), audit log (last 7 days),
          disk health, and hardware acceleration status.
        </p>
        <p className="text-[11px] text-amber-300 flex items-start gap-1.5">
          <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" />
          The bundle may contain sensitive information such as host paths and
          IP addresses. Share only with trusted support personnel.
        </p>
        {error && (
          <p className="text-[11px] text-rose-300">{error}</p>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={handleDownload}
          disabled={downloading}
        >
          <Download className={cn("h-4 w-4 mr-2", downloading && "animate-pulse")} />
          {downloading ? "Preparing bundle…" : "Download support bundle"}
        </Button>
        <p className="text-[11px] text-muted-foreground">
          Estimated size: 50 KB – 2 MB depending on log volume.
        </p>
      </div>
    </div>
  );
};

// ─── Main page ────────────────────────────────────────────────────────────────

const ResourcesPage = () => {
  const { isAdmin } = useAuth();
  const { data: resources, isLoading, refetch } = useQuery({
    queryKey: ["monitoring-resources"],
    queryFn: getResources,
    refetchInterval: 5_000,
  });

  const { data: sysInfo } = useQuery({
    queryKey: ["monitoring-system-info"],
    queryFn: getSystemInfo,
    staleTime: 5 * 60_000,
  });

  const { data: history } = useQuery({
    queryKey: ["monitoring-history"],
    queryFn: () => getResourceHistory({ minutes: 60 }),
    refetchInterval: 30_000,
  });

  const { data: rawBandwidth } = useQuery({
    queryKey: ["monitoring-bandwidth"],
    queryFn: getBandwidthSummary,
    refetchInterval: 10_000,
  });

  const { data: diskData } = useQuery({
    queryKey: ["monitoring-disks"],
    queryFn: getDiskHealth,
    refetchInterval: 60_000,
    enabled: isAdmin,
  });

  const bandwidth = useMemo(() => {
    if (!rawBandwidth) return [];
    if (Array.isArray(rawBandwidth)) return rawBandwidth;
    return Object.entries(rawBandwidth).map(([id, data]) => ({
      camera_id: id,
      camera_name: data?.camera_name,
      kbps: data?.kbps ?? 0,
    }));
  }, [rawBandwidth]);

  const cpu = resources?.cpu_percent ?? 0;
  const cpuFreq = resources?.cpu_freq_mhz ?? 0;
  const cpuPerCore = resources?.cpu_per_core ?? [];
  const gpuPct = resources?.gpu_percent ?? 0;
  const gpuMemPct = resources?.gpu_mem_percent ?? 0;
  const gpuMemUsed = resources?.gpu_mem_used_mb ?? 0;
  const gpuMemTotal = resources?.gpu_mem_total_mb ?? 0;
  const gpuTemp = resources?.gpu_temp_c ?? 0;
  const memPct = resources?.memory_percent ?? 0;
  const memUsed = resources?.memory_used_mb ?? 0;
  const memTotal = resources?.memory_total_mb ?? 0;
  const diskPct = resources?.disk_percent ?? 0;
  const diskUsed = resources?.disk_used_gb ?? 0;
  const diskTotal = resources?.disk_total_gb ?? 0;
  const netSent = resources?.network_sent_mbps ?? 0;
  const netRecv = resources?.network_recv_mbps ?? 0;
  const netTotal = netSent + netRecv;

  return (
    <div className="p-4 md:p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Live Resources
        </h2>
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isLoading}
        >
          <RefreshCw
            className={cn("h-4 w-4 mr-2", isLoading && "animate-spin")}
          />
          Refresh
        </Button>
      </div>

      {/* Gauges */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <GaugeCard
          label="CPU Usage"
          value={cpu}
          max={100}
          unit="%"
          icon={Cpu}
          color={tone(cpu)}
        />
        <GaugeCard
          label="Memory"
          value={memPct}
          max={100}
          unit="%"
          icon={MemoryStick}
          color={tone(memPct)}
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
          color={tone(diskPct)}
          sub={diskTotal > 0 ? `${fmt(diskUsed)} / ${fmt(diskTotal)} GB` : ""}
        />
        <GaugeCard
          label="Network I/O"
          value={netTotal}
          max={Math.max(100, netTotal * 1.2)}
          unit=" Mbps"
          icon={Network}
          color="blue"
          sub={`↑${fmt(netSent)}  ↓${fmt(netRecv)} Mbps`}
        />
      </div>

      {/* CPU + GPU detail */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* CPU detail */}
        <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 border-b border-white/5">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <Cpu className="h-4 w-4 text-teal-300" />
              CPU Details
            </h2>
            <span className="text-xs text-muted-foreground font-mono tabular-nums">
              {fmt(cpu)}% · {cpuFreq > 0 ? `${Math.round(cpuFreq)} MHz` : "—"}
            </span>
          </div>
          <div className="p-5 space-y-3">
            <div className="text-xs space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Model</span>
                <span className="font-mono truncate max-w-[60%] text-right">
                  {sysInfo?.cpu_model || "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Cores</span>
                <span className="font-mono">
                  {sysInfo?.cpu_cores_physical ?? "—"} physical ·{" "}
                  {sysInfo?.cpu_cores_logical ?? "—"} logical
                </span>
              </div>
              {sysInfo?.cpu_freq_max_mhz && (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Max freq</span>
                  <span className="font-mono">
                    {Math.round(sysInfo.cpu_freq_max_mhz)} MHz
                  </span>
                </div>
              )}
              {sysInfo?.platform && (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">OS</span>
                  <span className="font-mono">{sysInfo.platform}</span>
                </div>
              )}
            </div>

            {/* Per-core mini bars */}
            {cpuPerCore.length > 0 && (
              <div className="pt-2">
                <p className="text-[11px] text-muted-foreground mb-1.5 uppercase tracking-wider">
                  Per-core usage
                </p>
                <div className="grid grid-cols-8 gap-1">
                  {cpuPerCore.map((p, i) => {
                    const t = tone(p);
                    const bar =
                      t === "rose"
                        ? "bg-rose-400"
                        : t === "amber"
                          ? "bg-amber-400"
                          : "bg-teal-400";
                    return (
                      <div key={i} className="flex flex-col items-center gap-0.5">
                        <div className="h-10 w-full bg-white/5 rounded-sm overflow-hidden flex items-end">
                          <div
                            className={cn("w-full transition-all", bar)}
                            style={{ height: `${Math.min(p, 100)}%` }}
                          />
                        </div>
                        <span className="text-[9px] text-muted-foreground font-mono">
                          {i}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* GPU detail */}
        <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 border-b border-white/5">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <Zap className="h-4 w-4 text-teal-300" />
              GPU Details
            </h2>
            {sysInfo?.gpus?.length > 0 && (
              <span className="text-xs text-muted-foreground font-mono tabular-nums">
                {fmt(gpuPct)}%
              </span>
            )}
          </div>
          <div className="p-5">
            {!sysInfo?.gpus || sysInfo.gpus.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-6 text-center">
                <MonitorCog className="h-8 w-8 text-muted-foreground/40 mb-2" />
                <p className="text-sm text-muted-foreground">
                  No GPU detected
                </p>
                <p className="text-[11px] text-muted-foreground/70 mt-1">
                  NVIDIA driver + pynvml required
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {sysInfo.gpus.map((g) => (
                  <div key={g.index} className="space-y-2">
                    <div className="text-xs space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Model</span>
                        <span className="font-mono">{g.name}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Memory</span>
                        <span className="font-mono">
                          {fmt(gpuMemUsed)} / {fmt(g.memory_total_mb)} MB ({fmt(gpuMemPct)}%)
                        </span>
                      </div>
                      {g.driver_version && (
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Driver</span>
                          <span className="font-mono">{g.driver_version}</span>
                        </div>
                      )}
                      {gpuTemp > 0 && (
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground flex items-center gap-1">
                            <Thermometer className="h-3 w-3" />
                            Temp
                          </span>
                          <span
                            className={cn(
                              "font-mono",
                              gpuTemp >= 85
                                ? "text-rose-300"
                                : gpuTemp >= 70
                                  ? "text-amber-300"
                                  : "",
                            )}
                          >
                            {fmt(gpuTemp)}°C
                          </span>
                        </div>
                      )}
                    </div>

                    {/* GPU + VRAM bars */}
                    <div className="pt-1 space-y-2">
                      <div>
                        <div className="flex items-center justify-between text-[11px] text-muted-foreground mb-1">
                          <span>Utilization</span>
                          <span className="font-mono">{fmt(gpuPct)}%</span>
                        </div>
                        <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                          <div
                            className={cn(
                              "h-full transition-all",
                              gpuPct >= 85
                                ? "bg-rose-400"
                                : gpuPct >= 65
                                  ? "bg-amber-400"
                                  : "bg-teal-400",
                            )}
                            style={{ width: `${Math.min(gpuPct, 100)}%` }}
                          />
                        </div>
                      </div>
                      <div>
                        <div className="flex items-center justify-between text-[11px] text-muted-foreground mb-1">
                          <span>VRAM</span>
                          <span className="font-mono">{fmt(gpuMemPct)}%</span>
                        </div>
                        <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                          <div
                            className={cn(
                              "h-full transition-all",
                              gpuMemPct >= 85
                                ? "bg-rose-400"
                                : gpuMemPct >= 65
                                  ? "bg-amber-400"
                                  : "bg-blue-400",
                            )}
                            style={{ width: `${Math.min(gpuMemPct, 100)}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* History */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <HistoryCard
          title="CPU (60 min)"
          history={history}
          accessor={(p) => p.cpu_percent ?? 0}
          stroke="#14B8A6"
        />
        <HistoryCard
          title="Memory (60 min)"
          history={history}
          accessor={(p) => p.memory_percent ?? 0}
          stroke="#3B82F6"
        />
      </div>

      {/* Bandwidth */}
      <div className="rounded-lg border border-border bg-card/40">
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/5">
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <Activity className="h-4 w-4 text-teal-300" />
            Bandwidth per Camera
          </h2>
          <span className="text-xs text-muted-foreground">
            {bandwidth.length} {bandwidth.length === 1 ? "camera" : "cameras"}
          </span>
        </div>
        {bandwidth.length > 0 ? (
          <ul className="divide-y divide-white/5">
            {bandwidth.map((entry) => (
              <li
                key={entry.camera_id}
                className="flex items-center justify-between px-5 py-2.5 text-sm"
              >
                <span className="font-mono text-xs text-zinc-300 truncate max-w-[60%]">
                  {entry.camera_name || entry.camera_id}
                </span>
                <span className="text-muted-foreground font-mono tabular-nums">
                  {fmt(entry.kbps ?? 0)} kbps
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-5 py-6 text-sm text-muted-foreground">
            No bandwidth data available
          </p>
        )}
      </div>

      {/* Storage Health — admin only */}
      {isAdmin && (
        <div className="rounded-lg border border-border bg-card/40">
          <div className="flex items-center justify-between px-5 py-3 border-b border-white/5">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <HardDrive className="h-4 w-4 text-teal-300" />
              Storage Health
            </h2>
            <span className="text-xs text-muted-foreground">
              {diskData?.disks?.length ?? 0}{" "}
              {(diskData?.disks?.length ?? 0) === 1 ? "volume" : "volumes"}
            </span>
          </div>
          {diskData?.disks?.length > 0 ? (
            <div className="p-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {diskData.disks.map((disk, i) => (
                <DiskCard key={`${disk.device}-${i}`} disk={disk} />
              ))}
            </div>
          ) : (
            <p className="px-5 py-6 text-sm text-muted-foreground">
              {diskData ? "No volumes found" : "Loading disk health…"}
            </p>
          )}
        </div>
      )}

      {/* Diagnostics — admin only */}
      {isAdmin && <DiagnosticsCard />}
    </div>
  );
};

export default ResourcesPage;
