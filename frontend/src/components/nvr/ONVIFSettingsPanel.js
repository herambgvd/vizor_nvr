// =============================================================================
// ONVIF Settings Panel — Events, Imaging, Digital I/O, System
// =============================================================================

import React, { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Radio,
  Image,
  Cpu,
  Zap,
  RefreshCw,
  Power,
  Clock,
  Info,
  Save,
  RotateCcw,
  Focus,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Database,
  Search,
  Copy,
  PlayCircle,
} from "lucide-react";
import {
  getCamera,
  updateCamera,
  getONVIFDeviceInfo,
  getONVIFTime,
  syncONVIFTime,
  rebootCamera,
  factoryDefaultCamera,
  getImagingSettings,
  setImagingSettings,
  moveFocus,
  getRelayOutputs,
  triggerRelayOutput,
  getDigitalInputs,
  getOnvifEdgeRecordings,
  getOnvifReplayUri,
  getOnvifMetadataStream,
} from "../../api/cameras";
import { Button } from "../ui/button";
import { Switch } from "../ui/switch";
import { Label } from "../ui/label";
import { Slider } from "../ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../ui/tabs";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../ui/alert-dialog";
import { Badge } from "../ui/badge";
import { toast } from "sonner";
import { cn, friendlyError } from "../../lib/utils";
import { formatDateTime } from "../../lib/datetime";
import { usePermissions } from "../../hooks/usePermissions";

// ---------------------------------------------------------------------------
// Known ONVIF topic list for event filtering
// ---------------------------------------------------------------------------

const ONVIF_TOPICS = [
  { value: "tns1:VideoSource/MotionAlarm",               label: "Motion Alarm" },
  { value: "tns1:VideoSource/GlobalSceneChange/IVA",     label: "Scene Change (IVA)" },
  { value: "tns1:VideoAnalytics/Motion/Alarm",           label: "Video Analytics Motion" },
  { value: "tns1:VideoSource/ImageTooBlurry",            label: "Image Too Blurry (Tamper)" },
  { value: "tns1:VideoSource/ImageTooDark",              label: "Image Too Dark (Tamper)" },
  { value: "tns1:VideoSource/ImageTooBright",            label: "Image Too Bright" },
  { value: "tns1:VideoSource/GlobalSceneChange",         label: "Global Scene Change" },
  { value: "tns1:Device/Trigger/DigitalInput",           label: "Digital Input Trigger" },
  { value: "tns1:RuleEngine/LineDetector/Crossed",       label: "Line Crossing" },
  { value: "tns1:RuleEngine/FieldDetector/ObjectInside", label: "Zone Intrusion" },
  { value: "tns1:RuleEngine/CountAggregation/Alarm",     label: "Object Count Alarm" },
  { value: "tns1:AudioAnalytics/Audio/DetectedSound",    label: "Audio Alarm" },
  { value: "tns1:VideoAnalytics/FaceDetection/Alarm",    label: "Face Detection" },
  { value: "tns1:VideoSource/ConnectionFailed",          label: "Video Signal Lost" },
  { value: "tns1:ThermalService/TemperatureAlarm",       label: "Temperature Alarm" },
];

// ---------------------------------------------------------------------------
// Events Tab
// ---------------------------------------------------------------------------

