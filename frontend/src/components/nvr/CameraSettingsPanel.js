// =============================================================================
// CameraSettingsPanel — Advanced camera settings (motion, privacy, schedule)
// =============================================================================

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Settings2, Activity, EyeOff, Clock, Video, Save } from "lucide-react";
import { getCamera, updateCamera } from "../../api/cameras";
import { MotionZoneEditor } from "./MotionZoneEditor";
import { PrivacyMaskEditor } from "./PrivacyMaskEditor";
import { RecordingScheduleGrid } from "./RecordingScheduleGrid";
import { toast } from "sonner";

const TABS = [
  { key: "recording", label: "Recording", icon: Video },
  { key: "motion", label: "Motion Detection", icon: Activity },
  { key: "privacy", label: "Privacy Masks", icon: EyeOff },
  { key: "schedule", label: "Recording Schedule", icon: Clock },
];

const RECORDING_MODES = [
  {
    value: "continuous",
    label: "Continuous",
    desc: "Record 24/7 regardless of activity",
  },
  {
    value: "schedule",
    label: "Schedule",
    desc: "Record only during defined time windows",
  },
  {
    value: "motion",
    label: "Motion-Triggered",
    desc: "Record when motion is detected",
  },
  {
    value: "manual",
    label: "Manual",
    desc: "Record only when manually started",
  },
];

const RecordingModeTab = ({ camera, cameraId }) => {
  const qc = useQueryClient();
  const [mode, setMode] = useState(camera?.recording_mode || "continuous");

  const saveMutation = useMutation({
    mutationFn: (m) => updateCamera(cameraId, { recording_mode: m }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["camera", cameraId] });
      toast.success("Recording mode saved");
    },
    onError: () => toast.error("Failed to save recording mode"),
  });

  return (
    <div className="space-y-4 max-w-lg">
      <p className="text-sm text-muted-foreground">
        Select how this camera triggers recordings.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {RECORDING_MODES.map((m) => (
          <button
            key={m.value}
            type="button"
            onClick={() => setMode(m.value)}
            className={`flex flex-col text-left px-4 py-3 rounded-lg border-2 transition-all ${
              mode === m.value
                ? "border-slate-900 bg-zinc-950/40 dark:bg-zinc-900/60"
                : "border-white/10  hover:border-slate-400"
            }`}
          >
            <span className="text-sm font-medium text-white ">
              {m.label}
            </span>
            <span className="text-xs text-zinc-500 mt-0.5">{m.desc}</span>
          </button>
        ))}
      </div>
      <button
        onClick={() => saveMutation.mutate(mode)}
        disabled={saveMutation.isPending || mode === camera?.recording_mode}
        className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-zinc-900 text-white rounded-md disabled:opacity-50 hover:bg-zinc-900/60 transition-colors"
      >
        <Save className="h-4 w-4" />
        {saveMutation.isPending ? "Saving…" : "Save Recording Mode"}
      </button>
    </div>
  );
};

/**
 * CameraSettingsPanel — Tabbed panel for per-camera advanced settings.
 *
 * Props:
 *   - cameraId: string (required)
 *   - snapshotUrl?: string (optional camera snapshot for overlays)
 */
export const CameraSettingsPanel = ({ cameraId, snapshotUrl }) => {
  const [tab, setTab] = useState("recording");
  const qc = useQueryClient();

  const { data: camera } = useQuery({
    queryKey: ["camera", cameraId],
    queryFn: () => getCamera(cameraId),
    enabled: !!cameraId,
  });

  const scheduleMutation = useMutation({
    mutationFn: (schedule) =>
      updateCamera(cameraId, {
        recording_schedule: { enabled: true, grid: schedule },
      }),
    onSuccess: () => {
      toast.success("Recording schedule saved");
      qc.invalidateQueries({ queryKey: ["camera", cameraId] });
    },
    onError: () => toast.error("Failed to save schedule"),
  });

  const GO2RTC_URL = process.env.REACT_APP_GO2RTC_URL || "http://localhost:1984";
  const snap = snapshotUrl || `${GO2RTC_URL}/api/frame.jpeg?src=${encodeURIComponent(cameraId)}`;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <Settings2 className="h-5 w-5" />
        <h2 className="font-semibold text-lg">
          {camera?.name || "Camera"} — Advanced Settings
        </h2>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 transition-colors ${
              tab === key
                ? "border-primary text-primary font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="pt-2">
        {tab === "recording" && (
          <RecordingModeTab camera={camera} cameraId={cameraId} />
        )}
        {tab === "motion" && (
          <MotionZoneEditor cameraId={cameraId} snapshotUrl={snap} />
        )}
        {tab === "privacy" && (
          <PrivacyMaskEditor cameraId={cameraId} snapshotUrl={snap} />
        )}
        {tab === "schedule" && (
          <RecordingScheduleGrid
            schedule={camera?.recording_schedule?.grid || null}
            onSave={(sched) => scheduleMutation.mutate(sched)}
            saving={scheduleMutation.isPending}
          />
        )}
      </div>
    </div>
  );
};
