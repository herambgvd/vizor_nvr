// =============================================================================
// Camera Form Dialog - Shared Add/Edit Camera Dialog
// =============================================================================
// Reusable dialog for creating and editing cameras.
// Includes FPS control and recording schedule configuration.
// =============================================================================

import React, { useState, useEffect, useCallback } from "react";
import { Plus, Trash2, Clock } from "lucide-react";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Textarea } from "../ui/textarea";
import { Switch } from "../ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import { Checkbox } from "../ui/checkbox";

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const FPS_OPTIONS = [
  { value: "original", label: "Original (no change)" },
  { value: "1", label: "1 FPS" },
  { value: "2", label: "2 FPS" },
  { value: "5", label: "5 FPS" },
  { value: "10", label: "10 FPS" },
  { value: "15", label: "15 FPS" },
  { value: "24", label: "24 FPS" },
  { value: "30", label: "30 FPS" },
];

const RECORDING_MODE_OPTIONS = [
  { value: "continuous", label: "Continuous — record 24/7" },
  { value: "schedule",   label: "Schedule — defined time windows" },
  { value: "motion",     label: "Motion-triggered" },
  { value: "manual",     label: "Manual — start/stop only" },
];

const DEFAULT_FORM = {
  name: "",
  main_stream_url: "",
  location: "",
  description: "",
  is_enabled: true,
  recording_mode: "continuous",
  recording_fps: null,
  recording_schedule: null,
  onvif_host: "",
  onvif_port: 80,
  onvif_username: "",
  onvif_password: "",
  anr_enabled: false,
};

const DEFAULT_PERIOD = { days: [0, 1, 2, 3, 4], start: "08:00", end: "18:00" };

/**
 * CameraFormDialog - Shared camera create/edit dialog
 * @param {boolean} open - Whether dialog is open
 * @param {Function} onOpenChange - Open state change handler
 * @param {Object|null} camera - Camera to edit (null for create)
 * @param {Function} onSubmit - Submit handler (data) => void
 * @param {Function} onDelete - Delete handler (camera) => void (edit mode only)
 * @param {boolean} isPending - Whether mutation is pending
 */
