// =============================================================================
// Settings — Retention, Recording, General, System config
// =============================================================================

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Settings as SettingsIcon,
  Save,
  Clock,
  Video,
  Database,
  Shield,
} from "lucide-react";
import {
  getRetentionConfig,
  updateRetentionConfig,
  getRecordingConfig,
  updateRecordingConfig,
  getSettings,
  updateSettings,
  getHealth,
} from "../api/settings";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Switch } from "../components/ui/switch";
import { toast } from "sonner";

// ── shared styles ─────────────────────────────────────────────────────────────

const inputStyle = {
  background: "var(--console-raised)",
  border: "1px solid var(--console-border)",
  color: "var(--console-text)",
};

const TABS = [
  { id: "retention", label: "Retention", icon: Clock },
  { id: "recording", label: "Recording", icon: Video },
  { id: "general", label: "General", icon: SettingsIcon },
  { id: "security", label: "Security", icon: Shield },
  { id: "system", label: "System", icon: Database },
];

const Settings = () => {
  const qc = useQueryClient();
  const [tab, setTab] = useState("retention");

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
          Configuration
        </span>
      </div>

      {/* Internal tab bar */}
      <div
        className="flex items-center gap-0 border-b flex-shrink-0 overflow-x-auto"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        {TABS.map(({ id, label, icon: Icon }) => {
          const active = tab === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
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
        <div className="mx-auto max-w-5xl">
          {tab === "retention" && <RetentionTab queryClient={qc} />}
          {tab === "recording" && <RecordingTab queryClient={qc} />}
          {tab === "general" && <GeneralTab queryClient={qc} />}
          {tab === "security" && <SecurityTab queryClient={qc} />}
          {tab === "system" && <SystemTab />}
        </div>
      </div>
    </div>
  );
};

// ---------- Retention ----------

const RetentionTab = ({ queryClient }) => {
  const { data: config, isLoading } = useQuery({
    queryKey: ["retention-config"],
    queryFn: getRetentionConfig,
  });

  const [form, setForm] = useState({
    enabled: true,
    days: 30,
    max_storage_gb: 0,
    check_interval_min: 60,
  });

  React.useEffect(() => {
    if (config) {
      setForm({
        enabled: config.enabled ?? true,
        days: config.days ?? 30,
        max_storage_gb: config.max_storage_gb ?? 0,
        check_interval_min: config.check_interval_min ?? 60,
      });
    }
  }, [config]);

  const mutation = useMutation({
    mutationFn: (data) => updateRetentionConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["retention-config"] });
      toast.success("Retention policy updated");
    },
    onError: (e) =>
      toast.error(e.response?.data?.detail || "Failed to update retention"),
  });

  const set = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  return (
    <ConsoleCard icon={Clock} title="Retention Policy" description="Configure how long recordings are kept before auto-deletion.">
      {isLoading ? (
        <p className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>Loading…</p>
      ) : (
        <div className="space-y-5">
          <div
            className="flex items-center gap-3 rounded px-4 py-3"
            style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
          >
            <Switch
              checked={form.enabled}
              onCheckedChange={(v) => set("enabled", v)}
            />
            <Label className="font-telemetry text-xs" style={{ color: "var(--console-text)" }}>
              Enable automatic retention cleanup
            </Label>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            <FieldGroup label="Retention Period (days)" help="Recordings older than this will be deleted">
              <ConsoleInput
                type="number"
                min={1}
                max={3650}
                value={form.days}
                onChange={(e) => set("days", parseInt(e.target.value, 10) || 30)}
              />
            </FieldGroup>
            <FieldGroup label="Max Storage (GB)" help="0 = unlimited storage">
              <ConsoleInput
                type="number"
                min={0}
                value={form.max_storage_gb}
                onChange={(e) => set("max_storage_gb", parseInt(e.target.value, 10) || 0)}
              />
            </FieldGroup>
            <FieldGroup label="Check Interval (minutes)" help="How often to run cleanup">
              <ConsoleInput
                type="number"
                min={5}
                max={1440}
                value={form.check_interval_min}
                onChange={(e) => set("check_interval_min", parseInt(e.target.value, 10) || 60)}
              />
            </FieldGroup>
          </div>
          <div>
            <PrimaryButton
              onClick={() => mutation.mutate(form)}
              disabled={mutation.isPending || isLoading}
            >
              <Save className="h-3.5 w-3.5 mr-1.5" />
              Save Changes
            </PrimaryButton>
          </div>
        </div>
      )}
    </ConsoleCard>
  );
};

