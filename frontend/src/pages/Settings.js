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
  Users,
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
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/ui/tabs";
import { toast } from "sonner";
import { useAuth } from "../context/AuthContext";

const Settings = () => {
  const qc = useQueryClient();
  const { isAdmin } = useAuth();

  // Lazy-load Users component only when needed
  const UsersPanel = React.lazy(() => import("./Users"));

  return (
    <div className="p-4 md:p-8 h-full overflow-y-auto">
      {/* Header */}
      <div className="mb-6 md:mb-8">
        <h1
          className="text-2xl md:text-3xl font-bold text-white  tracking-tight"
          style={{ fontFamily: "Manrope, sans-serif" }}
        >
          Settings
        </h1>
        <p className="text-muted-foreground dark:text-muted-foreground mt-1 text-sm md:text-base">
          System configuration and preferences
        </p>
      </div>

      <Tabs defaultValue="retention" className="space-y-4 md:space-y-6">
        <TabsList className="flex-wrap h-auto gap-1">
          <TabsTrigger
            value="retention"
            className="gap-1 md:gap-2 text-xs md:text-sm"
          >
            <Clock className="h-3 w-3 md:h-4 md:w-4" />
            <span className="hidden sm:inline">Retention</span>
          </TabsTrigger>
          <TabsTrigger
            value="recording"
            className="gap-1 md:gap-2 text-xs md:text-sm"
          >
            <Video className="h-3 w-3 md:h-4 md:w-4" />
            <span className="hidden sm:inline">Recording</span>
          </TabsTrigger>
          <TabsTrigger
            value="general"
            className="gap-1 md:gap-2 text-xs md:text-sm"
          >
            <SettingsIcon className="h-3 w-3 md:h-4 md:w-4" />
            <span className="hidden sm:inline">General</span>
          </TabsTrigger>
          <TabsTrigger
            value="system"
            className="gap-1 md:gap-2 text-xs md:text-sm"
          >
            <Database className="h-3 w-3 md:h-4 md:w-4" />
            <span className="hidden sm:inline">System</span>
          </TabsTrigger>
          {isAdmin && (
            <TabsTrigger
              value="users"
              className="gap-1 md:gap-2 text-xs md:text-sm"
            >
              <Users className="h-3 w-3 md:h-4 md:w-4" />
              <span className="hidden sm:inline">Users</span>
            </TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="retention">
          <RetentionTab queryClient={qc} />
        </TabsContent>
        <TabsContent value="recording">
          <RecordingTab queryClient={qc} />
        </TabsContent>
        <TabsContent value="general">
          <GeneralTab queryClient={qc} />
        </TabsContent>
        <TabsContent value="system">
          <SystemTab />
        </TabsContent>
        {isAdmin && (
          <TabsContent value="users">
            <React.Suspense
              fallback={<p className="text-sm text-muted-foreground p-4">Loading…</p>}
            >
              <UsersPanel />
            </React.Suspense>
          </TabsContent>
        )}
      </Tabs>
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
    <Card
      title="Retention Policy"
      description="Configure how long recordings are kept before auto-deletion"
    >
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading...</p>
      ) : (
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <Switch
              checked={form.enabled}
              onCheckedChange={(v) => set("enabled", v)}
            />
            <Label>Enable automatic retention cleanup</Label>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <Label>Retention Period (days)</Label>
              <Input
                type="number"
                min={1}
                max={3650}
                value={form.days}
                onChange={(e) =>
                  set("days", parseInt(e.target.value, 10) || 30)
                }
                className="mt-1"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Recordings older than this will be deleted
              </p>
            </div>
            <div>
              <Label>Max Storage (GB)</Label>
              <Input
                type="number"
                min={0}
                value={form.max_storage_gb}
                onChange={(e) =>
                  set("max_storage_gb", parseInt(e.target.value, 10) || 0)
                }
                className="mt-1"
              />
              <p className="text-xs text-muted-foreground mt-1">
                0 = unlimited storage
              </p>
            </div>
            <div>
              <Label>Check Interval (minutes)</Label>
              <Input
                type="number"
                min={5}
                max={1440}
                value={form.check_interval_min}
                onChange={(e) =>
                  set("check_interval_min", parseInt(e.target.value, 10) || 60)
                }
                className="mt-1"
              />
              <p className="text-xs text-muted-foreground mt-1">
                How often to run cleanup
              </p>
            </div>
          </div>
          <Button
            onClick={() => mutation.mutate(form)}
            disabled={mutation.isPending}
          >
            <Save className="h-4 w-4 mr-2" />
            Save Changes
          </Button>
        </div>
      )}
    </Card>
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
    <Card
      title="Recording Configuration"
      description="Default recording parameters for all cameras"
    >
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading...</p>
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <Label>Segment Duration (seconds)</Label>
              <Input
                type="number"
                min={60}
                max={7200}
                value={form.segment_duration}
                onChange={(e) =>
                  set("segment_duration", parseInt(e.target.value, 10) || 900)
                }
                className="mt-1"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Split recordings into segments (60–7200s)
              </p>
            </div>
            <div>
              <Label>Default FPS</Label>
              <Input
                type="number"
                min={0}
                max={60}
                value={form.default_fps}
                onChange={(e) =>
                  set("default_fps", parseInt(e.target.value, 10) || 0)
                }
                className="mt-1"
              />
              <p className="text-xs text-muted-foreground mt-1">0 = use source FPS</p>
            </div>
            <div>
              <Label>Recording Format</Label>
              <select
                value={form.format}
                onChange={(e) => set("format", e.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
              >
                <option value="mp4">MP4</option>
                <option value="mkv">MKV</option>
              </select>
              <p className="text-xs text-muted-foreground mt-1">
                Container format for recordings
              </p>
            </div>
          </div>

          <div className="border-t border-slate-100 pt-4 space-y-3">
            <h3 className="text-sm font-medium text-zinc-200">
              Recording Settings
            </h3>
            <div className="flex items-center gap-3">
              <Switch
                checked={form.ffmpeg_recovery}
                onCheckedChange={(v) => set("ffmpeg_recovery", v)}
              />
              <Label>Auto-recover camera streams after failure</Label>
            </div>
            <div className="w-48">
              <Label>Health Check Interval (seconds)</Label>
              <Input
                type="number"
                min={10}
                max={300}
                value={form.health_check_interval}
                onChange={(e) =>
                  set(
                    "health_check_interval",
                    parseInt(e.target.value, 10) || 30,
                  )
                }
                className="mt-1"
              />
            </div>
          </div>

          <Button
            onClick={() => mutation.mutate(form)}
            disabled={mutation.isPending}
          >
            <Save className="h-4 w-4 mr-2" />
            Save Changes
          </Button>
        </div>
      )}
    </Card>
  );
};

