// =============================================================================
// System Monitoring — Resources + Storage (merged view)
// =============================================================================

import React, { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Cpu,
  MemoryStick,
  HardDrive,
  Network,
  Activity,
  RefreshCw,
  Plus,
  Trash2,
  Edit2,
  FolderOpen,
  AlertTriangle,
  Database,
  Cloud,
  CloudUpload,
  Disc,
  Settings,
  TestTube,
  Check,
  X,
} from "lucide-react";
import {
  getResources,
  getResourceHistory,
  getBandwidthSummary,
} from "../api/monitoring";
import {
  getStoragePools,
  createStoragePool,
  updateStoragePool,
  deleteStoragePool,
  getStorageRules,
  createStorageRule,
  deleteStorageRule,
  getStorageSummary,
  getSystemDisks,
  getCloudConfigs,
  createCloudConfig,
  updateCloudConfig,
  deleteCloudConfig,
  testCloudConfig,
} from "../api/storage";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "../components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { toast } from "sonner";
import { usePermissions } from "../hooks";
import { cn } from "../lib/utils";

// =============================================================================
// Main Page
// =============================================================================

const SystemMonitoring = () => {
  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 px-4 md:px-8 pt-4 md:pt-6 pb-3 md:pb-4 border-b border-white/10 ">
        <h1
          className="text-2xl md:text-3xl font-bold text-white  tracking-tight"
          style={{ fontFamily: "Manrope, sans-serif" }}
        >
          Monitoring
        </h1>
        <p className="text-zinc-500 dark:text-zinc-500 mt-1 text-sm md:text-base">
          System resources and storage management
        </p>
      </div>

      <Tabs
        defaultValue="resources"
        className="flex-1 flex flex-col overflow-hidden"
      >
        <div className="flex-shrink-0 px-4 md:px-8 border-b border-white/10 ">
          <TabsList className="h-auto bg-transparent gap-0 p-0">
            <TabsTrigger
              value="resources"
              className="gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-slate-900 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-3"
            >
              <Activity className="h-4 w-4" />
              Resources
            </TabsTrigger>
            <TabsTrigger
              value="storage"
              className="gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-slate-900 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-3"
            >
              <HardDrive className="h-4 w-4" />
              Storage
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="resources" className="flex-1 overflow-y-auto m-0">
          <ResourcesPanel />
        </TabsContent>
        <TabsContent value="storage" className="flex-1 overflow-y-auto m-0">
          <StoragePanel />
        </TabsContent>
      </Tabs>
    </div>
  );
};

// =============================================================================
// Resources Panel (from Monitoring.js)
// =============================================================================

const ResourcesPanel = () => {
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

  const bandwidth = useMemo(() => {
    if (!rawBandwidth) return [];
    if (Array.isArray(rawBandwidth)) return rawBandwidth;
    return Object.entries(rawBandwidth).map(([id, data]) => ({
      camera_id: id,
      kbps: data?.kbps ?? 0,
    }));
  }, [rawBandwidth]);

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
    <div className="p-4 md:p-8 space-y-6">
      {/* Refresh */}
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
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
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
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
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
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
      <div className="bg-zinc-950 dark:bg-zinc-900/60 border border-white/10  rounded-lg p-6">
        <h2 className="text-lg font-semibold text-white  mb-4 flex items-center gap-2">
          <Activity className="h-5 w-5 text-zinc-400 dark:text-zinc-500" />
          Bandwidth per Camera
        </h2>
        {bandwidth.length > 0 ? (
          <div className="space-y-3">
            {bandwidth.map((entry) => (
              <div
                key={entry.camera_id}
                className="flex items-center justify-between text-sm"
              >
                <span className="text-zinc-200  font-medium font-mono text-xs">
                  {entry.camera_name || entry.camera_id}
                </span>
                <span className="text-zinc-500 dark:text-zinc-500">
                  {fmt(entry.kbps ?? 0)} kbps
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-zinc-500">No bandwidth data available</p>
        )}
      </div>
    </div>
  );
};

// =============================================================================
// Storage Panel (from Storage.js — imported as-is)
// =============================================================================

const StoragePanel = React.lazy(() => import("./Storage"));

// =============================================================================
// Shared helpers
// =============================================================================

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
    <div className="bg-zinc-950 dark:bg-zinc-900/60 border border-white/10  rounded-lg p-6 flex flex-col items-center">
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
        <span className="text-sm font-medium text-zinc-200 ">
          {label}
        </span>
      </div>
      {sub && <p className="text-xs text-zinc-500 mt-1">{sub}</p>}
    </div>
  );
};

const HistoryCard = ({ title, history, accessor, color }) => {
  const points = useMemo(() => {
    if (!Array.isArray(history) || history.length === 0) return [];
    return history.map((p, i) => ({ x: i, y: accessor(p) }));
  }, [history, accessor]);

  if (points.length === 0) {
    return (
      <div className="bg-zinc-950 dark:bg-zinc-900/60 border border-white/10  rounded-lg p-6">
        <h3 className="text-sm font-semibold text-zinc-200  mb-3">
          {title}
        </h3>
        <p className="text-sm text-zinc-500">No history data</p>
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
    <div className="bg-zinc-950 dark:bg-zinc-900/60 border border-white/10  rounded-lg p-6">
      <h3 className="text-sm font-semibold text-zinc-200  mb-3">
        {title}
      </h3>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-24">
        <path d={pathD} fill="none" stroke={color} strokeWidth="2" />
      </svg>
    </div>
  );
};

export default SystemMonitoring;