// ---------- Recording ----------

const RecordingTab = ({ queryClient }) => {
  const { data: config, isLoading } = useQuery({
    queryKey: ["recording-config"],
    queryFn: getRecordingConfig,
  });

  const [form, setForm] = useState({
    segment_duration: 900,
    default_fps: 0,
    format: "mp4",
    ffmpeg_recovery: true,
    health_check_interval: 30,
  });

  React.useEffect(() => {
    if (config) {
      setForm({
        segment_duration: config.segment_duration ?? 900,
        default_fps: config.default_fps ?? 0,
        format: config.format ?? "mp4",
        ffmpeg_recovery: config.ffmpeg_recovery ?? true,
        health_check_interval: config.health_check_interval ?? 30,
      });
    }
  }, [config]);

  const mutation = useMutation({
    mutationFn: (data) => updateRecordingConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recording-config"] });
      toast.success("Recording config updated");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Failed"),
  });

  const set = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  return (
    <ConsoleCard icon={Video} title="Recording Configuration" description="Default recording parameters applied to all cameras.">
      {isLoading ? (
        <p className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>Loading…</p>
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            <FieldGroup label="Segment Duration (seconds)" help="Split recordings into segments (60–7200s)">
              <ConsoleInput
                type="number"
                min={60}
                max={7200}
                value={form.segment_duration}
                onChange={(e) => set("segment_duration", parseInt(e.target.value, 10) || 900)}
              />
            </FieldGroup>
            <FieldGroup label="Default FPS" help="0 = use source FPS">
              <ConsoleInput
                type="number"
                min={0}
                max={60}
                value={form.default_fps}
                onChange={(e) => set("default_fps", parseInt(e.target.value, 10) || 0)}
              />
            </FieldGroup>
            <FieldGroup label="Recording Format" help="Container format for recordings">
              <select
                value={form.format}
                onChange={(e) => set("format", e.target.value)}
                className="w-full rounded font-telemetry text-xs h-[30px] px-2 outline-none focus:ring-1"
                style={{ ...inputStyle, "--tw-ring-color": "var(--console-accent)" }}
              >
                <option value="mp4">MP4</option>
                <option value="mkv">MKV</option>
              </select>
            </FieldGroup>
          </div>

          <div
            className="border-t pt-4 space-y-3"
            style={{ borderColor: "var(--console-border)" }}
          >
            <p
              className="font-telemetry text-[11px] uppercase tracking-wide"
              style={{ color: "var(--console-muted)" }}
            >
              Recording Settings
            </p>
            <div
              className="flex items-center gap-3 rounded px-4 py-3"
              style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
            >
              <Switch
                checked={form.ffmpeg_recovery}
                onCheckedChange={(v) => set("ffmpeg_recovery", v)}
              />
              <Label className="font-telemetry text-xs" style={{ color: "var(--console-text)" }}>
                Auto-recover camera streams after failure
              </Label>
            </div>
            <div className="w-full sm:w-48">
              <FieldGroup label="Health Check Interval (seconds)">
                <ConsoleInput
                  type="number"
                  min={10}
                  max={300}
                  value={form.health_check_interval}
                  onChange={(e) => set("health_check_interval", parseInt(e.target.value, 10) || 30)}
                />
              </FieldGroup>
            </div>
          </div>
          <div>
            <PrimaryButton
              onClick={() => mutation.mutate(form)}
              disabled={mutation.isPending || isLoading}
            >
              <Save className="h-3.5 w-3.5 mr-1.5" />
              Save Changes
            </PrimaryButton>
          </div>
        </div>
      )}
    </ConsoleCard>
  );
};