// ---------- General ----------

const GeneralTab = ({ queryClient }) => {
  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });

  const [form, setForm] = useState({});

  // Transform array of {key, value} objects to flat {key: value} map
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
    <Card title="General Settings" description="Application-wide preferences">
      <div className="space-y-4">
        <div>
          <Label>System Name</Label>
          <Input
            value={form.system_name ?? ""}
            onChange={(e) => set("system_name", e.target.value)}
            className="w-80 mt-1"
            placeholder="GVD NVR"
          />
        </div>
        <div>
          <Label>Timezone</Label>
          <Input
            value={form.timezone ?? ""}
            onChange={(e) => set("timezone", e.target.value)}
            className="w-48 mt-1"
            placeholder="UTC"
          />
        </div>
        <Button
          onClick={() => mutation.mutate({ settings: form })}
          disabled={mutation.isPending}
        >
          <Save className="h-4 w-4 mr-2" />
          Save Changes
        </Button>
      </div>
    </Card>
  );
};

// ---------- System info ----------

const SystemTab = () => {
  const { data: health, isLoading } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30000,
  });

  return (
    <Card
      title="System Information"
      description="Health check and version info"
    >
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : health ? (
        <div className="space-y-3 text-sm">
          <Row label="Status" value={health.status || "unknown"} />
          <Row label="Version" value={health.version || "-"} />
          <Row label="Streaming Service" value={health.go2rtc && health.go2rtc !== "disconnected" ? "Connected" : "Disconnected"} />
          <Row
            label="Active Recordings"
            value={health.active_recordings ?? "-"}
          />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Unable to fetch health info</p>
      )}
    </Card>
  );
};

// ---------- shared UI ----------

const Card = ({ title, description, children }) => (
  <div className="bg-card border border-border rounded-lg p-6">
    <h2 className="text-lg font-semibold text-white">{title}</h2>
    {description && (
      <p className="text-sm text-muted-foreground mt-1 mb-6">{description}</p>
    )}
    {children}
  </div>
);

const Row = ({ label, value }) => (
  <div className="flex justify-between">
    <span className="text-muted-foreground">{label}</span>
    <span className="text-white font-medium">{value}</span>
  </div>
);

export default Settings;
