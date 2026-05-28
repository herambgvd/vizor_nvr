// =============================================================================
// Storage — Pool management, disk explorer, cloud storage, tier rules
// =============================================================================

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  HardDrive,
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
  Server,
  Wifi,
  WifiOff,
  Plug,
  Unplug,
  Activity,
  Archive,
  Play,
} from "lucide-react";
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
  testNasConnection,
  mountNasPool,
  unmountNasPool,
  getNasPoolHealth,
  getBackupSchedules,
  createBackupSchedule,
  updateBackupSchedule,
  deleteBackupSchedule,
  runBackupNow,
} from "../api/storage";
import { Button } from "../components/ui/button";
import PageTabs from "../components/ui/page-tabs";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
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

// ── helpers ────────────────────────────────────────────────────────────────────

const fmtBytes = (bytes) => {
  if (!bytes || bytes <= 0) return "0 B";
  const k = 1024;
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${u[i]}`;
};

const pctVal = (used, total) =>
  total > 0 ? ((used / total) * 100).toFixed(1) : 0;

const TABS = [
  { id: "overview", label: "Overview", icon: Database },
  { id: "disks", label: "System Disks", icon: Disc },
  { id: "cloud", label: "Cloud Storage", icon: Cloud },
  { id: "rules", label: "Tier Rules", icon: Settings },
  { id: "backups", label: "Backup", icon: Archive },
];

// ── main page ──────────────────────────────────────────────────────────────────

const Storage = () => {
  const { isAdmin, canManageStorage } = usePermissions();
  const canManage = isAdmin || canManageStorage;
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState("overview");

  const { data: pools = [] } = useQuery({
    queryKey: ["storage-pools"],
    queryFn: getStoragePools,
  });
  const { data: rules = [] } = useQuery({
    queryKey: ["storage-rules"],
    queryFn: getStorageRules,
  });
  const { data: summary } = useQuery({
    queryKey: ["storage-summary"],
    queryFn: getStorageSummary,
    refetchInterval: 30000,
  });
  const { data: disksData } = useQuery({
    queryKey: ["system-disks"],
    queryFn: getSystemDisks,
    staleTime: 30000,
  });
  const { data: cloudConfigs = [] } = useQuery({
    queryKey: ["cloud-configs"],
    queryFn: getCloudConfigs,
  });

  const [poolDialog, setPoolDialog] = useState(false);
  const [editPool, setEditPool] = useState(null);
  const [ruleDialog, setRuleDialog] = useState(false);
  const [cloudDialog, setCloudDialog] = useState(false);
  const [editCloud, setEditCloud] = useState(null);
  const [backupDialog, setBackupDialog] = useState(false);
  const [editBackup, setEditBackup] = useState(null);

  const disks = disksData?.disks ?? [];

  return (
    <div className="p-4 md:p-6 h-full overflow-y-auto">
      <div className="mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Storage
        </h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          Local pools, system disks & cloud storage
        </p>
      </div>

      <PageTabs
        tabs={TABS.map((t) => ({ id: t.id, label: t.label, icon: t.icon }))}
        value={activeTab}
        onValueChange={setActiveTab}
        className="mb-6"
      />

      {/* tab content */}
      {activeTab === "overview" && (
        <OverviewTab
          summary={summary}
          pools={pools}
          canManage={canManage}
          onAddPool={() => {
            setEditPool(null);
            setPoolDialog(true);
          }}
          onEditPool={(p) => {
            setEditPool(p);
            setPoolDialog(true);
          }}
          onDeletePool={(id) => handleDeletePool(id)}
        />
      )}
      {activeTab === "disks" && <DiskExplorerTab disks={disks} />}
      {activeTab === "cloud" && (
        <CloudTab
          configs={cloudConfigs}
          canManage={canManage}
          onAdd={() => {
            setEditCloud(null);
            setCloudDialog(true);
          }}
          onEdit={(c) => {
            setEditCloud(c);
            setCloudDialog(true);
          }}
          onDelete={handleDeleteCloud}
          queryClient={qc}
        />
      )}
      {activeTab === "rules" && (
        <RulesTab
          rules={rules}
          pools={pools}
          canManage={canManage}
          onAddRule={() => setRuleDialog(true)}
          onDeleteRule={handleDeleteRule}
        />
      )}
      {activeTab === "backups" && (
        <BackupTab
          pools={pools}
          canManage={canManage}
          onAdd={() => { setEditBackup(null); setBackupDialog(true); }}
          onEdit={(b) => { setEditBackup(b); setBackupDialog(true); }}
          onDelete={handleDeleteBackup}
          queryClient={qc}
        />
      )}

      {/* dialogs */}
      <PoolFormDialog
        open={poolDialog}
        onOpenChange={setPoolDialog}
        pool={editPool}
        queryClient={qc}
      />
      <RuleFormDialog
        open={ruleDialog}
        onOpenChange={setRuleDialog}
        pools={pools}
        queryClient={qc}
      />
      <CloudFormDialog
        open={cloudDialog}
        onOpenChange={setCloudDialog}
        config={editCloud}
        queryClient={qc}
      />
      <BackupFormDialog
        open={backupDialog}
        onOpenChange={setBackupDialog}
        schedule={editBackup}
        pools={pools}
        queryClient={qc}
      />
    </div>
  );

  function handleDeletePool(id) {
    if (!window.confirm("Delete this storage pool?")) return;
    deleteStoragePool(id)
      .then(() => {
        qc.invalidateQueries({ queryKey: ["storage-pools"] });
        qc.invalidateQueries({ queryKey: ["storage-summary"] });
        toast.success("Pool deleted");
      })
      .catch((e) =>
        toast.error(e.response?.data?.detail || "Failed to delete pool"),
      );
  }

  function handleDeleteRule(id) {
    if (!window.confirm("Delete this tier rule?")) return;
    deleteStorageRule(id)
      .then(() => {
        qc.invalidateQueries({ queryKey: ["storage-rules"] });
        toast.success("Rule deleted");
      })
      .catch((e) =>
        toast.error(e.response?.data?.detail || "Failed to delete rule"),
      );
  }

  function handleDeleteCloud(id) {
    if (!window.confirm("Delete this cloud config?")) return;
    deleteCloudConfig(id)
      .then(() => {
        qc.invalidateQueries({ queryKey: ["cloud-configs"] });
        toast.success("Cloud config deleted");
      })
      .catch((e) =>
        toast.error(e.response?.data?.detail || "Failed to delete"),
      );
  }

  function handleDeleteBackup(id) {
    if (!window.confirm("Delete this backup schedule?")) return;
    deleteBackupSchedule(id)
      .then(() => {
        qc.invalidateQueries({ queryKey: ["backup-schedules"] });
        toast.success("Backup schedule deleted");
      })
      .catch((e) =>
        toast.error(e.response?.data?.detail || "Failed to delete"),
      );
  }
};

// ═══════════════════════════════════════════════════════════════════════════════
// TAB: Backup Schedules
// ═══════════════════════════════════════════════════════════════════════════════

const BackupTab = ({ pools, canManage, onAdd, onEdit, onDelete, queryClient }) => {
  const { data: schedules = [] } = useQuery({
    queryKey: ["backup-schedules"],
    queryFn: getBackupSchedules,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Scheduled Archives</h3>
        {canManage && (
          <Button size="sm" onClick={onAdd}>
            <Plus className="h-4 w-4 mr-1.5" />
            Add Schedule
          </Button>
        )}
      </div>

      {schedules.length === 0 ? (
        <p className="text-sm text-muted-foreground">No backup schedules configured.</p>
      ) : (
        <div className="space-y-3">
          {schedules.map((s) => (
            <div
              key={s.id}
              className="flex items-center justify-between bg-card border border-border rounded-lg p-4"
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{s.name}</span>
                  {!s.is_active && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">
                      Paused
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  Copies recordings older than <strong>{s.age_days}</strong> days via cron{" "}
                  <code className="text-teal-400">{s.schedule}</code>
                </p>
                {s.last_run_status && (
                  <p className="text-xs text-muted-foreground">
                    Last run: {s.last_run_status} {s.last_run_at && `— ${new Date(s.last_run_at).toLocaleString()}`}
                    {s.last_run_message && ` (${s.last_run_message})`}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    runBackupNow(s.id)
                      .then(() => {
                        toast.success("Backup started");
                        queryClient.invalidateQueries({ queryKey: ["backup-schedules"] });
                      })
                      .catch((e) => toast.error(e.response?.data?.detail || "Failed"))
                  }
                  title="Run now"
                >
                  <Play className="h-4 w-4" />
                </Button>
                {canManage && (
                  <>
                    <Button size="sm" variant="ghost" onClick={() => onEdit(s)}>
                      <Edit2 className="h-4 w-4" />
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => onDelete(s.id)}>
                      <Trash2 className="h-4 w-4 text-rose-400" />
                    </Button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const BackupFormDialog = ({ open, onOpenChange, schedule, pools, queryClient }) => {
  const isEdit = !!schedule;
  const [form, setForm] = useState({
    name: "",
    source_pool_id: "",
    target_pool_id: "",
    schedule: "0 2 * * *",
    age_days: 7,
    is_active: true,
  });

  React.useEffect(() => {
    if (schedule) {
      setForm({
        name: schedule.name || "",
        source_pool_id: schedule.source_pool_id || "",
        target_pool_id: schedule.target_pool_id || "",
        schedule: schedule.schedule || "0 2 * * *",
        age_days: schedule.age_days || 7,
        is_active: schedule.is_active ?? true,
      });
    } else {
      setForm({
        name: "",
        source_pool_id: "",
        target_pool_id: "",
        schedule: "0 2 * * *",
        age_days: 7,
        is_active: true,
      });
    }
  }, [schedule, open]);

  const mutation = useMutation({
    mutationFn: (data) =>
      isEdit
        ? updateBackupSchedule(schedule.id, data)
        : createBackupSchedule(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["backup-schedules"] });
      toast.success(isEdit ? "Schedule updated" : "Schedule created");
      onOpenChange(false);
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Failed"),
  });

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md bg-card border-border">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Backup Schedule" : "New Backup Schedule"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div>
            <Label>Name</Label>
            <Input value={form.name} onChange={(e) => set("name", e.target.value)} className="mt-1" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Source Pool</Label>
              <select
                className="w-full mt-1 h-9 px-2 text-sm bg-zinc-900 border border-border rounded-md"
                value={form.source_pool_id}
                onChange={(e) => set("source_pool_id", e.target.value)}
              >
                <option value="">Select…</option>
                {pools.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            <div>
              <Label>Target Pool (NAS)</Label>
              <select
                className="w-full mt-1 h-9 px-2 text-sm bg-zinc-900 border border-border rounded-md"
                value={form.target_pool_id}
                onChange={(e) => set("target_pool_id", e.target.value)}
              >
                <option value="">Select…</option>
                {pools.filter((p) => p.pool_type !== "local").map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <Label>Cron Schedule</Label>
            <Input value={form.schedule} onChange={(e) => set("schedule", e.target.value)} className="mt-1" placeholder="0 2 * * *" />
            <p className="text-[10px] text-muted-foreground mt-1">Minute Hour Day Month DayOfWeek</p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Age Threshold (days)</Label>
              <Input type="number" min={1} value={form.age_days} onChange={(e) => set("age_days", parseInt(e.target.value, 10) || 1)} className="mt-1" />
            </div>
            <div className="flex items-center gap-2 pt-6">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => set("is_active", e.target.checked)}
                className="rounded border-border"
              />
              <Label className="text-sm">Active</Label>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => mutation.mutate(form)} disabled={mutation.isPending}>
            {isEdit ? "Save Changes" : "Create Schedule"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

// ═══════════════════════════════════════════════════════════════════════════════
// TAB: Overview — summary cards + pool cards
// ═══════════════════════════════════════════════════════════════════════════════

const OverviewTab = ({
  summary,
  pools,
  canManage,
  onAddPool,
  onEditPool,
  onDeletePool,
}) => (
  <>
    {/* summary cards */}
    {summary && (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <SummaryCard
          icon={Database}
          label="Total Capacity"
          value={fmtBytes(summary.total_capacity_bytes)}
        />
        <SummaryCard
          icon={HardDrive}
          label="Used"
          value={`${fmtBytes(summary.total_used_bytes)} (${pctVal(summary.total_used_bytes, summary.total_capacity_bytes)}%)`}
        />
        <SummaryCard
          icon={FolderOpen}
          label="Pools"
          value={String(summary.total_pools ?? pools.length)}
        />
      </div>
    )}

    {/* pools section */}
    <div className="flex items-center justify-between mb-4">
      <h2 className="text-lg font-semibold text-white">Storage Pools</h2>
      {canManage && (
        <Button size="sm" onClick={onAddPool}>
          <Plus className="h-4 w-4 mr-1" />
          Add Pool
        </Button>
      )}
    </div>

    {pools.length === 0 ? (
      <EmptyState text="No storage pools configured" />
    ) : (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {pools.map((pool) => (
          <PoolCard
            key={pool.id}
            pool={pool}
            canManage={canManage}
            onEdit={() => onEditPool(pool)}
            onDelete={() => onDeletePool(pool.id)}
          />
        ))}
      </div>
    )}
  </>
);

// ═══════════════════════════════════════════════════════════════════════════════
// TAB: System Disks — disk partition explorer
// ═══════════════════════════════════════════════════════════════════════════════

const DiskExplorerTab = ({ disks }) => (
  <div>
    <h2 className="text-lg font-semibold text-white mb-4">
      System Disk Partitions
    </h2>
    {disks.length === 0 ? (
      <EmptyState text="No disk information available" />
    ) : (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {disks.map((disk, i) => {
          const used = disk.used_bytes ?? 0;
          const total = disk.total_bytes ?? 0;
          const free = disk.free_bytes ?? 0;
          const percent = disk.percent ?? 0;
          const barColor =
            percent > 90
              ? "bg-red-500"
              : percent > 70
                ? "bg-yellow-500"
                : "bg-blue-500";

          return (
            <div
              key={i}
              className="bg-card border border-border rounded-lg p-5"
            >
              <div className="flex items-center gap-2 mb-2">
                <Disc className="h-5 w-5 text-muted-foreground" />
                <h3 className="font-semibold text-white text-sm">
                  {disk.mountpoint}
                </h3>
                <span className="text-xs text-muted-foreground font-mono ml-auto">
                  {disk.device}
                </span>
              </div>
              <p className="text-xs text-muted-foreground mb-3">
                Filesystem: {disk.fstype || "unknown"}
              </p>
              <div className="h-2.5 bg-card/60 rounded-full overflow-hidden mb-2">
                <div
                  className={`h-full ${barColor} rounded-full transition-all`}
                  style={{ width: `${percent}%` }}
                />
              </div>
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>{fmtBytes(used)} used</span>
                <span>{fmtBytes(free)} free</span>
                <span>{fmtBytes(total)} total</span>
              </div>
              <div className="mt-2 text-right">
                <span
                  className={cn(
                    "text-sm font-bold",
                    percent > 90
                      ? "text-red-600"
                      : percent > 70
                        ? "text-yellow-600"
                        : "text-blue-600",
                  )}
                >
                  {percent}% used
                </span>
              </div>
            </div>
          );
        })}
      </div>
    )}
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════════
// TAB: Cloud Storage — S3-compatible cloud configs
// ═══════════════════════════════════════════════════════════════════════════════

const CloudTab = ({
  configs,
  canManage,
  onAdd,
  onEdit,
  onDelete,
  queryClient,
}) => {
  const testMut = useMutation({
    mutationFn: testCloudConfig,
    onSuccess: (res) => {
      if (res.success) {
        toast.success(res.message);
      } else {
        toast.error(res.message);
      }
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Test failed"),
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-white">
            Cloud Storage Configs
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Configure S3-compatible storage (AWS S3, MinIO, Backblaze B2) for
            uploading recordings
          </p>
        </div>
        {canManage && (
          <Button size="sm" onClick={onAdd}>
            <Plus className="h-4 w-4 mr-1" />
            Add Cloud Config
          </Button>
        )}
      </div>

      {configs.length === 0 ? (
        <div className="bg-card border border-border rounded-lg p-10 text-center">
          <Cloud className="h-12 w-12 text-slate-300 mx-auto mb-4" />
          <p className="text-muted-foreground mb-2">No cloud storage configured</p>
          <p className="text-sm text-muted-foreground">
            Add an S3-compatible cloud storage config to back up recordings to
            the cloud
          </p>
          {canManage && (
            <Button onClick={onAdd} variant="outline" className="mt-4">
              <CloudUpload className="h-4 w-4 mr-2" />
              Configure Cloud Storage
            </Button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {configs.map((cfg) => (
            <div
              key={cfg.id}
              className="bg-card border border-border rounded-lg p-5"
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Cloud className="h-5 w-5 text-blue-500" />
                  <h3 className="font-semibold text-white">{cfg.name}</h3>
                </div>
                <div className="flex items-center gap-1">
                  {cfg.sync_enabled && (
                    <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded font-medium">
                      Auto-sync
                    </span>
                  )}
                  {cfg.is_active ? (
                    <span
                      className="h-2 w-2 rounded-full bg-green-500 inline-block"
                      title="Active"
                    />
                  ) : (
                    <span
                      className="h-2 w-2 rounded-full bg-slate-300 inline-block"
                      title="Inactive"
                    />
                  )}
                </div>
              </div>

              <div className="space-y-1 text-sm mb-4">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Provider</span>
                  <span className="text-zinc-200 font-medium">
                    {cfg.provider.toUpperCase()}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Bucket</span>
                  <span className="text-zinc-200 font-mono text-xs">
                    {cfg.bucket}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Region</span>
                  <span className="text-zinc-200">{cfg.region}</span>
                </div>
                {cfg.endpoint && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Endpoint</span>
                    <span className="text-zinc-200 font-mono text-xs truncate max-w-[200px]">
                      {cfg.endpoint}
                    </span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Prefix</span>
                  <span className="text-zinc-200 font-mono text-xs">
                    {cfg.prefix}
                  </span>
                </div>
              </div>

              {canManage && (
                <div className="flex gap-2 border-t border-slate-100 pt-3">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => testMut.mutate(cfg.id)}
                    disabled={testMut.isPending}
                  >
                    <TestTube className="h-3.5 w-3.5 mr-1" />
                    Test
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onEdit(cfg)}
                  >
                    <Edit2 className="h-3.5 w-3.5 mr-1" />
                    Edit
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-red-600 hover:text-red-700"
                    onClick={() => onDelete(cfg.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5 mr-1" />
                    Delete
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════════
// TAB: Tier Rules
// ═══════════════════════════════════════════════════════════════════════════════

const RulesTab = ({ rules, pools, canManage, onAddRule, onDeleteRule }) => (
  <div>
    <div className="flex items-center justify-between mb-4">
      <h2 className="text-lg font-semibold text-white">Tier Rules</h2>
      {canManage && (
        <Button size="sm" onClick={onAddRule}>
          <Plus className="h-4 w-4 mr-1" />
          Add Rule
        </Button>
      )}
    </div>

    {rules.length === 0 ? (
      <EmptyState text="No tier rules configured. Rules move recordings between pools based on age." />
    ) : (
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-card/40 border-b border-border">
            <tr>
              <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                Name
              </th>
              <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                Source Pool
              </th>
              <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                Target Pool
              </th>
              <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                Age Threshold
              </th>
              <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                Status
              </th>
              {canManage && (
                <th className="text-right px-4 py-3 text-zinc-400 font-medium">
                  Actions
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => {
              const sourcePool = pools.find(
                (p) => p.id === rule.source_pool_id,
              );
              const targetPool = pools.find(
                (p) => p.id === rule.target_pool_id,
              );
              const hours = rule.age_threshold_hours ?? 0;
              const days =
                hours >= 24 ? `${Math.round(hours / 24)}d` : `${hours}h`;
              return (
                <tr
                  key={rule.id}
                  className="border-b border-slate-100 last:border-0"
                >
                  <td className="px-4 py-3 font-medium text-white">
                    {rule.name}
                  </td>
                  <td className="px-4 py-3 text-zinc-400">
                    {sourcePool?.name || rule.source_pool_id}
                  </td>
                  <td className="px-4 py-3 text-zinc-400">
                    {targetPool?.name || rule.target_pool_id}
                  </td>
                  <td className="px-4 py-3 text-zinc-400">
                    {days} ({hours}h)
                  </td>
                  <td className="px-4 py-3">
                    {rule.is_active ? (
                      <span className="inline-flex items-center gap-1 text-xs text-green-700 bg-green-50 px-2 py-0.5 rounded">
                        <Check className="h-3 w-3" /> Active
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground bg-card/60 px-2 py-0.5 rounded">
                        <X className="h-3 w-3" /> Inactive
                      </span>
                    )}
                  </td>
                  {canManage && (
                    <td className="px-4 py-3 text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-red-500"
                        onClick={() => onDeleteRule(rule.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    )}
  </div>
);

// ── sub-components ─────────────────────────────────────────────────────────────

const SummaryCard = ({ icon: Icon, label, value }) => (
  <div className="bg-card border border-border rounded-lg p-5 flex items-center gap-4">
    <div className="h-10 w-10 rounded-lg bg-blue-50 flex items-center justify-center">
      <Icon className="h-5 w-5 text-blue-600" />
    </div>
    <div>
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold text-white">{value}</p>
    </div>
  </div>
);

const PoolCard = ({ pool, canManage, onEdit, onDelete }) => {
  // Backend returns max_size_bytes and used_bytes
  const capacity = pool.max_size_bytes || 0;
  const used = pool.used_bytes || 0;
  const usedPct = capacity > 0 ? parseFloat(pctVal(used, capacity)) : 0;
  const barColor =
    usedPct > 90
      ? "bg-red-500"
      : usedPct > 70
        ? "bg-yellow-500"
        : "bg-blue-500";

  const isNas = pool.pool_type !== "local";
  const mountState = pool.nas_mount_state || "unknown";
  const mountColor =
    mountState === "mounted"
      ? "text-teal-400"
      : mountState === "error"
        ? "text-rose-400"
        : "text-zinc-400";

  const qc = useQueryClient();
  const mountMut = useMutation({
    mutationFn: () => mountNasPool(pool.id),
    onSuccess: () => {
      toast.success("Pool mounted");
      qc.invalidateQueries({ queryKey: ["storage-pools"] });
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Mount failed"),
  });
  const unmountMut = useMutation({
    mutationFn: () => unmountNasPool(pool.id),
    onSuccess: () => {
      toast.success("Pool unmounted");
      qc.invalidateQueries({ queryKey: ["storage-pools"] });
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Unmount failed"),
  });

  return (
    <div className="bg-card border border-border rounded-lg p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <HardDrive className="h-5 w-5 text-muted-foreground" />
          <h3 className="font-semibold text-white">{pool.name}</h3>
          {pool.is_default && (
            <span className="text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-medium">
              DEFAULT
            </span>
          )}
        </div>
        {canManage && (
          <div className="flex gap-1">
            {isNas && (
              <>
                {mountState !== "mounted" ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    title="Mount"
                    onClick={() => mountMut.mutate()}
                    disabled={mountMut.isPending}
                  >
                    <Plug className="h-3.5 w-3.5" />
                  </Button>
                ) : (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    title="Unmount"
                    onClick={() => unmountMut.mutate()}
                    disabled={unmountMut.isPending}
                  >
                    <Unplug className="h-3.5 w-3.5" />
                  </Button>
                )}
              </>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={onEdit}
            >
              <Edit2 className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-red-500"
              onClick={onDelete}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </div>
      <p className="text-xs text-muted-foreground font-mono truncate mb-1">
        {pool.path}
      </p>
      <p className="text-xs text-muted-foreground mb-2">
        Type: {pool.pool_type} | Priority: {pool.priority}
        {pool.recording_count > 0 && ` | ${pool.recording_count} recordings`}
      </p>
      {isNas && (
        <div className="flex items-center gap-2 mb-2 text-xs">
          <span className={mountColor}>
            {mountState === "mounted" ? <Wifi className="h-3 w-3 inline mr-1" /> : <WifiOff className="h-3 w-3 inline mr-1" />}
            {mountState}
          </span>
          {pool.nas_server && (
            <span className="text-zinc-500">
              {pool.nas_server}:{pool.nas_share}
            </span>
          )}
          {pool.nas_last_mount_error && (
            <span className="text-rose-400 truncate" title={pool.nas_last_mount_error}>
              {pool.nas_last_mount_error}
            </span>
          )}
        </div>
      )}
      {capacity > 0 ? (
        <>
          <div className="h-2 bg-card/60 rounded-full overflow-hidden mb-2">
            <div
              className={`h-full ${barColor} rounded-full`}
              style={{ width: `${usedPct}%` }}
            />
          </div>
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{fmtBytes(used)} used</span>
            <span>{fmtBytes(capacity)} total</span>
          </div>
        </>
      ) : (
        <div className="text-xs text-muted-foreground">
          {fmtBytes(used)} used (unlimited capacity)
        </div>
      )}
      {usedPct > 90 && (
        <div className="mt-3 flex items-center gap-1 text-xs text-red-600">
          <AlertTriangle className="h-3 w-3" />
          Storage nearly full
        </div>
      )}
    </div>
  );
};

const EmptyState = ({ text }) => (
  <div className="bg-card border border-border rounded-lg p-10 text-center text-muted-foreground">
    {text}
  </div>
);

// ── Pool Form Dialog ───────────────────────────────────────────────────────────

const PoolFormDialog = ({ open, onOpenChange, pool, queryClient }) => {
  const isEdit = !!pool;
  const [form, setForm] = useState({
    name: "",
    path: "",
    pool_type: "local",
    max_size_bytes: "",
    priority: "0",
    is_default: false,
    nas_server: "",
    nas_share: "",
    nas_protocol: "nfs",
    nas_username: "",
    nas_password: "",
    nas_domain: "",
    nas_auto_mount: true,
  });

  React.useEffect(() => {
    if (pool) {
      setForm({
        name: pool.name || "",
        path: pool.path || "",
        pool_type: pool.pool_type || "local",
        max_size_bytes: pool.max_size_bytes || "",
        priority: String(pool.priority ?? 0),
        is_default: pool.is_default ?? false,
        nas_server: pool.nas_server || "",
        nas_share: pool.nas_share || "",
        nas_protocol: pool.nas_protocol || "nfs",
        nas_username: pool.nas_username || "",
        nas_password: "",
        nas_domain: pool.nas_domain || "",
        nas_auto_mount: pool.nas_auto_mount ?? true,
      });
    } else {
      setForm({
        name: "",
        path: "",
        pool_type: "local",
        max_size_bytes: "",
        priority: "0",
        is_default: false,
        nas_server: "",
        nas_share: "",
        nas_protocol: "nfs",
        nas_username: "",
        nas_password: "",
        nas_domain: "",
        nas_auto_mount: true,
      });
    }
  }, [pool, open]);

  const mutation = useMutation({
    mutationFn: (data) =>
      isEdit ? updateStoragePool(pool.id, data) : createStoragePool(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storage-pools"] });
      queryClient.invalidateQueries({ queryKey: ["storage-summary"] });
      onOpenChange(false);
      toast.success(isEdit ? "Pool updated" : "Pool created");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Failed"),
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    const payload = {
      name: form.name,
      path: form.path,
      pool_type: form.pool_type,
      max_size_bytes: parseInt(form.max_size_bytes, 10) || null,
      priority: parseInt(form.priority, 10) || 0,
      is_default: form.is_default,
    };
    if (form.pool_type !== "local") {
      payload.nas_server = form.nas_server || null;
      payload.nas_share = form.nas_share || null;
      payload.nas_protocol = form.nas_protocol || null;
      payload.nas_username = form.nas_username || null;
      payload.nas_password = form.nas_password || null;
      payload.nas_domain = form.nas_domain || null;
      payload.nas_auto_mount = form.nas_auto_mount;
    }
    mutation.mutate(payload);
  };

  const set = (key, val) => setForm((p) => ({ ...p, [key]: val }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? "Edit Storage Pool" : "New Storage Pool"}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label>Name</Label>
            <Input
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="primary"
              required
            />
          </div>
          <div>
            <Label>Path</Label>
            <Input
              value={form.path}
              onChange={(e) => set("path", e.target.value)}
              placeholder="/data/recordings"
              required
              disabled={isEdit}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Type</Label>
              <Select
                value={form.pool_type}
                onValueChange={(v) => set("pool_type", v)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="local">Local</SelectItem>
                  <SelectItem value="nfs">NFS</SelectItem>
                  <SelectItem value="smb">SMB</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Priority</Label>
              <Input
                type="number"
                value={form.priority}
                onChange={(e) => set("priority", e.target.value)}
              />
            </div>
          </div>
          <div>
            <Label>Max Size (bytes)</Label>
            <Input
              type="number"
              value={form.max_size_bytes}
              onChange={(e) => set("max_size_bytes", e.target.value)}
              placeholder="Leave empty for unlimited"
            />
            <p className="text-xs text-muted-foreground mt-1">
              e.g., 1099511627776 = 1 TB. Leave empty for unlimited.
            </p>
          </div>
          {/* NAS fields */}
          {form.pool_type !== "local" && (
            <div className="space-y-3 border-t border-border pt-3">
              <div className="flex items-center gap-2 text-sm font-medium text-zinc-200">
                <Server className="h-4 w-4" /> NAS Configuration
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs">Server / IP</Label>
                  <Input
                    value={form.nas_server}
                    onChange={(e) => set("nas_server", e.target.value)}
                    placeholder="192.168.1.50"
                    required={form.pool_type !== "local"}
                  />
                </div>
                <div>
                  <Label className="text-xs">Share / Export</Label>
                  <Input
                    value={form.nas_share}
                    onChange={(e) => set("nas_share", e.target.value)}
                    placeholder="recordings"
                    required={form.pool_type !== "local"}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs">Protocol</Label>
                  <Select
                    value={form.nas_protocol}
                    onValueChange={(v) => set("nas_protocol", v)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="nfs">NFS</SelectItem>
                      <SelectItem value="smb">SMB / CIFS</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-xs">Domain / Workgroup</Label>
                  <Input
                    value={form.nas_domain}
                    onChange={(e) => set("nas_domain", e.target.value)}
                    placeholder="WORKGROUP"
                  />
                </div>
              </div>
              {form.nas_protocol === "smb" && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs">Username</Label>
                    <Input
                      value={form.nas_username}
                      onChange={(e) => set("nas_username", e.target.value)}
                      placeholder="admin"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Password</Label>
                    <Input
                      type="password"
                      value={form.nas_password}
                      onChange={(e) => set("nas_password", e.target.value)}
                      placeholder={isEdit ? "Leave blank to keep" : ""}
                    />
                  </div>
                </div>
              )}
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="nas_auto_mount"
                  checked={form.nas_auto_mount}
                  onChange={(e) => set("nas_auto_mount", e.target.checked)}
                  className="rounded border-border"
                />
                <Label htmlFor="nas_auto_mount" className="text-xs cursor-pointer">
                  Auto-mount on startup
                </Label>
              </div>
              {!isEdit && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={() => {
                    testNasConnection({
                      server: form.nas_server,
                      protocol: form.nas_protocol,
                      username: form.nas_username,
                      password: form.nas_password,
                      domain: form.nas_domain,
                    })
                      .then((res) => {
                        if (res.ok) {
                          toast.success(res.message);
                        } else {
                          toast.error(res.message);
                        }
                      })
                      .catch((e) => toast.error(e.response?.data?.detail || "Test failed"));
                  }}
                  disabled={!form.nas_server}
                >
                  <TestTube className="h-3.5 w-3.5 mr-1.5" />
                  Test Connection
                </Button>
              )}
            </div>
          )}

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="is_default"
              checked={form.is_default}
              onChange={(e) => set("is_default", e.target.checked)}
              className="rounded border-border"
            />
            <Label htmlFor="is_default" className="text-sm cursor-pointer">
              Set as default pool
            </Label>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending}>
              {isEdit ? "Update" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

// ── Rule Form Dialog ───────────────────────────────────────────────────────────

const RuleFormDialog = ({ open, onOpenChange, pools, queryClient }) => {
  const [form, setForm] = useState({
    name: "",
    source_pool_id: "",
    target_pool_id: "",
    age_threshold_hours: "",
  });

  React.useEffect(() => {
    if (open)
      setForm({
        name: "",
        source_pool_id: "",
        target_pool_id: "",
        age_threshold_hours: "",
      });
  }, [open]);

  const mutation = useMutation({
    mutationFn: (data) => createStorageRule(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storage-rules"] });
      onOpenChange(false);
      toast.success("Rule created");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Failed"),
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    mutation.mutate({
      name: form.name,
      source_pool_id: form.source_pool_id,
      target_pool_id: form.target_pool_id,
      age_threshold_hours: parseInt(form.age_threshold_hours, 10) || 24,
    });
  };

  const set = (key, val) => setForm((p) => ({ ...p, [key]: val }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New Tier Rule</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label>Rule Name</Label>
            <Input
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="Move old recordings to archive"
              required
            />
          </div>
          <div>
            <Label>Source Pool</Label>
            <Select
              value={form.source_pool_id}
              onValueChange={(v) => set("source_pool_id", v)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select source pool…" />
              </SelectTrigger>
              <SelectContent>
                {pools.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Target Pool</Label>
            <Select
              value={form.target_pool_id}
              onValueChange={(v) => set("target_pool_id", v)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select target pool…" />
              </SelectTrigger>
              <SelectContent>
                {pools
                  .filter((p) => p.id !== form.source_pool_id)
                  .map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Age Threshold (hours)</Label>
            <Input
              type="number"
              value={form.age_threshold_hours}
              onChange={(e) => set("age_threshold_hours", e.target.value)}
              placeholder="e.g., 168 (7 days)"
              required
              min="1"
            />
            <p className="text-xs text-muted-foreground mt-1">
              Recordings older than this will be moved from source → target pool
            </p>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending}>
              Create Rule
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

// ── Cloud Config Form Dialog ───────────────────────────────────────────────────

const CloudFormDialog = ({ open, onOpenChange, config, queryClient }) => {
  const isEdit = !!config;
  const [form, setForm] = useState({
    name: "",
    provider: "s3",
    endpoint: "",
    bucket: "",
    region: "us-east-1",
    access_key: "",
    secret_key: "",
    prefix: "recordings/",
    sync_enabled: false,
  });

  React.useEffect(() => {
    if (config) {
      setForm({
        name: config.name || "",
        provider: config.provider || "s3",
        endpoint: config.endpoint || "",
        bucket: config.bucket || "",
        region: config.region || "us-east-1",
        access_key: "", // never pre-fill secrets
        secret_key: "",
        prefix: config.prefix || "recordings/",
        sync_enabled: config.sync_enabled ?? false,
      });
    } else {
      setForm({
        name: "",
        provider: "s3",
        endpoint: "",
        bucket: "",
        region: "us-east-1",
        access_key: "",
        secret_key: "",
        prefix: "recordings/",
        sync_enabled: false,
      });
    }
  }, [config, open]);

  const mutation = useMutation({
    mutationFn: (data) =>
      isEdit ? updateCloudConfig(config.id, data) : createCloudConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cloud-configs"] });
      onOpenChange(false);
      toast.success(isEdit ? "Cloud config updated" : "Cloud config created");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Failed"),
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    const payload = { ...form };
    // Don't send empty credentials on edit
    if (isEdit) {
      if (!payload.access_key) delete payload.access_key;
      if (!payload.secret_key) delete payload.secret_key;
    }
    mutation.mutate(payload);
  };

  const set = (key, val) => setForm((p) => ({ ...p, [key]: val }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? "Edit Cloud Config" : "New Cloud Storage Config"}
          </DialogTitle>
        </DialogHeader>
        <form
          onSubmit={handleSubmit}
          className="space-y-4 max-h-[60vh] overflow-y-auto pr-1"
        >
          <div>
            <Label>Name</Label>
            <Input
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="My S3 Backup"
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Provider</Label>
              <Select
                value={form.provider}
                onValueChange={(v) => set("provider", v)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="s3">AWS S3</SelectItem>
                  <SelectItem value="minio">MinIO</SelectItem>
                  <SelectItem value="b2">Backblaze B2</SelectItem>
                  <SelectItem value="gcs">Google Cloud</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Region</Label>
              <Input
                value={form.region}
                onChange={(e) => set("region", e.target.value)}
                placeholder="us-east-1"
              />
            </div>
          </div>
          <div>
            <Label>Bucket</Label>
            <Input
              value={form.bucket}
              onChange={(e) => set("bucket", e.target.value)}
              placeholder="my-nvr-bucket"
              required
            />
          </div>
          <div>
            <Label>Endpoint (for MinIO/custom S3)</Label>
            <Input
              value={form.endpoint}
              onChange={(e) => set("endpoint", e.target.value)}
              placeholder="https://minio.example.com:9000"
            />
            <p className="text-xs text-muted-foreground mt-1">
              Leave empty for standard AWS S3
            </p>
          </div>
          <div>
            <Label>Prefix</Label>
            <Input
              value={form.prefix}
              onChange={(e) => set("prefix", e.target.value)}
              placeholder="recordings/"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Access Key</Label>
              <Input
                value={form.access_key}
                onChange={(e) => set("access_key", e.target.value)}
                placeholder={isEdit ? "••••••••" : "AKIA..."}
              />
            </div>
            <div>
              <Label>Secret Key</Label>
              <Input
                type="password"
                value={form.secret_key}
                onChange={(e) => set("secret_key", e.target.value)}
                placeholder={isEdit ? "••••••••" : ""}
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="sync_enabled"
              checked={form.sync_enabled}
              onChange={(e) => set("sync_enabled", e.target.checked)}
              className="rounded border-border"
            />
            <Label htmlFor="sync_enabled" className="text-sm cursor-pointer">
              Auto-sync new recordings to this cloud storage
            </Label>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending}>
              {isEdit ? "Update" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default Storage;