// ---------- General ----------

const GeneralTab = ({ queryClient }) => {
  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });

  const [form, setForm] = useState({});

  React.useEffect(() => {
    if (settings) {
      if (Array.isArray(settings)) {
        const flat = {};
        settings.forEach((s) => {
          flat[s.key] = s.value;
        });
        setForm(flat);
      } else {
        setForm(settings);
      }
    }
  }, [settings]);

  const mutation = useMutation({
    mutationFn: (data) => updateSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      toast.success("Settings saved");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Failed"),
  });

  const set = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  return (
    <ConsoleCard icon={SettingsIcon} title="General Settings" description="Application-wide identity and locale preferences.">
      <div className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <FieldGroup label="System Name">
            <ConsoleInput
              value={form.system_name ?? ""}
              onChange={(e) => set("system_name", e.target.value)}
              placeholder="GVD NVR"
            />
          </FieldGroup>
          <FieldGroup label="Timezone">
            <ConsoleInput
              value={form.timezone ?? ""}
              onChange={(e) => set("timezone", e.target.value)}
              placeholder="UTC"
            />
          </FieldGroup>
        </div>
        <div>
          <PrimaryButton
            onClick={() => mutation.mutate({ settings: form })}
            disabled={mutation.isPending}
          >
            <Save className="h-3.5 w-3.5 mr-1.5" />
            Save Changes
          </PrimaryButton>
        </div>
      </div>
    </ConsoleCard>
  );
};

// ---------- Security ----------

const SecurityTab = ({ queryClient }) => {
  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });

  const [form, setForm] = useState({
    password_min_length: 8,
    password_require_uppercase: "true",
    password_require_number: "true",
    password_require_symbol: "false",
    password_history_count: 0,
    password_max_age_days: 0,
  });

  React.useEffect(() => {
    if (settings) {
      const flat = Array.isArray(settings)
        ? Object.fromEntries(settings.map((s) => [s.key, s.value]))
        : settings;
      setForm({
        password_min_length: parseInt(flat.password_min_length ?? "8", 10),
        password_require_uppercase: flat.password_require_uppercase ?? "true",
        password_require_number: flat.password_require_number ?? "true",
        password_require_symbol: flat.password_require_symbol ?? "false",
        password_history_count: parseInt(flat.password_history_count ?? "0", 10),
        password_max_age_days: parseInt(flat.password_max_age_days ?? "0", 10),
      });
    }
  }, [settings]);

  const mutation = useMutation({
    mutationFn: (data) => updateSettings({ settings: data }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      toast.success("Security policy updated");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Failed to update"),
  });

  const set = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  return (
    <ConsoleCard icon={Shield} title="Password Policy" description="Control password strength and rotation requirements.">
      <div className="space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          <FieldGroup label="Minimum Length">
            <ConsoleInput
              type="number"
              min={4}
              max={64}
              value={form.password_min_length}
              onChange={(e) => set("password_min_length", parseInt(e.target.value, 10) || 8)}
            />
          </FieldGroup>
          <FieldGroup label="History Count" help="0 = disabled">
            <ConsoleInput
              type="number"
              min={0}
              max={24}
              value={form.password_history_count}
              onChange={(e) => set("password_history_count", parseInt(e.target.value, 10) || 0)}
            />
          </FieldGroup>
          <FieldGroup label="Max Age (days)" help="0 = never expires">
            <ConsoleInput
              type="number"
              min={0}
              max={365}
              value={form.password_max_age_days}
              onChange={(e) => set("password_max_age_days", parseInt(e.target.value, 10) || 0)}
            />
          </FieldGroup>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
          {[
            { key: "password_require_uppercase", label: "Require uppercase" },
            { key: "password_require_number", label: "Require number" },
            { key: "password_require_symbol", label: "Require symbol" },
          ].map(({ key, label }) => (
            <div
              key={key}
              className="flex items-center gap-2 rounded px-3 py-2.5"
              style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
            >
              <Switch
                checked={form[key] === "true"}
                onCheckedChange={(v) => set(key, v ? "true" : "false")}
              />
              <Label className="font-telemetry text-xs" style={{ color: "var(--console-text)" }}>
                {label}
              </Label>
            </div>
          ))}
        </div>
        <div>
          <PrimaryButton
            onClick={() => mutation.mutate({
              password_min_length: String(form.password_min_length),
              password_require_uppercase: form.password_require_uppercase,
              password_require_number: form.password_require_number,
              password_require_symbol: form.password_require_symbol,
              password_history_count: String(form.password_history_count),
              password_max_age_days: String(form.password_max_age_days),
            })}
            disabled={mutation.isPending}
          >
            <Save className="h-3.5 w-3.5 mr-1.5" />
            Save Policy
          </PrimaryButton>
        </div>
      </div>
    </ConsoleCard>
  );
};

