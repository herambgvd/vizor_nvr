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
import { useConfirm } from "../components/ui/confirm";
import { cn, friendlyError } from "../lib/utils";
import { formatDateTime } from "../lib/datetime";

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

// ── shared styles ─────────────────────────────────────────────────────────────

const inputStyle = {
  background: "var(--console-raised)",
  border: "1px solid var(--console-border)",
  color: "var(--console-text)",
};

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
  const confirm = useConfirm();
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
    <div
      className="h-full flex flex-col overflow-hidden"
      style={{ background: "var(--console-bg)", color: "var(--console-text)" }}
    >
      {/* Page header bar */}
      <div
        className="flex items-center gap-3 px-4 py-2.5 border-b flex-shrink-0"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        <span
          className="w-0.5 h-4 rounded-full flex-shrink-0"
          style={{ background: "var(--console-accent)" }}
        />
        <span
          className="font-telemetry text-xs font-semibold uppercase tracking-widest"
          style={{ color: "var(--console-text)" }}
        >
          Storage
        </span>
        <span
          className="font-telemetry text-[10px]"
          style={{ color: "var(--console-muted)" }}
        >
          Local pools, system disks &amp; cloud storage
        </span>
      </div>

      {/* Internal tab bar */}
      <div
        className="flex items-center gap-0 border-b flex-shrink-0 overflow-x-auto"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        {TABS.map(({ id, label, icon: Icon }) => {
          const active = activeTab === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => setActiveTab(id)}
              className="relative flex items-center gap-1.5 px-4 py-2.5 font-telemetry text-[11px] uppercase tracking-wide whitespace-nowrap transition-colors hover:bg-white/5"
              style={{ color: active ? "var(--console-accent)" : "var(--console-muted)" }}
            >
              <Icon className="h-3.5 w-3.5 flex-shrink-0" />
              {label}
              {active && (
                <span
                  className="absolute bottom-0 left-0 right-0 h-[2px] rounded-t"
                  style={{ background: "var(--console-accent)" }}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4 md:p-6">
        {activeTab === "overview" && (
          <OverviewTab
            summary={summary}
            pools={pools}
            canManage={canManage}
            onAddPool={() => { setEditPool(null); setPoolDialog(true); }}
            onEditPool={(p) => { setEditPool(p); setPoolDialog(true); }}
            onDeletePool={(id) => handleDeletePool(id)}
          />
        )}
        {activeTab === "disks" && <DiskExplorerTab disks={disks} />}
        {activeTab === "cloud" && (
          <CloudTab
            configs={cloudConfigs}
            canManage={canManage}
            onAdd={() => { setEditCloud(null); setCloudDialog(true); }}
            onEdit={(c) => { setEditCloud(c); setCloudDialog(true); }}
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
      </div>

      {/* dialogs */}
      <PoolFormDialog open={poolDialog} onOpenChange={setPoolDialog} pool={editPool} queryClient={qc} />
      <RuleFormDialog open={ruleDialog} onOpenChange={setRuleDialog} pools={pools} queryClient={qc} />
      <CloudFormDialog open={cloudDialog} onOpenChange={setCloudDialog} config={editCloud} queryClient={qc} />
      <BackupFormDialog open={backupDialog} onOpenChange={setBackupDialog} schedule={editBackup} pools={pools} queryClient={qc} />
    </div>
  );

  async function handleDeletePool(id) {
    if (!(await confirm({
      title: "Delete storage pool?",
      description: "Recordings on this pool will no longer be tracked. This cannot be undone.",
      confirmText: "Delete",
      danger: true,
    }))) return;
    deleteStoragePool(id)
      .then(() => {
        qc.invalidateQueries({ queryKey: ["storage-pools"] });
        qc.invalidateQueries({ queryKey: ["storage-summary"] });
        toast.success("Pool deleted");
      })
      .catch((e) => toast.error(friendlyError(e, "Couldn't delete the pool.")));
  }

  async function handleDeleteRule(id) {
    if (!(await confirm({
      title: "Delete tier rule?",
      confirmText: "Delete",
      danger: true,
    }))) return;
    deleteStorageRule(id)
      .then(() => {
        qc.invalidateQueries({ queryKey: ["storage-rules"] });
        toast.success("Rule deleted");
      })
      .catch((e) => toast.error(friendlyError(e, "Couldn't delete the rule.")));
  }

  async function handleDeleteCloud(id) {
    if (!(await confirm({
      title: "Delete cloud config?",
      confirmText: "Delete",
      danger: true,
    }))) return;
    deleteCloudConfig(id)
      .then(() => {
        qc.invalidateQueries({ queryKey: ["cloud-configs"] });
        toast.success("Cloud config deleted");
      })
      .catch((e) => toast.error(friendlyError(e, "Couldn't delete.")));
  }

  async function handleDeleteBackup(id) {
    if (!(await confirm({
      title: "Delete backup schedule?",
      confirmText: "Delete",
      danger: true,
    }))) return;
    deleteBackupSchedule(id)
      .then(() => {
        qc.invalidateQueries({ queryKey: ["backup-schedules"] });
        toast.success("Backup schedule deleted");
      })
      .catch((e) => toast.error(friendlyError(e, "Couldn't delete.")));
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
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span
          className="font-telemetry text-[11px] uppercase tracking-wide"
          style={{ color: "var(--console-muted)" }}
        >
          Scheduled Archives
        </span>
        {canManage && (
          <PrimaryBtn onClick={onAdd}>
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add Schedule
          </PrimaryBtn>
        )}
      </div>

      {schedules.length === 0 ? (
        <EmptyState text="No backup schedules configured." />
      ) : (
        <div className="space-y-2">
          {schedules.map((s) => (
            <div
              key={s.id}
              className="flex items-center justify-between rounded p-4"
              style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-telemetry text-xs font-semibold" style={{ color: "var(--console-text)" }}>
                    {s.name}
                  </span>
                  {!s.is_active && (
                    <span
                      className="font-telemetry text-[10px] px-1.5 py-0.5 rounded"
                      style={{ background: "var(--console-raised)", color: "var(--console-muted)", border: "1px solid var(--console-border)" }}
                    >
                      Paused
                    </span>
                  )}
                </div>
                <p className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
                  Copies recordings older than <strong>{s.age_days}</strong> days via cron{" "}
                  <code style={{ color: "var(--console-accent)" }}>{s.schedule}</code>
                </p>
                {s.last_run_status && (
                  <p className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
                    Last run: {s.last_run_status} {s.last_run_at && `— ${formatDateTime(s.last_run_at)}`}
                    {s.last_run_message && ` (${s.last_run_message})`}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-1">
                <GhostIconBtn
                  onClick={() =>
                    runBackupNow(s.id)
                      .then(() => {
                        toast.success("Backup started");
                        queryClient.invalidateQueries({ queryKey: ["backup-schedules"] });
                      })
                      .catch((e) => toast.error(friendlyError(e, "Couldn't start the backup.")))
                  }
                  title="Run now"
                >
                  <Play className="h-3.5 w-3.5" />
                </GhostIconBtn>
                {canManage && (
                  <>
                    <GhostIconBtn onClick={() => onEdit(s)}>
                      <Edit2 className="h-3.5 w-3.5" />
                    </GhostIconBtn>
                    <GhostIconBtn onClick={() => onDelete(s.id)}>
                      <Trash2 className="h-3.5 w-3.5" style={{ color: "var(--console-rec)" }} />
                    </GhostIconBtn>
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
      setForm({ name: "", source_pool_id: "", target_pool_id: "", schedule: "0 2 * * *", age_days: 7, is_active: true });
    }
  }, [schedule, open]);

  const mutation = useMutation({
    mutationFn: (data) => isEdit ? updateBackupSchedule(schedule.id, data) : createBackupSchedule(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["backup-schedules"] });
      toast.success(isEdit ? "Schedule updated" : "Schedule created");
      onOpenChange(false);
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't save the backup schedule.")),
  });

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)", color: "var(--console-text)" }}
      >
        <DialogHeader>
          <DialogTitle className="font-telemetry text-xs uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
            {isEdit ? "Edit Backup Schedule" : "New Backup Schedule"}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <DialogField label="Name">
            <ConsoleInput value={form.name} onChange={(e) => set("name", e.target.value)} />
          </DialogField>
          <div className="grid grid-cols-2 gap-3">
            <DialogField label="Source Pool">
              <ConsoleSelect value={form.source_pool_id} onChange={(e) => set("source_pool_id", e.target.value)}>
                <option value="">Select…</option>
                {pools.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </ConsoleSelect>
            </DialogField>
            <DialogField label="Target Pool (NAS)">
              <ConsoleSelect value={form.target_pool_id} onChange={(e) => set("target_pool_id", e.target.value)}>
                <option value="">Select…</option>
                {pools.filter((p) => p.pool_type !== "local").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </ConsoleSelect>
            </DialogField>
          </div>
          <DialogField label="Cron Schedule" help="Minute Hour Day Month DayOfWeek">
            <ConsoleInput value={form.schedule} onChange={(e) => set("schedule", e.target.value)} placeholder="0 2 * * *" />
          </DialogField>
          <div className="grid grid-cols-2 gap-3">
            <DialogField label="Age Threshold (days)">
              <ConsoleInput type="number" min={1} value={form.age_days} onChange={(e) => set("age_days", parseInt(e.target.value, 10) || 1)} />
            </DialogField>
            <div className="flex items-center gap-2 pt-5">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => set("is_active", e.target.checked)}
                className="rounded"
                style={{ accentColor: "var(--console-accent)" }}
              />
              <label className="font-telemetry text-xs" style={{ color: "var(--console-text)" }}>Active</label>
            </div>
          </div>
        </div>
        <DialogFooter>
          <SecondaryBtn onClick={() => onOpenChange(false)}>Cancel</SecondaryBtn>
          <PrimaryBtn onClick={() => mutation.mutate(form)} disabled={mutation.isPending}>
            {isEdit ? "Save Changes" : "Create Schedule"}
          </PrimaryBtn>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

// ═══════════════════════════════════════════════════════════════════════════════
// TAB: Overview — summary cards + pool cards
// ═══════════════════════════════════════════════════════════════════════════════

const OverviewTab = ({ summary, pools, canManage, onAddPool, onEditPool, onDeletePool }) => (
  <>
    {summary && (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
        <SummaryCard icon={Database} label="Total Capacity" value={fmtBytes(summary.total_capacity_bytes)} />
        <SummaryCard
          icon={HardDrive}
          label="Used"
          value={`${fmtBytes(summary.total_used_bytes)} (${pctVal(summary.total_used_bytes, summary.total_capacity_bytes)}%)`}
        />
        <SummaryCard icon={FolderOpen} label="Pools" value={String(summary.total_pools ?? pools.length)} />
      </div>
    )}

    <div className="flex items-center justify-between mb-4">
      <span
        className="font-telemetry text-[11px] uppercase tracking-wide"
        style={{ color: "var(--console-muted)" }}
      >
        Storage Pools
      </span>
      {canManage && (
        <PrimaryBtn onClick={onAddPool}>
          <Plus className="h-3.5 w-3.5 mr-1" />
          Add Pool
        </PrimaryBtn>
      )}
    </div>

    {pools.length === 0 ? (
      <EmptyState text="No storage pools configured" />
    ) : (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {pools.map((pool) => (
          <PoolCard key={pool.id} pool={pool} canManage={canManage} onEdit={() => onEditPool(pool)} onDelete={() => onDeletePool(pool.id)} />
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
    <p
      className="font-telemetry text-[11px] uppercase tracking-wide mb-4"
      style={{ color: "var(--console-muted)" }}
    >
      System Disk Partitions
    </p>
    {disks.length === 0 ? (
      <EmptyState text="No disk information available" />
    ) : (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {disks.map((disk, i) => {
          const used = disk.used_bytes ?? 0;
          const total = disk.total_bytes ?? 0;
          const free = disk.free_bytes ?? 0;
          const percent = disk.percent ?? 0;
          const barColor =
            percent > 90
              ? "var(--console-rec)"
              : percent > 70
              ? "var(--console-alarm)"
              : "var(--console-accent)";

          return (
            <div
              key={i}
              className="rounded p-4"
              style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
            >
              <div className="flex items-center gap-2 mb-2">
                <Disc className="h-4 w-4 flex-shrink-0" style={{ color: "var(--console-muted)" }} />
                <span className="font-telemetry text-xs font-semibold" style={{ color: "var(--console-text)" }}>
                  {disk.mountpoint}
                </span>
                <span className="font-telemetry text-[10px] ml-auto" style={{ color: "var(--console-muted)" }}>
                  {disk.device}
                </span>
              </div>
              <p className="font-telemetry text-[10px] mb-3" style={{ color: "var(--console-muted)" }}>
                Filesystem: {disk.fstype || "unknown"}
              </p>
              <div
                className="h-2 rounded-full overflow-hidden mb-2"
                style={{ background: "var(--console-raised)" }}
              >
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${percent}%`, background: barColor }}
                />
              </div>
              <div className="flex justify-between font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
                <span>{fmtBytes(used)} used</span>
                <span>{fmtBytes(free)} free</span>
                <span>{fmtBytes(total)} total</span>
              </div>
              <div className="mt-2 text-right">
                <span
                  className="font-telemetry text-xs font-bold"
                  style={{
                    color:
                      percent > 90
                        ? "var(--console-rec)"
                        : percent > 70
                        ? "var(--console-alarm)"
                        : "var(--console-accent)",
                  }}
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

const CloudTab = ({ configs, canManage, onAdd, onEdit, onDelete, queryClient }) => {
  const testMut = useMutation({
    mutationFn: testCloudConfig,
    onSuccess: (res) => { if (res.success) toast.success(res.message); else toast.error(res.message); },
    onError: (e) => toast.error(friendlyError(e, "Cloud test failed.")),
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="font-telemetry text-[11px] uppercase tracking-wide" style={{ color: "var(--console-muted)" }}>
            Cloud Storage Configs
          </p>
          <p className="font-telemetry text-[10px] mt-0.5" style={{ color: "var(--console-muted)" }}>
            Configure S3-compatible storage (AWS S3, MinIO, Backblaze B2) for uploading recordings
          </p>
        </div>
        {canManage && (
          <PrimaryBtn onClick={onAdd}>
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add Cloud Config
          </PrimaryBtn>
        )}
      </div>

      {configs.length === 0 ? (
        <div
          className="rounded p-10 text-center"
          style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
        >
          <Cloud className="h-10 w-10 mx-auto mb-4" style={{ color: "var(--console-muted)" }} />
          <p className="font-telemetry text-xs mb-1" style={{ color: "var(--console-muted)" }}>
            No cloud storage configured
          </p>
          <p className="font-telemetry text-[10px] mb-4" style={{ color: "var(--console-muted)" }}>
            Add an S3-compatible cloud storage config to back up recordings to the cloud
          </p>
          {canManage && (
            <SecondaryBtn onClick={onAdd}>
              <CloudUpload className="h-3.5 w-3.5 mr-1.5" />
              Configure Cloud Storage
            </SecondaryBtn>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {configs.map((cfg) => (
            <div
              key={cfg.id}
              className="rounded p-4"
              style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Cloud className="h-4 w-4 flex-shrink-0" style={{ color: "var(--console-accent)" }} />
                  <span className="font-telemetry text-xs font-semibold" style={{ color: "var(--console-text)" }}>
                    {cfg.name}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  {cfg.sync_enabled && (
                    <span
                      className="font-telemetry text-[10px] px-1.5 py-0.5 rounded"
                      style={{ background: "var(--console-raised)", color: "var(--console-online)", border: "1px solid var(--console-border)" }}
                    >
                      Auto-sync
                    </span>
                  )}
                  <span
                    className="h-2 w-2 rounded-full inline-block"
                    style={{ background: cfg.is_active ? "var(--console-online)" : "var(--console-muted)" }}
                    title={cfg.is_active ? "Active" : "Inactive"}
                  />
                </div>
              </div>

              <div className="space-y-1 font-telemetry text-[11px] mb-4">
                {[
                  ["Provider", cfg.provider.toUpperCase()],
                  ["Bucket", cfg.bucket],
                  ["Region", cfg.region],
                  ...(cfg.endpoint ? [["Endpoint", cfg.endpoint]] : []),
                  ["Prefix", cfg.prefix],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <span style={{ color: "var(--console-muted)" }}>{k}</span>
                    <span className="font-telemetry text-[10px] truncate max-w-[200px]" style={{ color: "var(--console-text)" }}>{v}</span>
                  </div>
                ))}
              </div>

              {canManage && (
                <div
                  className="flex gap-2 pt-3 border-t"
                  style={{ borderColor: "var(--console-border)" }}
                >
                  <SecondaryBtn onClick={() => testMut.mutate(cfg.id)} disabled={testMut.isPending}>
                    <TestTube className="h-3.5 w-3.5 mr-1" />
                    Test
                  </SecondaryBtn>
                  <SecondaryBtn onClick={() => onEdit(cfg)}>
                    <Edit2 className="h-3.5 w-3.5 mr-1" />
                    Edit
                  </SecondaryBtn>
                  <SecondaryBtn onClick={() => onDelete(cfg.id)}>
                    <Trash2 className="h-3.5 w-3.5 mr-1" style={{ color: "var(--console-rec)" }} />
                    Delete
                  </SecondaryBtn>
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
      <span
        className="font-telemetry text-[11px] uppercase tracking-wide"
        style={{ color: "var(--console-muted)" }}
      >
        Tier Rules
      </span>
      {canManage && (
        <PrimaryBtn onClick={onAddRule}>
          <Plus className="h-3.5 w-3.5 mr-1" />
          Add Rule
        </PrimaryBtn>
      )}
    </div>

    {rules.length === 0 ? (
      <EmptyState text="No tier rules configured. Rules move recordings between pools based on age." />
    ) : (
      <div
        className="rounded overflow-hidden"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
      >
        <table className="w-full font-telemetry text-[11px]">
          <thead
            style={{ background: "var(--console-raised)", borderBottom: "1px solid var(--console-border)" }}
          >
            <tr>
              {["Name", "Source Pool", "Target Pool", "Age Threshold", "Status", canManage ? "Actions" : null]
                .filter(Boolean)
                .map((h, idx) => (
                  <th
                    key={idx}
                    className={cn("px-4 py-2.5 text-left font-semibold uppercase tracking-wide", idx === 5 && "text-right")}
                    style={{ color: "var(--console-muted)" }}
                  >
                    {h}
                  </th>
                ))}
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => {
              const sourcePool = pools.find((p) => p.id === rule.source_pool_id);
              const targetPool = pools.find((p) => p.id === rule.target_pool_id);
              const hours = rule.age_threshold_hours ?? 0;
              const days = hours >= 24 ? `${Math.round(hours / 24)}d` : `${hours}h`;
              return (
                <tr
                  key={rule.id}
                  className="border-b last:border-0"
                  style={{ borderColor: "var(--console-border)" }}
                >
                  <td className="px-4 py-3 font-semibold" style={{ color: "var(--console-text)" }}>
                    {rule.name}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--console-muted)" }}>
                    {sourcePool?.name || rule.source_pool_id}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--console-muted)" }}>
                    {targetPool?.name || rule.target_pool_id}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--console-muted)" }}>
                    {days} ({hours}h)
                  </td>
                  <td className="px-4 py-3">
                    {rule.is_active ? (
                      <span
                        className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded"
                        style={{ background: "var(--console-raised)", color: "var(--console-online)", border: "1px solid var(--console-border)" }}
                      >
                        <Check className="h-2.5 w-2.5" /> Active
                      </span>
                    ) : (
                      <span
                        className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded"
                        style={{ background: "var(--console-raised)", color: "var(--console-muted)", border: "1px solid var(--console-border)" }}
                      >
                        <X className="h-2.5 w-2.5" /> Inactive
                      </span>
                    )}
                  </td>
                  {canManage && (
                    <td className="px-4 py-3 text-right">
                      <GhostIconBtn onClick={() => onDeleteRule(rule.id)}>
                        <Trash2 className="h-3.5 w-3.5" style={{ color: "var(--console-rec)" }} />
                      </GhostIconBtn>
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
  <div
    className="rounded p-4 flex items-center gap-4"
    style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
  >
    <div
      className="h-9 w-9 rounded flex items-center justify-center flex-shrink-0"
      style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
    >
      <Icon className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
    </div>
    <div>
      <p className="font-telemetry text-[10px] uppercase tracking-wide" style={{ color: "var(--console-muted)" }}>
        {label}
      </p>
      <p className="font-telemetry text-sm font-semibold" style={{ color: "var(--console-text)" }}>
        {value}
      </p>
    </div>
  </div>
);

const PoolCard = ({ pool, canManage, onEdit, onDelete }) => {
  // Prefer the configured quota; fall back to the real filesystem capacity the
  // backend reports (total_bytes) so unquota'd pools still show a usage meter.
  const quota = pool.max_size_bytes || 0;
  const capacity = quota || pool.total_bytes || 0;
  const used = pool.used_bytes || 0;
  const free = pool.free_bytes ?? Math.max(0, capacity - used);
  // online=false means the path is missing or the mount is stale/offline —
  // distinguish this from a genuinely empty disk so 0/0/0 doesn't read as such.
  const online = pool.online !== false;
  const usedPct = capacity > 0 ? parseFloat(pctVal(used, capacity)) : 0;
  const isFull = online && (usedPct >= 99 || (capacity > 0 && free <= 0));
  const barColor =
    usedPct > 90
      ? "var(--console-rec)"
      : usedPct > 70
      ? "var(--console-alarm)"
      : "var(--console-accent)";

  const isNas = pool.pool_type !== "local";
  const mountState = pool.nas_mount_state || "unknown";
  const mountColor =
    mountState === "mounted"
      ? "var(--console-online)"
      : mountState === "error"
      ? "var(--console-rec)"
      : "var(--console-muted)";

  const qc = useQueryClient();
  const mountMut = useMutation({
    mutationFn: () => mountNasPool(pool.id),
    onSuccess: () => { toast.success("Pool mounted"); qc.invalidateQueries({ queryKey: ["storage-pools"] }); },
    onError: (e) => toast.error(friendlyError(e, "Couldn't mount the pool.")),
  });
  const unmountMut = useMutation({
    mutationFn: () => unmountNasPool(pool.id),
    onSuccess: () => { toast.success("Pool unmounted"); qc.invalidateQueries({ queryKey: ["storage-pools"] }); },
    onError: (e) => toast.error(friendlyError(e, "Couldn't unmount the pool.")),
  });

  return (
    <div
      className="rounded p-4"
      style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <HardDrive className="h-4 w-4 flex-shrink-0" style={{ color: "var(--console-muted)" }} />
          <span className="font-telemetry text-xs font-semibold" style={{ color: "var(--console-text)" }}>
            {pool.name}
          </span>
          {pool.is_default && (
            <span
              className="font-telemetry text-[10px] px-1.5 py-0.5 rounded"
              style={{ background: "var(--console-raised)", color: "var(--console-accent)", border: "1px solid var(--console-border)" }}
            >
              DEFAULT
            </span>
          )}
          {!online && (
            <span
              className="font-telemetry text-[10px] px-1.5 py-0.5 rounded inline-flex items-center gap-1"
              style={{ background: "var(--console-raised)", color: "var(--console-rec)", border: "1px solid var(--console-border)" }}
              title="Storage path is missing or the mount is offline"
            >
              <WifiOff className="h-2.5 w-2.5" /> OFFLINE
            </span>
          )}
        </div>
        {canManage && (
          <div className="flex gap-0.5">
            {isNas && (
              mountState !== "mounted" ? (
                <GhostIconBtn title="Mount" onClick={() => mountMut.mutate()} disabled={mountMut.isPending}>
                  <Plug className="h-3.5 w-3.5" />
                </GhostIconBtn>
              ) : (
                <GhostIconBtn title="Unmount" onClick={() => unmountMut.mutate()} disabled={unmountMut.isPending}>
                  <Unplug className="h-3.5 w-3.5" />
                </GhostIconBtn>
              )
            )}
            <GhostIconBtn onClick={onEdit}>
              <Edit2 className="h-3.5 w-3.5" />
            </GhostIconBtn>
            <GhostIconBtn onClick={onDelete}>
              <Trash2 className="h-3.5 w-3.5" style={{ color: "var(--console-rec)" }} />
            </GhostIconBtn>
          </div>
        )}
      </div>
      <p className="font-telemetry text-[10px] truncate mb-1" style={{ color: "var(--console-muted)" }}>
        {pool.path}
      </p>
      <p className="font-telemetry text-[10px] mb-2" style={{ color: "var(--console-muted)" }}>
        Type: {pool.pool_type} | Priority: {pool.priority}
        {pool.recording_count > 0 && ` | ${pool.recording_count} recordings`}
      </p>
      {isNas && (
        <div className="flex items-center gap-2 mb-2 font-telemetry text-[10px]">
          <span style={{ color: mountColor }}>
            {mountState === "mounted"
              ? <Wifi className="h-3 w-3 inline mr-1" />
              : <WifiOff className="h-3 w-3 inline mr-1" />}
            {mountState}
          </span>
          {pool.nas_server && (
            <span style={{ color: "var(--console-muted)" }}>
              {pool.nas_server}:{pool.nas_share}
            </span>
          )}
          {pool.nas_last_mount_error && (
            <span style={{ color: "var(--console-rec)" }} title={pool.nas_last_mount_error} className="truncate">
              {pool.nas_last_mount_error}
            </span>
          )}
        </div>
      )}
      {!online ? (
        <div className="font-telemetry text-[10px]" style={{ color: "var(--console-rec)" }}>
          Storage offline — usage unavailable
        </div>
      ) : capacity > 0 ? (
        <>
          <div className="h-1.5 rounded-full overflow-hidden mb-2" style={{ background: "var(--console-raised)" }}>
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.min(usedPct, 100)}%`, background: barColor }}
            />
          </div>
          <div className="flex justify-between font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
            <span>{fmtBytes(used)} used</span>
            <span>{fmtBytes(free)} free</span>
            <span>{fmtBytes(capacity)} total</span>
          </div>
        </>
      ) : (
        <div className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
          {fmtBytes(used)} used (unlimited capacity)
        </div>
      )}
      {online && isFull ? (
        <div className="mt-3 flex items-center gap-1 font-telemetry text-[10px]" style={{ color: "var(--console-rec)" }}>
          <AlertTriangle className="h-3 w-3" />
          Storage full
        </div>
      ) : online && usedPct > 90 ? (
        <div className="mt-3 flex items-center gap-1 font-telemetry text-[10px]" style={{ color: "var(--console-rec)" }}>
          <AlertTriangle className="h-3 w-3" />
          Storage nearly full
        </div>
      ) : null}
    </div>
  );
};

const EmptyState = ({ text }) => (
  <div
    className="rounded p-10 text-center font-telemetry text-xs"
    style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)", color: "var(--console-muted)" }}
  >
    {text}
  </div>
);

// ── Pool Form Dialog ───────────────────────────────────────────────────────────

const PoolFormDialog = ({ open, onOpenChange, pool, queryClient }) => {
  const isEdit = !!pool;
  const [form, setForm] = useState({
    name: "", path: "", pool_type: "local", max_size_bytes: "",
    priority: "0", is_default: false, nas_server: "", nas_share: "",
    nas_protocol: "nfs", nas_username: "", nas_password: "", nas_domain: "",
    nas_auto_mount: true,
  });

  React.useEffect(() => {
    if (pool) {
      setForm({
        name: pool.name || "", path: pool.path || "", pool_type: pool.pool_type || "local",
        max_size_bytes: pool.max_size_bytes || "", priority: String(pool.priority ?? 0),
        is_default: pool.is_default ?? false, nas_server: pool.nas_server || "",
        nas_share: pool.nas_share || "", nas_protocol: pool.nas_protocol || "nfs",
        nas_username: pool.nas_username || "", nas_password: "",
        nas_domain: pool.nas_domain || "", nas_auto_mount: pool.nas_auto_mount ?? true,
      });
    } else {
      setForm({
        name: "", path: "", pool_type: "local", max_size_bytes: "",
        priority: "0", is_default: false, nas_server: "", nas_share: "",
        nas_protocol: "nfs", nas_username: "", nas_password: "", nas_domain: "",
        nas_auto_mount: true,
      });
    }
  }, [pool, open]);

  const mutation = useMutation({
    mutationFn: (data) => isEdit ? updateStoragePool(pool.id, data) : createStoragePool(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storage-pools"] });
      queryClient.invalidateQueries({ queryKey: ["storage-summary"] });
      onOpenChange(false);
      toast.success(isEdit ? "Pool updated" : "Pool created");
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't save the pool.")),
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    const payload = {
      name: form.name, path: form.path, pool_type: form.pool_type,
      max_size_bytes: parseInt(form.max_size_bytes, 10) || null,
      priority: parseInt(form.priority, 10) || 0, is_default: form.is_default,
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
      <DialogContent
        className="sm:max-w-md"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)", color: "var(--console-text)" }}
      >
        <DialogHeader>
          <DialogTitle className="font-telemetry text-xs uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
            {isEdit ? "Edit Storage Pool" : "New Storage Pool"}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-3">
          <DialogField label="Name">
            <ConsoleInput value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="primary" required />
          </DialogField>
          <DialogField label="Path">
            <ConsoleInput value={form.path} onChange={(e) => set("path", e.target.value)} placeholder="/data/recordings" required disabled={isEdit} />
          </DialogField>
          <div className="grid grid-cols-2 gap-3">
            <DialogField label="Type">
              <Select value={form.pool_type} onValueChange={(v) => set("pool_type", v)}>
                <SelectTrigger className="h-[30px] text-xs font-telemetry" style={inputStyle}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="local">Local</SelectItem>
                  <SelectItem value="nfs">NFS</SelectItem>
                  <SelectItem value="smb">SMB</SelectItem>
                </SelectContent>
              </Select>
            </DialogField>
            <DialogField label="Priority">
              <ConsoleInput type="number" value={form.priority} onChange={(e) => set("priority", e.target.value)} />
            </DialogField>
          </div>
          <DialogField label="Max Size (bytes)" help="e.g., 1099511627776 = 1 TB. Leave empty for unlimited.">
            <ConsoleInput type="number" value={form.max_size_bytes} onChange={(e) => set("max_size_bytes", e.target.value)} placeholder="Leave empty for unlimited" />
          </DialogField>

          {form.pool_type !== "local" && (
            <div
              className="space-y-3 border-t pt-3"
              style={{ borderColor: "var(--console-border)" }}
            >
              <div className="flex items-center gap-2 font-telemetry text-[11px] uppercase tracking-wide" style={{ color: "var(--console-muted)" }}>
                <Server className="h-3.5 w-3.5" /> NAS Configuration
              </div>
              <div className="grid grid-cols-2 gap-3">
                <DialogField label="Server / IP">
                  <ConsoleInput value={form.nas_server} onChange={(e) => set("nas_server", e.target.value)} placeholder="192.168.1.50" required={form.pool_type !== "local"} />
                </DialogField>
                <DialogField label="Share / Export">
                  <ConsoleInput value={form.nas_share} onChange={(e) => set("nas_share", e.target.value)} placeholder="recordings" required={form.pool_type !== "local"} />
                </DialogField>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <DialogField label="Protocol">
                  <Select value={form.nas_protocol} onValueChange={(v) => set("nas_protocol", v)}>
                    <SelectTrigger className="h-[30px] text-xs font-telemetry" style={inputStyle}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="nfs">NFS</SelectItem>
                      <SelectItem value="smb">SMB / CIFS</SelectItem>
                    </SelectContent>
                  </Select>
                </DialogField>
                <DialogField label="Domain / Workgroup">
                  <ConsoleInput value={form.nas_domain} onChange={(e) => set("nas_domain", e.target.value)} placeholder="WORKGROUP" />
                </DialogField>
              </div>
              {form.nas_protocol === "smb" && (
                <div className="grid grid-cols-2 gap-3">
                  <DialogField label="Username">
                    <ConsoleInput value={form.nas_username} onChange={(e) => set("nas_username", e.target.value)} placeholder="admin" />
                  </DialogField>
                  <DialogField label="Password">
                    <ConsoleInput type="password" value={form.nas_password} onChange={(e) => set("nas_password", e.target.value)} placeholder={isEdit ? "Leave blank to keep" : ""} />
                  </DialogField>
                </div>
              )}
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="nas_auto_mount"
                  checked={form.nas_auto_mount}
                  onChange={(e) => set("nas_auto_mount", e.target.checked)}
                  className="rounded"
                  style={{ accentColor: "var(--console-accent)" }}
                />
                <label htmlFor="nas_auto_mount" className="font-telemetry text-xs cursor-pointer" style={{ color: "var(--console-text)" }}>
                  Auto-mount on startup
                </label>
              </div>
              {!isEdit && (
                <SecondaryBtn
                  type="button"
                  className="w-full justify-center"
                  onClick={() => {
                    testNasConnection({
                      server: form.nas_server, protocol: form.nas_protocol,
                      username: form.nas_username, password: form.nas_password, domain: form.nas_domain,
                    })
                      .then((res) => { if (res.ok) toast.success(res.message); else toast.error(res.message); })
                      .catch((e) => toast.error(friendlyError(e, "Connection test failed.")));
                  }}
                  disabled={!form.nas_server}
                >
                  <TestTube className="h-3.5 w-3.5 mr-1.5" />
                  Test Connection
                </SecondaryBtn>
              )}
            </div>
          )}

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="is_default"
              checked={form.is_default}
              onChange={(e) => set("is_default", e.target.checked)}
              className="rounded"
              style={{ accentColor: "var(--console-accent)" }}
            />
            <label htmlFor="is_default" className="font-telemetry text-xs cursor-pointer" style={{ color: "var(--console-text)" }}>
              Set as default pool
            </label>
          </div>
          <DialogFooter>
            <PrimaryBtn type="submit" disabled={mutation.isPending}>
              {isEdit ? "Update" : "Create"}
            </PrimaryBtn>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

// ── Rule Form Dialog ───────────────────────────────────────────────────────────

const RuleFormDialog = ({ open, onOpenChange, pools, queryClient }) => {
  const [form, setForm] = useState({ name: "", source_pool_id: "", target_pool_id: "", age_threshold_hours: "" });

  React.useEffect(() => {
    if (open) setForm({ name: "", source_pool_id: "", target_pool_id: "", age_threshold_hours: "" });
  }, [open]);

  const mutation = useMutation({
    mutationFn: (data) => createStorageRule(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storage-rules"] });
      onOpenChange(false);
      toast.success("Rule created");
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't create the rule.")),
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    mutation.mutate({
      name: form.name, source_pool_id: form.source_pool_id,
      target_pool_id: form.target_pool_id,
      age_threshold_hours: parseInt(form.age_threshold_hours, 10) || 24,
    });
  };

  const set = (key, val) => setForm((p) => ({ ...p, [key]: val }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)", color: "var(--console-text)" }}
      >
        <DialogHeader>
          <DialogTitle className="font-telemetry text-xs uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
            New Tier Rule
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-3">
          <DialogField label="Rule Name">
            <ConsoleInput value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Move old recordings to archive" required />
          </DialogField>
          <DialogField label="Source Pool">
            <Select value={form.source_pool_id} onValueChange={(v) => set("source_pool_id", v)}>
              <SelectTrigger className="h-[30px] text-xs font-telemetry" style={inputStyle}>
                <SelectValue placeholder="Select source pool…" />
              </SelectTrigger>
              <SelectContent>
                {pools.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </DialogField>
          <DialogField label="Target Pool">
            <Select value={form.target_pool_id} onValueChange={(v) => set("target_pool_id", v)}>
              <SelectTrigger className="h-[30px] text-xs font-telemetry" style={inputStyle}>
                <SelectValue placeholder="Select target pool…" />
              </SelectTrigger>
              <SelectContent>
                {pools.filter((p) => p.id !== form.source_pool_id).map((p) => (
                  <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </DialogField>
          <DialogField label="Age Threshold (hours)" help="Recordings older than this will be moved from source → target pool">
            <ConsoleInput type="number" value={form.age_threshold_hours} onChange={(e) => set("age_threshold_hours", e.target.value)} placeholder="e.g., 168 (7 days)" required min="1" />
          </DialogField>
          <DialogFooter>
            <PrimaryBtn type="submit" disabled={mutation.isPending}>
              Create Rule
            </PrimaryBtn>
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
    name: "", provider: "s3", endpoint: "", bucket: "", region: "us-east-1",
    access_key: "", secret_key: "", prefix: "recordings/", sync_enabled: false,
  });

  React.useEffect(() => {
    if (config) {
      setForm({
        name: config.name || "", provider: config.provider || "s3",
        endpoint: config.endpoint || "", bucket: config.bucket || "",
        region: config.region || "us-east-1", access_key: "", secret_key: "",
        prefix: config.prefix || "recordings/", sync_enabled: config.sync_enabled ?? false,
      });
    } else {
      setForm({ name: "", provider: "s3", endpoint: "", bucket: "", region: "us-east-1", access_key: "", secret_key: "", prefix: "recordings/", sync_enabled: false });
    }
  }, [config, open]);

  const mutation = useMutation({
    mutationFn: (data) => isEdit ? updateCloudConfig(config.id, data) : createCloudConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cloud-configs"] });
      onOpenChange(false);
      toast.success(isEdit ? "Cloud config updated" : "Cloud config created");
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't save the cloud config.")),
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    const payload = { ...form };
    if (isEdit) { if (!payload.access_key) delete payload.access_key; if (!payload.secret_key) delete payload.secret_key; }
    mutation.mutate(payload);
  };

  const set = (key, val) => setForm((p) => ({ ...p, [key]: val }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-lg"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)", color: "var(--console-text)" }}
      >
        <DialogHeader>
          <DialogTitle className="font-telemetry text-xs uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
            {isEdit ? "Edit Cloud Config" : "New Cloud Storage Config"}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
          <DialogField label="Name">
            <ConsoleInput value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="My S3 Backup" required />
          </DialogField>
          <div className="grid grid-cols-2 gap-3">
            <DialogField label="Provider">
              <Select value={form.provider} onValueChange={(v) => set("provider", v)}>
                <SelectTrigger className="h-[30px] text-xs font-telemetry" style={inputStyle}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="s3">AWS S3</SelectItem>
                  <SelectItem value="minio">MinIO</SelectItem>
                  <SelectItem value="b2">Backblaze B2</SelectItem>
                  <SelectItem value="gcs">Google Cloud</SelectItem>
                </SelectContent>
              </Select>
            </DialogField>
            <DialogField label="Region">
              <ConsoleInput value={form.region} onChange={(e) => set("region", e.target.value)} placeholder="us-east-1" />
            </DialogField>
          </div>
          <DialogField label="Bucket">
            <ConsoleInput value={form.bucket} onChange={(e) => set("bucket", e.target.value)} placeholder="my-nvr-bucket" required />
          </DialogField>
          <DialogField label="Endpoint (for MinIO/custom S3)" help="Leave empty for standard AWS S3">
            <ConsoleInput value={form.endpoint} onChange={(e) => set("endpoint", e.target.value)} placeholder="https://minio.example.com:9000" />
          </DialogField>
          <DialogField label="Prefix">
            <ConsoleInput value={form.prefix} onChange={(e) => set("prefix", e.target.value)} placeholder="recordings/" />
          </DialogField>
          <div className="grid grid-cols-2 gap-3">
            <DialogField label="Access Key">
              <ConsoleInput value={form.access_key} onChange={(e) => set("access_key", e.target.value)} placeholder={isEdit ? "••••••••" : "AKIA..."} />
            </DialogField>
            <DialogField label="Secret Key">
              <ConsoleInput type="password" value={form.secret_key} onChange={(e) => set("secret_key", e.target.value)} placeholder={isEdit ? "••••••••" : ""} />
            </DialogField>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="sync_enabled"
              checked={form.sync_enabled}
              onChange={(e) => set("sync_enabled", e.target.checked)}
              className="rounded"
              style={{ accentColor: "var(--console-accent)" }}
            />
            <label htmlFor="sync_enabled" className="font-telemetry text-xs cursor-pointer" style={{ color: "var(--console-text)" }}>
              Auto-sync new recordings to this cloud storage
            </label>
          </div>
          <DialogFooter>
            <PrimaryBtn type="submit" disabled={mutation.isPending}>
              {isEdit ? "Update" : "Create"}
            </PrimaryBtn>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

// ── Shared button primitives ───────────────────────────────────────────────────

const PrimaryBtn = ({ children, disabled, onClick, type = "button", className = "" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className={`inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] font-semibold uppercase tracking-wide transition-opacity disabled:opacity-50 ${className}`}
    style={{ background: "var(--console-accent)", color: "#06231f" }}
  >
    {children}
  </button>
);

const SecondaryBtn = ({ children, disabled, onClick, type = "button", className = "" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className={`inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] border transition-colors hover:bg-white/5 disabled:opacity-50 ${className}`}
    style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}
  >
    {children}
  </button>
);

const GhostIconBtn = ({ children, onClick, disabled, title, className = "" }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    title={title}
    className={`h-7 w-7 flex items-center justify-center rounded transition-colors hover:bg-white/5 disabled:opacity-50 ${className}`}
    style={{ color: "var(--console-muted)" }}
  >
    {children}
  </button>
);

const DialogField = ({ label, help, children }) => (
  <div>
    <label className="block font-telemetry text-[10px] uppercase tracking-wide mb-1" style={{ color: "var(--console-muted)" }}>
      {label}
    </label>
    {children}
    {help && <p className="font-telemetry text-[10px] mt-1" style={{ color: "var(--console-muted)" }}>{help}</p>}
  </div>
);

const ConsoleInput = (props) => (
  <input
    {...props}
    className="w-full rounded font-telemetry text-xs h-[30px] px-2 border outline-none focus:ring-1"
    style={{
      background: "var(--console-raised)",
      border: "1px solid var(--console-border)",
      color: "var(--console-text)",
      "--tw-ring-color": "var(--console-accent)",
    }}
  />
);

const ConsoleSelect = ({ children, ...props }) => (
  <select
    {...props}
    className="w-full rounded font-telemetry text-xs h-[30px] px-2 border outline-none focus:ring-1"
    style={{
      background: "var(--console-raised)",
      border: "1px solid var(--console-border)",
      color: "var(--console-text)",
      "--tw-ring-color": "var(--console-accent)",
    }}
  >
    {children}
  </select>
);

export default Storage;
