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
import { cn } from "../../lib/utils";

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
  const qc = useQueryClient();
  const [enabled, setEnabled] = useState(!!camera?.onvif_events_enabled);
  const [topics, setTopics] = useState(camera?.onvif_event_topics || []);

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
    onError: (e) => toast.error(e.response?.data?.detail || "Save failed"),
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
        <Radio className="h-10 w-10 mx-auto mb-3 text-slate-300" />
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
      <div className="flex items-center justify-between p-4 bg-card/40 dark:bg-primary/60 rounded-lg">
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
                    ? "bg-primary text-white border-slate-900"
                    : "bg-card dark:bg-primary text-zinc-200  border-border  hover:border-slate-400",
                )}
              >
                <div
                  className={cn(
                    "h-4 w-4 rounded flex-shrink-0 border-2 transition-colors",
                    checked
                      ? "border-white bg-card"
                      : "border-border ",
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
// Imaging Tab
// ---------------------------------------------------------------------------

const ImagingTab = ({ camera, cameraId }) => {
  const [settings, setSettings] = useState(null);
  const [dirty, setDirty] = useState(false);

  const { data, isLoading, isError, refetch } = useQuery({
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
    onError: (e) => toast.error(e.response?.data?.detail || "Failed to apply imaging settings"),
  });

  const focusMutation = useMutation({
    mutationFn: (data) => moveFocus(cameraId, data),
    onSuccess: () => toast.success("Focus command sent"),
    onError: (e) => toast.error(e.response?.data?.detail || "Focus command failed"),
  });

  const update = (key, value) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  };

  if (!camera?.onvif_host) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Image className="h-10 w-10 mx-auto mb-3 text-slate-300" />
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
        <p className="text-sm text-muted-foreground">Could not load imaging settings from camera.</p>
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
        <p className="text-sm font-semibold text-zinc-200  border-b border-border  pb-2">
          Image Quality
        </p>
        <SliderRow label="Brightness" field="brightness" min={-100} max={100} />
        <SliderRow label="Contrast" field="contrast" min={-100} max={100} />
        <SliderRow label="Saturation" field="color_saturation" min={0} max={100} />
        <SliderRow label="Sharpness" field="sharpness" min={0} max={100} />
      </div>

      {/* Mode selects */}
      <div className="space-y-4">
        <p className="text-sm font-semibold text-zinc-200  border-b border-border  pb-2">
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
        <p className="text-sm font-semibold text-zinc-200  border-b border-border  pb-2">
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

  const { data: relays, isLoading: relaysLoading, isError: relaysError, refetch: refetchRelays } = useQuery({
    queryKey: ["onvif-relays", cameraId],
    queryFn: () => getRelayOutputs(cameraId),
    enabled: !!camera?.onvif_host,
    retry: 1,
  });

  const { data: inputs, isLoading: inputsLoading, isError: inputsError, refetch: refetchInputs } = useQuery({
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
      toast.error(e.response?.data?.detail || `Failed to trigger relay ${token}`);
      setTriggeringRelay(null);
    },
  });

  if (!camera?.onvif_host) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Zap className="h-10 w-10 mx-auto mb-3 text-slate-300" />
        <p className="text-sm">No ONVIF host configured for this camera.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Relay Outputs */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-semibold text-zinc-200 ">
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
            Could not load relay outputs from camera.
          </p>
        ) : !relays?.length ? (
          <p className="text-sm text-muted-foreground py-4">No relay outputs reported by camera.</p>
        ) : (
          <div className="space-y-2">
            {(relays || []).map((relay) => (
              <div
                key={relay.token}
                className="flex items-center justify-between p-3 bg-card/40 dark:bg-primary/60 rounded-lg border border-border "
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
          <p className="text-sm font-semibold text-zinc-200 ">
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
            Could not load digital inputs from camera.
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
                  className="flex items-center justify-between p-3 bg-card/40 dark:bg-primary/60 rounded-lg border border-border "
                >
                  <div className="flex items-center gap-3">
                    {isActive ? (
                      <CheckCircle2 className="h-5 w-5 text-green-500 flex-shrink-0" />
                    ) : (
                      <Circle className="h-5 w-5 text-slate-300 flex-shrink-0" />
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
                    className={cn("text-xs", isActive && "bg-green-500 hover:bg-green-500")}
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

  const { data: deviceInfo, isLoading: infoLoading, isError: infoError } = useQuery({
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
    onError: (e) => toast.error(e.response?.data?.detail || "Time sync failed"),
  });

  const rebootMutation = useMutation({
    mutationFn: () => rebootCamera(cameraId),
    onSuccess: () => {
      toast.success("Camera reboot initiated. Camera will reconnect in 30–60s.");
      setShowRebootConfirm(false);
    },
    onError: (e) => {
      toast.error(e.response?.data?.detail || "Reboot command failed");
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
      toast.error(e.response?.data?.detail || "Factory reset failed");
      setShowFactoryConfirm(false);
    },
  });

  if (!camera?.onvif_host) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Cpu className="h-10 w-10 mx-auto mb-3 text-slate-300" />
        <p className="text-sm">No ONVIF host configured for this camera.</p>
      </div>
    );
  }

  const InfoRow = ({ label, value }) => (
    <div className="flex items-start justify-between py-2 border-b border-slate-100  last:border-0">
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
        <p className="text-sm font-semibold text-zinc-200  border-b border-border  pb-2 mb-3 flex items-center gap-2">
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
            Could not retrieve device information.
          </p>
        ) : deviceInfo ? (
          <div className="bg-card/40 dark:bg-primary/60 rounded-lg p-3">
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
        <p className="text-sm font-semibold text-zinc-200  border-b border-border  pb-2 mb-3 flex items-center gap-2">
          <Clock className="h-4 w-4" />
          Camera Time
        </p>
        <div className="flex items-center gap-4 flex-wrap">
          <div className="bg-card/40 dark:bg-primary/60 rounded-lg px-4 py-2 min-w-[200px]">
            {timeLoading ? (
              <span className="text-sm text-muted-foreground">Loading…</span>
            ) : timeData?.camera_time ? (
              <>
                <p className="text-xs text-muted-foreground">Camera time</p>
                <p className="text-sm font-medium font-mono text-white ">
                  {new Date(timeData.camera_time).toLocaleString()}
                </p>
                {timeData.offset_seconds != null && (
                  <p className={cn(
                    "text-xs mt-0.5",
                    Math.abs(timeData.offset_seconds) > 5 ? "text-amber-500" : "text-green-500",
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
        <p className="text-sm font-semibold text-red-600 border-b border-red-100 dark:border-red-900 pb-2 mb-3">
          Danger Zone
        </p>
        <div className="flex items-center gap-3 flex-wrap">
          <Button
            variant="outline"
            size="sm"
            className="border-orange-300 text-orange-600 hover:bg-orange-50 hover:border-orange-400"
            onClick={() => setShowRebootConfirm(true)}
          >
            <Power className="h-4 w-4 mr-1" />
            Reboot Camera
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="border-red-300 text-red-600 hover:bg-red-50 hover:border-red-400"
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
              className="bg-orange-600 hover:bg-orange-700"
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
        <TabsList className="h-auto bg-card/60 dark:bg-primary/60 p-1">
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
          <TabsContent value="system" className="m-0">
            <SystemTab camera={camera} cameraId={cameraId} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
};
