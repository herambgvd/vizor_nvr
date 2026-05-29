// =============================================================================
// ResourcesPage — /monitoring/resources
// =============================================================================
// CPU / Memory / Disk / Network gauges + 60-min history sparklines +
// per-camera bandwidth list. Console OLED theme throughout.
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
import { cn } from "../../lib/utils";

const fmt = (v) => (typeof v === "number" ? v.toFixed(1) : "—");

// Severity coloring based on percent — returns CSS var strings
const toneColor = (pct) => {
  if (pct >= 85) return "var(--console-rec)";
  if (pct >= 65) return "var(--console-alarm)";
  return "var(--console-accent)";
};

const GaugeCard = ({ label, value, max, unit, icon: Icon, sub }) => {
  const pct = Math.min((value / max) * 100, 100);
  const circum = 2 * Math.PI * 40;
  const offset = circum - (pct / 100) * circum;
  const color = toneColor(pct);

  return (
    <div
      className="rounded border p-5 flex flex-col items-center"
      style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
    >
      <div className="relative mb-3">
        <svg className="h-24 w-24 -rotate-90" viewBox="0 0 100 100">
          <circle
            cx="50"
            cy="50"
            r="40"
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth="8"
          />
          <circle
            cx="50"
            cy="50"
            r="40"
            fill="none"
            stroke={color}
            strokeWidth="8"
            strokeDasharray={circum}
            strokeDashoffset={offset}
            strokeLinecap="round"
            style={{ transition: "stroke-dashoffset 0.6s ease" }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="font-telemetry text-lg font-bold tabular-nums" style={{ color }}>
            {fmt(value)}{unit}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <div className="p-1.5 rounded-md" style={{ background: "rgba(255,255,255,0.05)" }}>
          <Icon className="h-4 w-4" style={{ color }} />
        </div>
        <span className="font-telemetry text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
          {label}
        </span>
      </div>
      {sub && (
        <p className="font-telemetry text-[11px] mt-1 tabular-nums" style={{ color: "var(--console-muted)" }}>
          {sub}
        </p>
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
      <div
        className="rounded border p-5"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        <p className="font-telemetry text-xs font-semibold uppercase tracking-wide mb-3" style={{ color: "var(--console-text)" }}>
          {title}
        </p>
        <p className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>
          No history data
        </p>
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
    <div
      className="rounded border p-5"
      style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
    >
      <div className="flex items-center justify-between mb-3">
        <p className="font-telemetry text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
          {title}
        </p>
        <span className="font-telemetry text-[11px] tabular-nums" style={{ color: "var(--console-muted)" }}>
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
      <span
        className="inline-flex items-center gap-1 rounded px-2 py-0.5 font-telemetry text-[11px] font-medium border"
        style={{ background: "rgba(20,184,166,0.12)", color: "var(--console-accent)", borderColor: "rgba(20,184,166,0.3)" }}
      >
        <CheckCircle className="h-3 w-3" /> OK
      </span>
    );
  if (status === "warning")
    return (
      <span
        className="inline-flex items-center gap-1 rounded px-2 py-0.5 font-telemetry text-[11px] font-medium border"
        style={{ background: "rgba(245,158,11,0.12)", color: "var(--console-alarm)", borderColor: "rgba(245,158,11,0.3)" }}
      >
        <AlertTriangle className="h-3 w-3" /> Warning
      </span>
    );
  if (status === "fail")
    return (
      <span
        className="inline-flex items-center gap-1 rounded px-2 py-0.5 font-telemetry text-[11px] font-medium border"
        style={{ background: "rgba(239,68,68,0.12)", color: "var(--console-rec)", borderColor: "rgba(239,68,68,0.3)" }}
      >
        <XCircle className="h-3 w-3" /> Fail
      </span>
    );
  return (
    <span
      className="inline-flex items-center gap-1 rounded px-2 py-0.5 font-telemetry text-[11px] font-medium border"
      style={{ background: "var(--console-raised)", color: "var(--console-muted)", borderColor: "var(--console-border)" }}
    >
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
  const barColor = pct >= 90 ? "var(--console-rec)" : pct >= 75 ? "var(--console-alarm)" : "var(--console-accent)";

  return (
    <div
      className="rounded border p-4 space-y-3"
      style={{ background: "var(--console-raised)", borderColor: "var(--console-border)" }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-telemetry text-xs truncate" style={{ color: "var(--console-text)" }}>
            {disk.mount_path || disk.device || "—"}
          </p>
          <p className="font-telemetry text-[11px] truncate" style={{ color: "var(--console-muted)" }}>
            {disk.device !== disk.mount_path ? disk.device : ""}
            {disk.filesystem ? ` · ${disk.filesystem}` : ""}
          </p>
        </div>
        <SmartPill status={disk.smart_status} />
      </div>

      {/* Usage bar */}
      {disk.total_bytes > 0 && (
        <div>
          <div className="flex items-center justify-between font-telemetry text-[11px] mb-1" style={{ color: "var(--console-muted)" }}>
            <span>{fmtBytes(disk.used_bytes)} used</span>
            <span>{fmtBytes(disk.free_bytes)} free / {fmtBytes(disk.total_bytes)}</span>
          </div>
          <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.05)" }}>
            <div
              className="h-full transition-all"
              style={{ width: `${Math.min(pct, 100)}%`, background: barColor }}
            />
          </div>
          <p className="font-telemetry text-[11px] text-right mt-0.5" style={{ color: "var(--console-muted)" }}>
            {pct.toFixed(1)}%
          </p>
        </div>
      )}

      {/* SMART details */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 font-telemetry text-[11px]">
        {disk.model && (
          <>
            <span style={{ color: "var(--console-muted)" }}>Model</span>
            <span className="truncate" style={{ color: "var(--console-text)" }}>{disk.model}</span>
          </>
        )}
        {disk.temp_c != null && (
          <>
            <span className="flex items-center gap-1" style={{ color: "var(--console-muted)" }}>
              <Thermometer className="h-3 w-3" />Temp
            </span>
            <span
              style={{
                color: disk.temp_c >= 65
                  ? "var(--console-rec)"
                  : disk.temp_c >= 50
                    ? "var(--console-alarm)"
                    : "var(--console-text)",
              }}
            >
              {disk.temp_c}°C
            </span>
          </>
        )}
        {disk.reallocated_sectors != null && (
          <>
            <span style={{ color: "var(--console-muted)" }}>Reallocated</span>
            <span
              style={{
                color: disk.reallocated_sectors >= 50
                  ? "var(--console-rec)"
                  : disk.reallocated_sectors >= 1
                    ? "var(--console-alarm)"
                    : "var(--console-text)",
              }}
            >
              {disk.reallocated_sectors}
            </span>
          </>
        )}
        {disk.power_on_hours != null && (
          <>
            <span style={{ color: "var(--console-muted)" }}>Power-on hrs</span>
            <span style={{ color: "var(--console-text)" }}>{disk.power_on_hours.toLocaleString()}</span>
          </>
        )}
      </div>

      {/* Alerts */}
      {disk.alerts && disk.alerts.length > 0 && (
        <div className="space-y-1">
          {disk.alerts.map((alert, i) => (
            <div
              key={i}
              className="flex items-start gap-1.5 font-telemetry text-[11px]"
              style={{ color: "var(--console-alarm)" }}
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

// ─── Shared primitives ────────────────────────────────────────────────────────

const SectionHeader = ({ icon: Icon, label, right }) => (
  <div
    className="flex items-center justify-between px-4 py-2.5 border-b"
    style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
  >
    <div className="flex items-center gap-3">
      <span className="w-0.5 h-4 rounded-full flex-shrink-0" style={{ background: "var(--console-accent)" }} />
      {Icon && <Icon className="h-3.5 w-3.5 flex-shrink-0" style={{ color: "var(--console-accent)" }} />}
      <span className="font-telemetry text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--console-text)" }}>
        {label}
      </span>
    </div>
    {right && <div>{right}</div>}
  </div>
);

const SecondaryBtn = ({ children, disabled, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    className="inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] border transition-colors hover:bg-white/5 disabled:opacity-50"
    style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}
  >
    {children}
  </button>
);

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
    <div className="rounded border overflow-hidden" style={{ borderColor: "var(--console-border)" }}>
      <SectionHeader icon={FileArchive} label="Diagnostics" />
      <div className="p-4 space-y-3" style={{ background: "var(--console-panel)" }}>
        <p className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>
          Download a support bundle for troubleshooting. The archive contains
          system manifest, sanitized config files, the last 5 000 log lines,
          camera inventory (ONVIF passwords stripped), audit log (last 7 days),
          disk health, and hardware acceleration status.
        </p>
        <p className="font-telemetry text-[11px] flex items-start gap-1.5" style={{ color: "var(--console-alarm)" }}>
          <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" />
          The bundle may contain sensitive information such as host paths and
          IP addresses. Share only with trusted support personnel.
        </p>
        {error && (
          <p className="font-telemetry text-[11px]" style={{ color: "var(--console-rec)" }}>{error}</p>
        )}
        <SecondaryBtn onClick={handleDownload} disabled={downloading}>
          <Download className={cn("h-3.5 w-3.5 mr-1.5", downloading && "animate-pulse")} />
          {downloading ? "Preparing bundle…" : "Download support bundle"}
        </SecondaryBtn>
        <p className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
          Estimated size: 50 KB – 2 MB depending on log volume.
        </p>
      </div>
    </div>
  );
};

// ─── Detail panel wrapper ─────────────────────────────────────────────────────

const DetailPanel = ({ icon: Icon, label, right, children }) => (
  <div className="rounded border overflow-hidden" style={{ borderColor: "var(--console-border)" }}>
    <SectionHeader icon={Icon} label={label} right={right} />
    <div className="p-4 space-y-3" style={{ background: "var(--console-panel)" }}>
      {children}
    </div>
  </div>
);

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
    <div className="p-4 space-y-4">
      {/* Section header bar */}
      <div
        className="flex items-center gap-3 px-4 py-2.5 rounded border"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        <span className="w-0.5 h-4 rounded-full flex-shrink-0" style={{ background: "var(--console-accent)" }} />
        <span className="font-telemetry text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--console-text)" }}>
          Live Resources
        </span>
        <div className="flex-1" />
        <SecondaryBtn onClick={() => refetch()} disabled={isLoading}>
          <RefreshCw className={cn("h-3.5 w-3.5 mr-1.5", isLoading && "animate-spin")} />
          Refresh
        </SecondaryBtn>
      </div>

      {/* Gauges */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <GaugeCard
          label="CPU Usage"
          value={cpu}
          max={100}
          unit="%"
          icon={Cpu}
        />
        <GaugeCard
          label="Memory"
          value={memPct}
          max={100}
          unit="%"
          icon={MemoryStick}
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
          sub={diskTotal > 0 ? `${fmt(diskUsed)} / ${fmt(diskTotal)} GB` : ""}
        />
        <GaugeCard
          label="Network I/O"
          value={netTotal}
          max={Math.max(100, netTotal * 1.2)}
          unit=" Mbps"
          icon={Network}
          sub={`↑${fmt(netSent)}  ↓${fmt(netRecv)} Mbps`}
        />
      </div>

      {/* CPU + GPU detail */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* CPU detail */}
        <DetailPanel
          icon={Cpu}
          label="CPU Details"
          right={
            <span className="font-telemetry text-[11px] tabular-nums" style={{ color: "var(--console-muted)" }}>
              {fmt(cpu)}% · {cpuFreq > 0 ? `${Math.round(cpuFreq)} MHz` : "—"}
            </span>
          }
        >
          <div className="font-telemetry text-[11px] space-y-1.5">
            <div className="flex items-center justify-between">
              <span style={{ color: "var(--console-muted)" }}>Model</span>
              <span className="truncate max-w-[60%] text-right" style={{ color: "var(--console-text)" }}>
                {sysInfo?.cpu_model || "—"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span style={{ color: "var(--console-muted)" }}>Cores</span>
              <span style={{ color: "var(--console-text)" }}>
                {sysInfo?.cpu_cores_physical ?? "—"} physical ·{" "}
                {sysInfo?.cpu_cores_logical ?? "—"} logical
              </span>
            </div>
            {sysInfo?.cpu_freq_max_mhz && (
              <div className="flex items-center justify-between">
                <span style={{ color: "var(--console-muted)" }}>Max freq</span>
                <span style={{ color: "var(--console-text)" }}>
                  {Math.round(sysInfo.cpu_freq_max_mhz)} MHz
                </span>
              </div>
            )}
            {sysInfo?.platform && (
              <div className="flex items-center justify-between">
                <span style={{ color: "var(--console-muted)" }}>OS</span>
                <span style={{ color: "var(--console-text)" }}>{sysInfo.platform}</span>
              </div>
            )}
          </div>

          {/* Per-core mini bars */}
          {cpuPerCore.length > 0 && (
            <div className="pt-2">
              <p className="font-telemetry text-[10px] uppercase tracking-wider mb-1.5" style={{ color: "var(--console-muted)" }}>
                Per-core usage
              </p>
              <div className="grid grid-cols-8 gap-1">
                {cpuPerCore.map((p, i) => {
                  const barColor = toneColor(p);
                  return (
                    <div key={i} className="flex flex-col items-center gap-0.5">
                      <div
                        className="h-10 w-full rounded-sm overflow-hidden flex items-end"
                        style={{ background: "rgba(255,255,255,0.05)" }}
                      >
                        <div
                          className="w-full transition-all"
                          style={{ height: `${Math.min(p, 100)}%`, background: barColor }}
                        />
                      </div>
                      <span className="font-telemetry text-[9px]" style={{ color: "var(--console-muted)" }}>
                        {i}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </DetailPanel>

        {/* GPU detail */}
        <DetailPanel
          icon={Zap}
          label="GPU Details"
          right={
            sysInfo?.gpus?.length > 0 ? (
              <span className="font-telemetry text-[11px] tabular-nums" style={{ color: "var(--console-muted)" }}>
                {fmt(gpuPct)}%
              </span>
            ) : null
          }
        >
          {!sysInfo?.gpus || sysInfo.gpus.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-6 text-center">
              <MonitorCog className="h-8 w-8 mb-2 opacity-20" style={{ color: "var(--console-muted)" }} />
              <p className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>
                No GPU detected
              </p>
              <p className="font-telemetry text-[10px] mt-1" style={{ color: "var(--console-muted)" }}>
                NVIDIA driver + pynvml required
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {sysInfo.gpus.map((g) => (
                <div key={g.index} className="space-y-2">
                  <div className="font-telemetry text-[11px] space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span style={{ color: "var(--console-muted)" }}>Model</span>
                      <span style={{ color: "var(--console-text)" }}>{g.name}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span style={{ color: "var(--console-muted)" }}>Memory</span>
                      <span style={{ color: "var(--console-text)" }}>
                        {fmt(gpuMemUsed)} / {fmt(g.memory_total_mb)} MB ({fmt(gpuMemPct)}%)
                      </span>
                    </div>
                    {g.driver_version && (
                      <div className="flex items-center justify-between">
                        <span style={{ color: "var(--console-muted)" }}>Driver</span>
                        <span style={{ color: "var(--console-text)" }}>{g.driver_version}</span>
                      </div>
                    )}
                    {gpuTemp > 0 && (
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1" style={{ color: "var(--console-muted)" }}>
                          <Thermometer className="h-3 w-3" />
                          Temp
                        </span>
                        <span
                          style={{
                            color: gpuTemp >= 85
                              ? "var(--console-rec)"
                              : gpuTemp >= 70
                                ? "var(--console-alarm)"
                                : "var(--console-text)",
                          }}
                        >
                          {fmt(gpuTemp)}°C
                        </span>
                      </div>
                    )}
                  </div>

                  {/* GPU + VRAM bars */}
                  <div className="pt-1 space-y-2">
                    <div>
                      <div className="flex items-center justify-between font-telemetry text-[11px] mb-1" style={{ color: "var(--console-muted)" }}>
                        <span>Utilization</span>
                        <span>{fmt(gpuPct)}%</span>
                      </div>
                      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.05)" }}>
                        <div
                          className="h-full transition-all"
                          style={{ width: `${Math.min(gpuPct, 100)}%`, background: toneColor(gpuPct) }}
                        />
                      </div>
                    </div>
                    <div>
                      <div className="flex items-center justify-between font-telemetry text-[11px] mb-1" style={{ color: "var(--console-muted)" }}>
                        <span>VRAM</span>
                        <span>{fmt(gpuMemPct)}%</span>
                      </div>
                      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.05)" }}>
                        <div
                          className="h-full transition-all"
                          style={{ width: `${Math.min(gpuMemPct, 100)}%`, background: toneColor(gpuMemPct) }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </DetailPanel>
      </div>

      {/* History sparklines */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <HistoryCard
          title="CPU (60 min)"
          history={history}
          accessor={(p) => p.cpu_percent ?? 0}
          stroke="var(--console-accent)"
        />
        <HistoryCard
          title="Memory (60 min)"
          history={history}
          accessor={(p) => p.memory_percent ?? 0}
          stroke="var(--console-accent-blue)"
        />
      </div>

      {/* Bandwidth */}
      <div className="rounded border overflow-hidden" style={{ borderColor: "var(--console-border)" }}>
        <SectionHeader
          icon={Activity}
          label="Bandwidth per Camera"
          right={
            <span className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
              {bandwidth.length} {bandwidth.length === 1 ? "camera" : "cameras"}
            </span>
          }
        />
        {bandwidth.length > 0 ? (
          <table className="w-full font-telemetry text-[11px]">
            <tbody>
              {bandwidth.map((entry) => (
                <tr
                  key={entry.camera_id}
                  className="border-b last:border-0 hover:bg-white/5 transition-colors"
                  style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}
                >
                  <td className="px-4 py-2.5" style={{ color: "var(--console-text)" }}>
                    {entry.camera_name || entry.camera_id}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums" style={{ color: "var(--console-muted)" }}>
                    {fmt(entry.kbps ?? 0)} kbps
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="px-4 py-6 font-telemetry text-xs" style={{ background: "var(--console-panel)", color: "var(--console-muted)" }}>
            No bandwidth data available
          </p>
        )}
      </div>

      {/* Storage Health — admin only */}
      {isAdmin && (
        <div className="rounded border overflow-hidden" style={{ borderColor: "var(--console-border)" }}>
          <SectionHeader
            icon={HardDrive}
            label="Storage Health"
            right={
              <span className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
                {diskData?.disks?.length ?? 0}{" "}
                {(diskData?.disks?.length ?? 0) === 1 ? "volume" : "volumes"}
              </span>
            }
          />
          {diskData?.disks?.length > 0 ? (
            <div className="p-3 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3" style={{ background: "var(--console-panel)" }}>
              {diskData.disks.map((disk, i) => (
                <DiskCard key={`${disk.device}-${i}`} disk={disk} />
              ))}
            </div>
          ) : (
            <p className="px-4 py-6 font-telemetry text-xs" style={{ background: "var(--console-panel)", color: "var(--console-muted)" }}>
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