const EventsTab = ({ camera, cameraId }) => {
  const { isAdmin } = usePermissions();
  const qc = useQueryClient();
  const [enabled, setEnabled] = useState(!!camera?.onvif_events_enabled);
  const [topics, setTopics] = useState(camera?.onvif_event_topics || []);

  const { data: metadataStream, isLoading: metadataLoading, refetch: refetchMetadata } = useQuery({
    queryKey: ["onvif-metadata-stream", cameraId],
    queryFn: () => getOnvifMetadataStream(cameraId),
    enabled: !!camera?.onvif_host,
    retry: 1,
  });

  useEffect(() => {
    setEnabled(!!camera?.onvif_events_enabled);
    setTopics(camera?.onvif_event_topics || []);
  }, [camera]);

  const saveMutation = useMutation({
    mutationFn: (data) => updateCamera(cameraId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["camera", cameraId] });
      toast.success("ONVIF event settings saved");
    },
    onError: (e) => toast.error(friendlyError(e, "Save failed")),
  });

  const toggleTopic = (topic) => {
    setTopics((prev) =>
      prev.includes(topic) ? prev.filter((t) => t !== topic) : [...prev, topic],
    );
  };

  const handleSave = () => {
    saveMutation.mutate({
      onvif_events_enabled: enabled,
      onvif_event_topics: topics.length > 0 ? topics : null,
    });
  };

  if (!camera?.onvif_host) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Radio className="h-10 w-10 mx-auto mb-3 text-[var(--console-muted)]" />
        <p className="text-sm">No ONVIF host configured for this camera.</p>
        <p className="text-xs text-muted-foreground mt-1">
          Set the ONVIF host in camera settings to enable event pull.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Enable toggle */}
      <div className="flex items-center justify-between p-4 bg-[var(--console-panel)] rounded-lg">
        <div>
          <p className="text-sm font-medium text-white ">
            ONVIF Event Pull
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            Subscribe to real-time camera events via ONVIF PullPoint
          </p>
        </div>
        <Switch
          checked={enabled}
          onCheckedChange={setEnabled}
        />
      </div>

      <div className="p-4 bg-[var(--console-panel)] rounded-lg border border-[var(--console-border)]">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-white">
              Profile M Metadata Transport
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Camera-generated metadata stream discovery for analytics/event payloads
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => refetchMetadata()}>
            <RefreshCw className={cn("h-3.5 w-3.5", metadataLoading && "animate-spin")} />
          </Button>
        </div>
        {metadataLoading ? (
          <div className="flex items-center gap-2 mt-3 text-xs text-muted-foreground">
            <RefreshCw className="h-3.5 w-3.5 animate-spin" /> Checking metadata stream…
          </div>
        ) : metadataStream?.supported ? (
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-2">
              <Badge className="bg-[var(--console-accent)] hover:brightness-110 text-[var(--console-accent-foreground)]">Supported</Badge>
              <Badge variant="outline">Media{metadataStream.media_version}</Badge>
              {metadataStream.profile_token && (
                <Badge variant="outline">{metadataStream.profile_token}</Badge>
              )}
            </div>
            {isAdmin && (
              <p className="text-xs font-mono text-muted-foreground break-all">
                <span className="uppercase tracking-wide text-[10px] mr-1 opacity-70">Diagnostics</span>
                {metadataStream.uri}
              </p>
            )}
          </div>
        ) : (
          <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
            {metadataStream?.reason || "No metadata stream reported by camera."}
          </div>
        )}
      </div>

      {/* Topic filter */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div>
            <p className="text-sm font-medium text-white ">
              Event Topics
            </p>
            <p className="text-xs text-muted-foreground">
              Leave all unchecked to subscribe to all events
            </p>
          </div>
          {topics.length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setTopics([])}>
              Clear all
            </Button>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {ONVIF_TOPICS.map((t) => {
            const checked = topics.includes(t.value);
            return (
              <button
                key={t.value}
                onClick={() => toggleTopic(t.value)}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-left transition-colors border",
                  checked
                    ? "bg-[var(--console-accent)] text-white border-[var(--console-accent)]"
                    : "bg-[var(--console-raised)] text-[var(--console-text)]  border-[var(--console-border)]  hover:border-[var(--console-accent)]",
                )}
              >
                <div
                  className={cn(
                    "h-4 w-4 rounded flex-shrink-0 border-2 transition-colors",
                    checked
                      ? "border-white bg-transparent"
                      : "border-[var(--console-border)] ",
                  )}
                >
                  {checked && (
                    <svg viewBox="0 0 10 10" className="text-white" fill="currentColor">
                      <path d="M1.5 5l2.5 2.5 5-5" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </div>
                <span className="truncate">{t.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={saveMutation.isPending}>
          {saveMutation.isPending ? (
            <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Save className="h-4 w-4 mr-2" />
          )}
          Save Event Settings
        </Button>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Edge Recordings Tab (Profile G)
// ---------------------------------------------------------------------------

const EdgeRecordingsTab = ({ camera, cameraId }) => {
  const { isAdmin } = usePermissions();
  const now = new Date();
  const defaultEnd = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
  const defaultStart = new Date(now.getTime() - 60 * 60 * 1000 - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
  const [startTime, setStartTime] = useState(defaultStart);
  const [endTime, setEndTime] = useState(defaultEnd);
  const [replayByToken, setReplayByToken] = useState({});

  const buildParams = () => ({
    ...(startTime ? { start_time: new Date(startTime).toISOString() } : {}),
    ...(endTime ? { end_time: new Date(endTime).toISOString() } : {}),
  });

  const {
    data,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["onvif-edge-recordings", cameraId],
    queryFn: () => getOnvifEdgeRecordings(cameraId, buildParams()),
    enabled: false,
    retry: 1,
  });

  const replayMutation = useMutation({
    mutationFn: (token) => getOnvifReplayUri(cameraId, token),
    onSuccess: (result) => {
      setReplayByToken((prev) => ({ ...prev, [result.recording_token]: result.uri }));
      toast.success("Replay URI resolved");
    },
    onError: (e) => toast.error(friendlyError(e, "Replay URI not available")),
  });

  if (!camera?.onvif_host) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Database className="h-10 w-10 mx-auto mb-3 text-[var(--console-muted)]" />
        <p className="text-sm">No ONVIF host configured for this camera.</p>
      </div>
    );
  }

  const recordings = data?.recordings || [];

  const copyText = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Copied");
    } catch (_e) {
      toast.error("Copy failed");
    }
  };

  const formatTime = (value) => {
    if (!value) return "-";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return formatDateTime(value);
  };

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-3 items-end">
        <div className="space-y-1.5">
          <Label className="text-sm">Start</Label>
          <input
            type="datetime-local"
            value={startTime}
            onChange={(e) => setStartTime(e.target.value)}
            className="w-full h-9 px-3 rounded-md bg-[var(--console-panel)] border border-[var(--console-border)] text-sm text-white"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-sm">End</Label>
          <input
            type="datetime-local"
            value={endTime}
            onChange={(e) => setEndTime(e.target.value)}
            className="w-full h-9 px-3 rounded-md bg-[var(--console-panel)] border border-[var(--console-border)] text-sm text-white"
          />
        </div>
        <Button onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? (
            <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Search className="h-4 w-4 mr-2" />
          )}
          Search
        </Button>
      </div>

      {isError && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
          <AlertTriangle className="h-4 w-4 text-amber-400" />
          {friendlyError(error, "Could not search camera edge recordings.")}
        </div>
      )}

      {!data && !isError ? (
        <div className="text-sm text-muted-foreground py-8 text-center">
          Search camera-side Profile G storage for recordings in the selected time window.
        </div>
      ) : recordings.length === 0 && !isFetching && !isError ? (
        <div className="text-sm text-muted-foreground py-8 text-center">
          No edge recordings returned by the camera for this window.
        </div>
      ) : (
        <div className="space-y-2">
          {recordings.map((rec, idx) => {
            const token = rec.recording_token || `recording-${idx}`;
            const replayUri = replayByToken[token];
            return (
              <div
                key={`${token}-${rec.track_token || idx}`}
                className="p-3 rounded-lg bg-[var(--console-panel)] border border-[var(--console-border)]"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-white truncate">{token}</p>
                    <p className="text-xs text-muted-foreground">
                      {formatTime(rec.start_time)} - {formatTime(rec.end_time)}
                    </p>
                    {rec.track_token && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Track: {rec.track_token}
                      </p>
                    )}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={replayMutation.isPending}
                    onClick={() => replayMutation.mutate(token)}
                  >
                    <PlayCircle className="h-3.5 w-3.5 mr-1" />
                    Replay URI
                  </Button>
                </div>
                {replayUri && (
                  isAdmin ? (
                    <div className="mt-3 flex items-start gap-2">
                      <p className="flex-1 text-xs font-mono text-muted-foreground break-all">
                        <span className="uppercase tracking-wide text-[10px] mr-1 opacity-70">Diagnostics</span>
                        {replayUri}
                      </p>
                      <Button variant="ghost" size="sm" onClick={() => copyText(replayUri)}>
                        <Copy className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ) : (
                    <p className="mt-3 text-xs text-muted-foreground">
                      Replay link ready.
                    </p>
                  )
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Imaging Tab
// ---------------------------------------------------------------------------

const ImagingTab = ({ camera, cameraId }) => {
  const [settings, setSettings] = useState(null);
  const [dirty, setDirty] = useState(false);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["onvif-imaging", cameraId],
    queryFn: () => getImagingSettings(cameraId),
    enabled: !!camera?.onvif_host,
    retry: 1,
  });

  useEffect(() => {
    if (data) {
      setSettings(data);
      setDirty(false);
    }
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: (payload) => setImagingSettings(cameraId, payload),
    onSuccess: () => {
      setDirty(false);
      toast.success("Imaging settings applied");
      refetch();
    },
    onError: (e) => toast.error(friendlyError(e, "Failed to apply imaging settings")),
  });

  const focusMutation = useMutation({
    mutationFn: (data) => moveFocus(cameraId, data),
    onSuccess: () => toast.success("Focus command sent"),
    onError: (e) => toast.error(friendlyError(e, "Focus command failed")),
  });

  const update = (key, value) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  };

  if (!camera?.onvif_host) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Image className="h-10 w-10 mx-auto mb-3 text-[var(--console-muted)]" />
        <p className="text-sm">No ONVIF host configured for this camera.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
        <span className="ml-2 text-sm text-muted-foreground">Loading imaging settings…</span>
      </div>
    );
  }

  if (isError || !settings) {
    return (
      <div className="text-center py-12">
        <AlertTriangle className="h-10 w-10 mx-auto mb-3 text-amber-400" />
        <p className="text-sm text-muted-foreground max-w-md mx-auto">
          {friendlyError(error, "Could not load imaging settings from camera.")}
        </p>
        <Button variant="outline" size="sm" className="mt-3" onClick={refetch}>
          Retry
        </Button>
      </div>
    );
  }

  const SliderRow = ({ label, field, min = 0, max = 100, step = 1 }) => (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-sm">{label}</Label>
        <span className="text-xs text-muted-foreground font-mono w-8 text-right">
          {settings[field] != null ? Math.round(settings[field]) : "—"}
        </span>
      </div>
      <Slider
        min={min}
        max={max}
        step={step}
        value={[settings[field] ?? 50]}
        onValueChange={([v]) => update(field, v)}
        disabled={settings[field] == null}
      />
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Basic image quality */}
      <div className="space-y-4">
        <p className="text-sm font-semibold text-[var(--console-text)]  border-b border-border  pb-2">
          Image Quality
        </p>
        <SliderRow label="Brightness" field="brightness" min={-100} max={100} />
        <SliderRow label="Contrast" field="contrast" min={-100} max={100} />
        <SliderRow label="Saturation" field="color_saturation" min={0} max={100} />
        <SliderRow label="Sharpness" field="sharpness" min={0} max={100} />
      </div>

      {/* Mode selects */}
      <div className="space-y-4">
        <p className="text-sm font-semibold text-[var(--console-text)]  border-b border-border  pb-2">
          Camera Modes
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="space-y-1.5">
            <Label className="text-sm">IR Cut Filter (Day/Night)</Label>
            <Select
              value={settings.ir_cut_filter_mode || "AUTO"}
              onValueChange={(v) => update("ir_cut_filter_mode", v)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="AUTO">Auto</SelectItem>
                <SelectItem value="ON">Day (IR Cut ON)</SelectItem>
                <SelectItem value="OFF">Night (IR Cut OFF)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label className="text-sm">WDR Mode</Label>
            <Select
              value={settings.wide_dynamic_range_mode || "OFF"}
              onValueChange={(v) => update("wide_dynamic_range_mode", v)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="OFF">Off</SelectItem>
                <SelectItem value="ON">On</SelectItem>
                <SelectItem value="AUTO">Auto</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label className="text-sm">Exposure Mode</Label>
            <Select
              value={settings.exposure_mode || "AUTO"}
              onValueChange={(v) => update("exposure_mode", v)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="AUTO">Auto</SelectItem>
                <SelectItem value="MANUAL">Manual</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* Autofocus */}
      <div className="space-y-3">
        <p className="text-sm font-semibold text-[var(--console-text)]  border-b border-border  pb-2">
          Focus Control
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            variant="outline"
            size="sm"
            onClick={() => focusMutation.mutate({ mode: "AUTO" })}
            disabled={focusMutation.isPending}
          >
            <Focus className="h-4 w-4 mr-1" />
            Auto Focus
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => focusMutation.mutate({ mode: "MOVE", direction: "NEAR", speed: 0.5 })}
            disabled={focusMutation.isPending}
          >
            Focus Near
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => focusMutation.mutate({ mode: "MOVE", direction: "FAR", speed: 0.5 })}
            disabled={focusMutation.isPending}
          >
            Focus Far
          </Button>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2">
        <Button
          onClick={() => saveMutation.mutate(settings)}
          disabled={!dirty || saveMutation.isPending}
        >
          {saveMutation.isPending ? (
            <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Save className="h-4 w-4 mr-2" />
          )}
          Apply Settings
        </Button>
        <Button
          variant="outline"
          onClick={() => { setSettings(data); setDirty(false); }}
          disabled={!dirty}
        >
          <RotateCcw className="h-4 w-4 mr-1" />
          Revert
        </Button>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Digital I/O Tab
// ---------------------------------------------------------------------------

const DigitalIOTab = ({ camera, cameraId }) => {
  const [triggeringRelay, setTriggeringRelay] = useState(null);

  const { data: relays, isLoading: relaysLoading, isError: relaysError, error: relaysErr, refetch: refetchRelays } = useQuery({
    queryKey: ["onvif-relays", cameraId],
    queryFn: () => getRelayOutputs(cameraId),
    enabled: !!camera?.onvif_host,
    retry: 1,
  });

  const { data: inputs, isLoading: inputsLoading, isError: inputsError, error: inputsErr, refetch: refetchInputs } = useQuery({
    queryKey: ["onvif-inputs", cameraId],
    queryFn: () => getDigitalInputs(cameraId),
    enabled: !!camera?.onvif_host,
    retry: 1,
  });

  const triggerMutation = useMutation({
    mutationFn: ({ token, state }) => triggerRelayOutput(cameraId, token, state),
    onSuccess: (_, { token }) => {
      toast.success(`Relay ${token} triggered`);
      setTriggeringRelay(null);
      refetchRelays();
    },
    onError: (e, { token }) => {
      toast.error(friendlyError(e, `Failed to trigger relay ${token}`));
      setTriggeringRelay(null);
    },
  });

  if (!camera?.onvif_host) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Zap className="h-10 w-10 mx-auto mb-3 text-[var(--console-muted)]" />
        <p className="text-sm">No ONVIF host configured for this camera.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Relay Outputs */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-semibold text-[var(--console-text)] ">
            Relay Outputs
          </p>
          <Button variant="ghost" size="sm" onClick={refetchRelays}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>

        {relaysLoading ? (
          <div className="flex items-center gap-2 py-6 text-muted-foreground text-sm">
            <RefreshCw className="h-4 w-4 animate-spin" /> Loading relay outputs…
          </div>
        ) : relaysError ? (
          <p className="text-sm text-muted-foreground py-4">
            <AlertTriangle className="h-4 w-4 inline mr-1 text-amber-400" />
            {friendlyError(relaysErr, "Could not load relay outputs from camera.")}
          </p>
        ) : !relays?.length ? (
          <p className="text-sm text-muted-foreground py-4">No relay outputs reported by camera.</p>
        ) : (
          <div className="space-y-2">
            {(relays || []).map((relay) => (
              <div
                key={relay.token}
                className="flex items-center justify-between p-3 bg-[var(--console-panel)] rounded-lg border border-border "
              >
                <div>
                  <p className="text-sm font-medium text-white ">
                    {relay.token}
                  </p>
                  <p className="text-xs text-muted-foreground capitalize">
                    Mode: {relay.mode || "—"} · Delay: {relay.delay_time || "0"}s
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge
                    variant={relay.idle_state === "open" ? "outline" : "secondary"}
                    className="text-xs"
                  >
                    Idle: {relay.idle_state || "—"}
                  </Badge>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={triggeringRelay === relay.token || triggerMutation.isPending}
                    onClick={() => {
                      setTriggeringRelay(relay.token);
                      const nextState = relay.idle_state === "open" ? "closed" : "open";
                      triggerMutation.mutate({ token: relay.token, state: nextState });
                    }}
                  >
                    {triggeringRelay === relay.token ? (
                      <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Zap className="h-3.5 w-3.5 mr-1" />
                    )}
                    Trigger
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Digital Inputs */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-semibold text-[var(--console-text)] ">
            Digital Inputs
          </p>
          <Button variant="ghost" size="sm" onClick={refetchInputs}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>

        {inputsLoading ? (
          <div className="flex items-center gap-2 py-6 text-muted-foreground text-sm">
            <RefreshCw className="h-4 w-4 animate-spin" /> Loading digital inputs…
          </div>
        ) : inputsError ? (
          <p className="text-sm text-muted-foreground py-4">
            <AlertTriangle className="h-4 w-4 inline mr-1 text-amber-400" />
            {friendlyError(inputsErr, "Could not load digital inputs from camera.")}
          </p>
        ) : !inputs?.length ? (
          <p className="text-sm text-muted-foreground py-4">No digital inputs reported by camera.</p>
        ) : (
          <div className="space-y-2">
            {(inputs || []).map((input) => {
              const isActive = input.state === "active" || input.state === true || input.state === "true";
              return (
                <div
                  key={input.token}
                  className="flex items-center justify-between p-3 bg-[var(--console-panel)] rounded-lg border border-border "
                >
                  <div className="flex items-center gap-3">
                    {isActive ? (
                      <CheckCircle2 className="h-5 w-5 text-[var(--console-accent)] flex-shrink-0" />
                    ) : (
                      <Circle className="h-5 w-5 text-[var(--console-muted)] flex-shrink-0" />
                    )}
                    <div>
                      <p className="text-sm font-medium text-white ">
                        {input.token}
                      </p>
                      <p className="text-xs text-muted-foreground capitalize">
                        Idle state: {input.idle_state || "—"}
                      </p>
                    </div>
                  </div>
                  <Badge
                    variant={isActive ? "default" : "outline"}
                    className={cn("text-xs", isActive && "bg-[var(--console-accent)] hover:brightness-110 text-[var(--console-accent-foreground)]")}
                  >
                    {isActive ? "Active" : "Idle"}
                  </Badge>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// System Tab
// ---------------------------------------------------------------------------

const SystemTab = ({ camera, cameraId }) => {
  const [showRebootConfirm, setShowRebootConfirm] = useState(false);
  const [showFactoryConfirm, setShowFactoryConfirm] = useState(false);

  const { data: deviceInfo, isLoading: infoLoading, isError: infoError, error: infoErr } = useQuery({
    queryKey: ["onvif-device-info", cameraId],
    queryFn: () => getONVIFDeviceInfo(cameraId),
    enabled: !!camera?.onvif_host,
    retry: 1,
  });

  const { data: timeData, isLoading: timeLoading, refetch: refetchTime } = useQuery({
    queryKey: ["onvif-time", cameraId],
    queryFn: () => getONVIFTime(cameraId),
    enabled: !!camera?.onvif_host,
    retry: 1,
  });

  const syncTimeMutation = useMutation({
    mutationFn: () => syncONVIFTime(cameraId),
    onSuccess: () => {
      toast.success("Camera time synchronized to server time");
      refetchTime();
    },
    onError: (e) => toast.error(friendlyError(e, "Time sync failed")),
  });

  const rebootMutation = useMutation({
    mutationFn: () => rebootCamera(cameraId),
    onSuccess: () => {
      toast.success("Camera reboot initiated. Camera will reconnect in 30–60s.");
      setShowRebootConfirm(false);
    },
    onError: (e) => {
      toast.error(friendlyError(e, "Reboot command failed"));
      setShowRebootConfirm(false);
    },
  });

  const factoryMutation = useMutation({
    mutationFn: () => factoryDefaultCamera(cameraId, false),
    onSuccess: () => {
      toast.success("Factory reset initiated. Camera will restart with default settings.");
      setShowFactoryConfirm(false);
    },
    onError: (e) => {
      toast.error(friendlyError(e, "Factory reset failed"));
      setShowFactoryConfirm(false);
    },
  });

  if (!camera?.onvif_host) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Cpu className="h-10 w-10 mx-auto mb-3 text-[var(--console-muted)]" />
        <p className="text-sm">No ONVIF host configured for this camera.</p>
      </div>
    );
  }

  const InfoRow = ({ label, value }) => (
    <div className="flex items-start justify-between py-2 border-b border-[var(--console-border)]  last:border-0">
      <span className="text-xs text-muted-foreground dark:text-muted-foreground w-36 flex-shrink-0">{label}</span>
      <span className="text-xs font-medium text-white  text-right break-all">
        {value || "—"}
      </span>
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Device info */}
      <div>
        <p className="text-sm font-semibold text-[var(--console-text)]  border-b border-border  pb-2 mb-3 flex items-center gap-2">
          <Info className="h-4 w-4" />
          Device Information
        </p>
        {infoLoading ? (
          <div className="flex items-center gap-2 py-4 text-muted-foreground text-sm">
            <RefreshCw className="h-4 w-4 animate-spin" /> Loading device info…
          </div>
        ) : infoError ? (
          <p className="text-sm text-muted-foreground py-2">
            <AlertTriangle className="h-4 w-4 inline mr-1 text-amber-400" />
            {friendlyError(infoErr, "Could not retrieve device information.")}
          </p>
        ) : deviceInfo ? (
          <div className="bg-[var(--console-panel)] rounded-lg p-3">
            <InfoRow label="Manufacturer" value={deviceInfo.manufacturer} />
            <InfoRow label="Model" value={deviceInfo.model} />
            <InfoRow label="Firmware Version" value={deviceInfo.firmware_version} />
            <InfoRow label="Serial Number" value={deviceInfo.serial_number} />
            <InfoRow label="Hardware ID" value={deviceInfo.hardware_id} />
          </div>
        ) : null}
      </div>

      {/* Time */}
      <div>
        <p className="text-sm font-semibold text-[var(--console-text)]  border-b border-border  pb-2 mb-3 flex items-center gap-2">
          <Clock className="h-4 w-4" />
          Camera Time
        </p>
        <div className="flex items-center gap-4 flex-wrap">
          <div className="bg-[var(--console-panel)] rounded-lg px-4 py-2 min-w-[200px]">
            {timeLoading ? (
              <span className="text-sm text-muted-foreground">Loading…</span>
            ) : timeData?.camera_time ? (
              <>
                <p className="text-xs text-muted-foreground">Camera time</p>
                <p className="text-sm font-medium font-mono text-white ">
                  {/* The camera's own reported clock — shown verbatim so the
                      offset comparison stays meaningful; not the NVR display tz. */}
                  {new Date(timeData.camera_time).toLocaleString()}
                </p>
                {timeData.offset_seconds != null && (
                  <p className={cn(
                    "text-xs mt-0.5",
                    Math.abs(timeData.offset_seconds) > 5 ? "text-amber-500" : "text-[var(--console-accent)]",
                  )}>
                    {timeData.offset_seconds > 0 ? "+" : ""}
                    {timeData.offset_seconds}s offset from server
                  </p>
                )}
              </>
            ) : (
              <span className="text-sm text-muted-foreground">Time unavailable</span>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => syncTimeMutation.mutate()}
            disabled={syncTimeMutation.isPending}
          >
            {syncTimeMutation.isPending ? (
              <RefreshCw className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Clock className="h-4 w-4 mr-1" />
            )}
            Sync Time to Server
          </Button>
        </div>
      </div>

      {/* Danger zone */}
      <div>
        <p className="text-sm font-semibold pb-2 mb-3 border-b border-[var(--console-border)]" style={{ color: 'var(--console-rec)' }}>
          Danger Zone
        </p>
        <div className="flex items-center gap-3 flex-wrap">
          <Button
            variant="outline"
            size="sm"
            className="hover:bg-amber-500/10"
            style={{ borderColor: 'var(--console-alarm)', color: 'var(--console-alarm)' }}
            onClick={() => setShowRebootConfirm(true)}
          >
            <Power className="h-4 w-4 mr-1" />
            Reboot Camera
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="hover:bg-red-500/10"
            style={{ borderColor: 'var(--console-rec)', color: 'var(--console-rec)' }}
            onClick={() => setShowFactoryConfirm(true)}
          >
            <RotateCcw className="h-4 w-4 mr-1" />
            Factory Reset
          </Button>
        </div>
      </div>

      {/* Reboot confirmation */}
      <AlertDialog open={showRebootConfirm} onOpenChange={setShowRebootConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reboot Camera</AlertDialogTitle>
            <AlertDialogDescription>
              The camera will reboot and recording will be interrupted for 30–60 seconds.
              Are you sure you want to proceed?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => rebootMutation.mutate()}
              disabled={rebootMutation.isPending}
              className="text-white hover:opacity-90"
              style={{ backgroundColor: 'var(--console-alarm)' }}
            >
              {rebootMutation.isPending ? "Rebooting…" : "Reboot"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Factory reset confirmation */}
      <AlertDialog open={showFactoryConfirm} onOpenChange={setShowFactoryConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Factory Reset Camera</AlertDialogTitle>
            <AlertDialogDescription>
              This will reset ALL camera settings to factory defaults. Network configuration,
              presets, and credentials will be erased. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => factoryMutation.mutate()}
              disabled={factoryMutation.isPending}
              className="bg-destructive hover:bg-destructive/90"
            >
              {factoryMutation.isPending ? "Resetting…" : "Factory Reset"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main ONVIF Settings Panel
// ---------------------------------------------------------------------------

export const ONVIFSettingsPanel = ({ cameraId }) => {
  const { data: camera, isLoading } = useQuery({
    queryKey: ["camera", cameraId],
    queryFn: () => getCamera(cameraId),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="mb-4">
        <h3 className="text-base font-semibold text-white ">
          ONVIF Settings
        </h3>
        <p className="text-sm text-muted-foreground">
          Camera-level ONVIF configuration — events, imaging, digital I/O and system operations
        </p>
      </div>

      <Tabs defaultValue="events">
        <TabsList className="h-auto bg-[var(--console-raised)] p-1">
          <TabsTrigger value="events" className="gap-1.5 text-xs sm:text-sm">
            <Radio className="h-3.5 w-3.5" />
            Events
          </TabsTrigger>
          <TabsTrigger value="imaging" className="gap-1.5 text-xs sm:text-sm">
            <Image className="h-3.5 w-3.5" />
            Imaging
          </TabsTrigger>
          <TabsTrigger value="io" className="gap-1.5 text-xs sm:text-sm">
            <Zap className="h-3.5 w-3.5" />
            Digital I/O
          </TabsTrigger>
          <TabsTrigger value="edge" className="gap-1.5 text-xs sm:text-sm">
            <Database className="h-3.5 w-3.5" />
            Edge
          </TabsTrigger>
          <TabsTrigger value="system" className="gap-1.5 text-xs sm:text-sm">
            <Cpu className="h-3.5 w-3.5" />
            System
          </TabsTrigger>
        </TabsList>

        <div className="mt-4">
          <TabsContent value="events" className="m-0">
            <EventsTab camera={camera} cameraId={cameraId} />
          </TabsContent>
          <TabsContent value="imaging" className="m-0">
            <ImagingTab camera={camera} cameraId={cameraId} />
          </TabsContent>
          <TabsContent value="io" className="m-0">
            <DigitalIOTab camera={camera} cameraId={cameraId} />
          </TabsContent>
          <TabsContent value="edge" className="m-0">
            <EdgeRecordingsTab camera={camera} cameraId={cameraId} />
          </TabsContent>
          <TabsContent value="system" className="m-0">
            <SystemTab camera={camera} cameraId={cameraId} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
};