export const CameraFormDialog = ({
  open,
  onOpenChange,
  camera = null,
  onSubmit,
  onDelete,
  isPending = false,
}) => {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [periods, setPeriods] = useState([{ ...DEFAULT_PERIOD }]);

  const isEdit = !!camera?.id;

  // Populate form when camera changes
  useEffect(() => {
    if (camera) {
      setForm({
        name: camera.name || "",
        main_stream_url: camera.main_stream_url || "",
        location: camera.location || "",
        description: camera.description || "",
        is_enabled: camera.is_enabled ?? true,
        recording_mode: camera.recording_mode || "continuous",
        recording_fps: camera.recording_fps || null,
        recording_schedule: camera.recording_schedule || null,
        onvif_host: camera.onvif_host || "",
        onvif_port: camera.onvif_port ?? 80,
        onvif_username: camera.onvif_username || "",
        onvif_password: "",  // never pre-fill password
        anr_enabled: camera.anr_enabled ?? false,
      });
      if (camera.recording_schedule?.enabled) {
        setScheduleEnabled(true);
        setPeriods(
          camera.recording_schedule.periods?.length > 0
            ? camera.recording_schedule.periods
            : [{ ...DEFAULT_PERIOD }],
        );
      } else {
        setScheduleEnabled(false);
        setPeriods([{ ...DEFAULT_PERIOD }]);
      }
    } else {
      setForm(DEFAULT_FORM);
      setScheduleEnabled(false);
      setPeriods([{ ...DEFAULT_PERIOD }]);
    }
  }, [camera, open]);

  const updateField = useCallback((field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  }, []);

  const handlePeriodChange = (index, field, value) => {
    setPeriods((prev) => {
      const updated = [...prev];
      updated[index] = { ...updated[index], [field]: value };
      return updated;
    });
  };

  const togglePeriodDay = (periodIndex, dayIndex) => {
    setPeriods((prev) => {
      const updated = [...prev];
      const days = [...updated[periodIndex].days];
      const idx = days.indexOf(dayIndex);
      if (idx >= 0) {
        days.splice(idx, 1);
      } else {
        days.push(dayIndex);
        days.sort();
      }
      updated[periodIndex] = { ...updated[periodIndex], days };
      return updated;
    });
  };

  const addPeriod = () => {
    setPeriods((prev) => [...prev, { ...DEFAULT_PERIOD }]);
  };

  const removePeriod = (index) => {
    setPeriods((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const data = { ...form };

    // Build recording_schedule from UI state
    if (scheduleEnabled && periods.length > 0) {
      data.recording_schedule = {
        enabled: true,
        periods: periods.filter((p) => p.days.length > 0),
      };
    } else {
      data.recording_schedule = null;
    }

    // Convert fps string to int or null
    data.recording_fps =
      data.recording_fps && data.recording_fps !== "original"
        ? parseInt(data.recording_fps, 10)
        : null;

    // ONVIF: null-ify empty host; on edit, omit password if blank
    data.onvif_host = data.onvif_host?.trim() || null;
    if (!data.onvif_host) {
      data.onvif_port = null;
      data.onvif_username = null;
      data.onvif_password = null;
    } else {
      data.onvif_username = data.onvif_username?.trim() || null;
      if (isEdit && !data.onvif_password) {
        delete data.onvif_password; // don't overwrite stored password
      }
    }

    onSubmit(data);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl max-h-[92vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle style={{ fontFamily: "Manrope, sans-serif" }}>
            {isEdit ? "Edit Camera" : "Add New Camera"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update the camera configuration"
              : "Add a new IP camera to your network"}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit}>
          <div className="space-y-4 py-4">
            {/* Name + Stream URL share a row on wide modal */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="camera-name">Camera Name *</Label>
                <Input
                  id="camera-name"
                  data-testid="camera-name-input"
                  placeholder="Front Door Camera"
                  value={form.name}
                  onChange={(e) => updateField("name", e.target.value)}
                  required
                />
              </div>

              {/* Stream URL — shares row with name on md+ */}
              <div className="space-y-2">
                <Label htmlFor="main-stream-url">Stream URL *</Label>
                <Input
                  id="main-stream-url"
                  data-testid="main-stream-url-input"
                  placeholder="rtsp://192.168.1.100:554/stream1"
                  value={form.main_stream_url}
                  onChange={(e) => updateField("main_stream_url", e.target.value)}
                  required
                />
                <p className="text-xs text-muted-foreground">
                  Example: rtsp://username:password@ip:port/path
                </p>
              </div>
            </div>

            {/* Description */}
            <div className="space-y-2">
              <Label htmlFor="description">Description</Label>
              <Textarea
                id="description"
                data-testid="camera-description-input"
                placeholder="Additional notes about this camera..."
                value={form.description}
                onChange={(e) => updateField("description", e.target.value)}
                rows={2}
              />
            </div>

            {/* Enable Camera */}
            <div className="flex items-center justify-between">
              <div>
                <Label htmlFor="is-enabled">Enable Camera</Label>
                <p className="text-xs text-muted-foreground">
                  Camera will be monitored when enabled
                </p>
              </div>
              <Switch
                id="is-enabled"
                data-testid="camera-enabled-switch"
                checked={form.is_enabled}
                onCheckedChange={(checked) =>
                  updateField("is_enabled", checked)
                }
              />
            </div>

            {/* Recording Mode + FPS on one row on md+ */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="recording-mode">Recording Mode</Label>
                <Select
                  value={form.recording_mode || "continuous"}
                  onValueChange={(val) => updateField("recording_mode", val)}
                >
                  <SelectTrigger id="recording-mode">
                    <SelectValue placeholder="Continuous" />
                  </SelectTrigger>
                  <SelectContent>
                    {RECORDING_MODE_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="recording-fps">Recording FPS</Label>
                <Select
                  value={form.recording_fps?.toString() || "original"}
                  onValueChange={(val) =>
                    updateField(
                      "recording_fps",
                      val === "original" ? null : val,
                    )
                  }
                >
                  <SelectTrigger
                    id="recording-fps"
                    data-testid="recording-fps-select"
                  >
                    <SelectValue placeholder="Original (no change)" />
                  </SelectTrigger>
                  <SelectContent>
                    {FPS_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Lower FPS reduces storage usage. Original keeps the
                  camera's native frame rate.
                </p>
              </div>
            </div>

            {/* Recording Schedule */}
            <div className="space-y-3 border-t border-border pt-4">
              <div className="flex items-center justify-between">
                <div>
                  <Label className="flex items-center gap-2">
                    <Clock className="h-4 w-4" />
                    Recording Schedule
                  </Label>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Automatically start/stop recording on a schedule
                  </p>
                </div>
                <Switch
                  data-testid="schedule-enabled-switch"
                  checked={scheduleEnabled}
                  onCheckedChange={setScheduleEnabled}
                />
              </div>

              {scheduleEnabled && (
                <div className="space-y-3 pl-1">
                  {periods.map((period, idx) => (
                    <div
                      key={idx}
                      className="border border-border rounded-lg p-3 space-y-3"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-[var(--console-text)]">
                          Period {idx + 1}
                        </span>
                        {periods.length > 1 && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 text-muted-foreground hover:text-red-500"
                            onClick={() => removePeriod(idx)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        )}
                      </div>

                      {/* Days */}
                      <div className="flex flex-wrap gap-1.5">
                        {DAY_LABELS.map((label, dayIdx) => (
                          <label
                            key={dayIdx}
                            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium cursor-pointer transition-colors ${
                              period.days.includes(dayIdx)
                                ? "bg-[var(--console-accent)] text-white"
                                : "bg-[var(--console-raised)] text-muted-foreground hover:bg-[var(--console-border)]"
                            }`}
                          >
                            <Checkbox
                              checked={period.days.includes(dayIdx)}
                              onCheckedChange={() =>
                                togglePeriodDay(idx, dayIdx)
                              }
                              className="sr-only"
                            />
                            {label}
                          </label>
                        ))}
                      </div>

                      {/* Time Range */}
                      <div className="flex items-center gap-2">
                        <div className="flex-1">
                          <Label className="text-xs text-muted-foreground">
                            Start
                          </Label>
                          <Input
                            type="time"
                            value={period.start}
                            onChange={(e) =>
                              handlePeriodChange(idx, "start", e.target.value)
                            }
                            className="h-8 text-sm"
                          />
                        </div>
                        <span className="text-muted-foreground mt-4">—</span>
                        <div className="flex-1">
                          <Label className="text-xs text-muted-foreground">End</Label>
                          <Input
                            type="time"
                            value={period.end}
                            onChange={(e) =>
                              handlePeriodChange(idx, "end", e.target.value)
                            }
                            className="h-8 text-sm"
                          />
                        </div>
                      </div>
                    </div>
                  ))}

                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={addPeriod}
                    className="w-full"
                  >
                    <Plus className="h-3.5 w-3.5 mr-1.5" />
                    Add Time Period
                  </Button>
                </div>
              )}
            </div>
          </div>

            {/* ANR Configuration */}
            <div className="flex items-center justify-between border-t border-border pt-4">
              <div>
                <Label htmlFor="anr-enabled">Automatic Network Replenishment (ANR)</Label>
                <p className="text-xs text-muted-foreground">
                  Backfill missing recordings from camera SD card after outages
                </p>
              </div>
              <Switch
                id="anr-enabled"
                data-testid="anr-enabled-switch"
                checked={form.anr_enabled}
                onCheckedChange={(checked) =>
                  updateField("anr_enabled", checked)
                }
              />
            </div>

            {/* ONVIF Configuration */}
            <div className="space-y-3 border-t border-border pt-4">
              <div>
                <Label className="text-sm font-medium text-[var(--console-text)]">
                  ONVIF Configuration
                </Label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Required for PTZ, events, imaging, and device management
                </p>
              </div>

              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2 space-y-1.5">
                  <Label htmlFor="onvif-host" className="text-xs">ONVIF Host / IP</Label>
                  <Input
                    id="onvif-host"
                    placeholder="192.168.1.100"
                    value={form.onvif_host}
                    onChange={(e) => updateField("onvif_host", e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="onvif-port" className="text-xs">Port</Label>
                  <Input
                    id="onvif-port"
                    type="number"
                    min={1}
                    max={65535}
                    placeholder="80"
                    value={form.onvif_port}
                    onChange={(e) =>
                      updateField("onvif_port", parseInt(e.target.value, 10) || 80)
                    }
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1.5">
                  <Label htmlFor="onvif-user" className="text-xs">Username</Label>
                  <Input
                    id="onvif-user"
                    placeholder="admin"
                    value={form.onvif_username}
                    onChange={(e) => updateField("onvif_username", e.target.value)}
                    autoComplete="off"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="onvif-pass" className="text-xs">
                    Password{" "}
                    {isEdit && (
                      <span className="text-muted-foreground font-normal">(leave blank to keep)</span>
                    )}
                  </Label>
                  <Input
                    id="onvif-pass"
                    type="password"
                    placeholder={isEdit ? "••••••••" : "password"}
                    value={form.onvif_password}
                    onChange={(e) => updateField("onvif_password", e.target.value)}
                    autoComplete="new-password"
                  />
                </div>
              </div>
            </div>

          <DialogFooter className="gap-2">
            {isEdit && onDelete && (
              <Button
                type="button"
                variant="destructive"
                onClick={() => onDelete(camera)}
              >
                Delete
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              data-testid="save-camera-btn"
              type="submit"
              className="text-white hover:opacity-90"
              style={{ backgroundColor: 'var(--console-accent)' }}
              disabled={isPending}
            >
              {isPending ? "Saving..." : isEdit ? "Update" : "Add Camera"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default CameraFormDialog;