// ---------- System info ----------

const SystemTab = () => {
  const { data: health, isLoading } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30000,
  });

  const streamingUp = health?.go2rtc && health.go2rtc !== "disconnected";

  return (
    <ConsoleCard icon={Database} title="System Information" description="Live health check and version info. Refreshes automatically.">
      {isLoading ? (
        <p className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>Loading…</p>
      ) : health ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile
            label="Status"
            value={health.status || "unknown"}
            tone={health.status === "healthy" || health.status === "ok" ? "ok" : "warn"}
          />
          <StatTile
            label="Streaming"
            value={streamingUp ? "Connected" : "Disconnected"}
            tone={streamingUp ? "ok" : "warn"}
          />
          <StatTile label="Active Recordings" value={health.active_recordings ?? "-"} />
          <StatTile label="Version" value={health.version || "-"} />
        </div>
      ) : (
        <p className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>
          Unable to fetch health info
        </p>
      )}
    </ConsoleCard>
  );
};

const StatTile = ({ label, value, tone }) => (
  <div
    className="rounded px-4 py-3"
    style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
  >
    <p className="font-telemetry text-[10px] uppercase tracking-wider" style={{ color: "var(--console-muted)" }}>
      {label}
    </p>
    <p
      className="mt-1 font-telemetry text-lg font-semibold"
      style={{
        color:
          tone === "ok"
            ? "var(--console-online)"
            : tone === "warn"
            ? "var(--console-alarm)"
            : "var(--console-text)",
      }}
    >
      {value}
    </p>
  </div>
);

// ---------- shared UI ----------

const ConsoleCard = ({ title, description, children, icon: Icon }) => (
  <div
    className="rounded p-5 md:p-6 mb-4"
    style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
  >
    <div className="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-5 md:gap-8">
      {/* Label column */}
      <div
        className="md:border-r md:pr-6"
        style={{ borderColor: "var(--console-border)" }}
      >
        <div className="flex items-center gap-2">
          {Icon && <Icon className="h-4 w-4 flex-shrink-0" style={{ color: "var(--console-accent)" }} />}
          <h2 className="font-telemetry text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
            {title}
          </h2>
        </div>
        {description && (
          <p className="font-telemetry text-xs mt-1.5 leading-relaxed" style={{ color: "var(--console-muted)" }}>
            {description}
          </p>
        )}
      </div>
      {/* Controls column */}
      <div className="min-w-0">{children}</div>
    </div>
  </div>
);

const FieldGroup = ({ label, help, children }) => (
  <div>
    <label className="block font-telemetry text-[11px] uppercase tracking-wide mb-1" style={{ color: "var(--console-muted)" }}>
      {label}
    </label>
    {children}
    {help && (
      <p className="font-telemetry text-[10px] mt-1" style={{ color: "var(--console-muted)" }}>
        {help}
      </p>
    )}
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

const PrimaryButton = ({ children, disabled, onClick, type = "button" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className="inline-flex items-center h-[30px] px-4 rounded font-telemetry text-xs font-semibold uppercase tracking-wide transition-opacity disabled:opacity-50"
    style={{ background: "var(--console-accent)", color: "#06231f" }}
  >
    {children}
  </button>
);

export default Settings;
