// =============================================================================
// Camera Form Dialog - Shared Add/Edit Camera Dialog
// =============================================================================
// Reusable dialog for creating and editing cameras.
// Includes FPS control and recording schedule configuration.
// =============================================================================

import React, { useState, useEffect, useCallback } from "react";
import { Plus, Trash2, Clock, Camera, Radio, ShieldCheck } from "lucide-react";
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
      <DialogContent className="w-[min(960px,calc(100vw-32px))] max-w-none max-h-[88vh] overflow-hidden !p-0 !gap-0 bg-black/95 border-[var(--console-border)] shadow-[0_24px_90px_rgba(0,0,0,0.9),0_0_42px_hsl(var(--ring)/0.10)]">
        <form onSubmit={handleSubmit} className="flex max-h-[88vh] flex-col">
          <DialogHeader className="shrink-0 border-b border-[var(--console-border)] px-5 py-4 pr-12">
            <div className="flex items-center gap-3">
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-[hsl(var(--ring)/0.20)] text-[var(--console-accent)]">
                <Camera className="h-4 w-4" />
              </span>
              <div>
                <DialogTitle className="text-base" style={{ fontFamily: "Manrope, sans-serif" }}>
                  {isEdit ? "Edit Camera" : "Add New Camera"}
                </DialogTitle>
                <DialogDescription className="text-xs">
                  {isEdit
                    ? "Update stream, recording, and ONVIF settings"
                    : "Add RTSP stream details and ONVIF controls in one place"}
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            <div className="grid grid-cols-1 xl:grid-cols-[1.05fr_0.95fr] gap-4">
              <section className="rounded-lg border border-[var(--console-border)] bg-[var(--console-panel)] p-4">
                <div className="mb-4 flex items-center gap-2">
                  <Radio className="h-4 w-4 text-[var(--console-accent)]" />
                  <div>
                    <h3 className="text-sm font-semibold text-[var(--console-text)]">Stream Details</h3>
                    <p className="text-xs text-muted-foreground">Required connection fields</p>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="space-y-1.5">
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
                    <div className="space-y-1.5">
                      <Label htmlFor="main-stream-url">Stream URL *</Label>
                      <Input
                        id="main-stream-url"
                        data-testid="main-stream-url-input"
                        placeholder="rtsp://192.168.1.100:554/stream1"
                        value={form.main_stream_url}
                        onChange={(e) => updateField("main_stream_url", e.target.value)}
                        required
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3 md:items-end">
                    <div className="space-y-1.5">
                      <Label htmlFor="description">Description</Label>
                      <Textarea
                        id="description"
                        data-testid="camera-description-input"
                        placeholder="Optional camera notes..."
                        value={form.description}
                        onChange={(e) => updateField("description", e.target.value)}
                        rows={2}
                        className="min-h-[54px]"
                      />
                    </div>
                    <div className="flex min-w-[190px] items-center justify-between gap-4 rounded-md border border-[var(--console-border)] bg-black/35 px-3 py-2.5">
                      <div>
                        <Label htmlFor="is-enabled">Enable Camera</Label>
                        <p className="text-xs text-muted-foreground">Monitor when saved</p>
                      </div>
                      <Switch
                        id="is-enabled"
                        data-testid="camera-enabled-switch"
                        checked={form.is_enabled}
                        onCheckedChange={(checked) => updateField("is_enabled", checked)}
                      />
                    </div>
                  </div>
                </div>
              </section>

              <section className="rounded-lg border border-[var(--console-border)] bg-[var(--console-panel)] p-4">
                <div className="mb-4 flex items-center gap-2">
                  <Clock className="h-4 w-4 text-[var(--console-accent)]" />
                  <div>
                    <h3 className="text-sm font-semibold text-[var(--console-text)]">Recording</h3>
                    <p className="text-xs text-muted-foreground">Mode, FPS, schedule, and ANR</p>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="space-y-1.5">
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

                    <div className="space-y-1.5">
                      <Label htmlFor="recording-fps">Recording FPS</Label>
                      <Select
                        value={form.recording_fps?.toString() || "original"}
                        onValueChange={(val) =>
                          updateField("recording_fps", val === "original" ? null : val)
                        }
                      >
                        <SelectTrigger id="recording-fps" data-testid="recording-fps-select">
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
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="flex items-center justify-between gap-3 rounded-md border border-[var(--console-border)] bg-black/35 px-3 py-2.5">
                      <div>
                        <Label className="flex items-center gap-2">
                          Recording Schedule
                        </Label>
                        <p className="text-xs text-muted-foreground">Use time windows</p>
                      </div>
                      <Switch
                        data-testid="schedule-enabled-switch"
                        checked={scheduleEnabled}
                        onCheckedChange={setScheduleEnabled}
                      />
                    </div>

                    <div className="flex items-center justify-between gap-3 rounded-md border border-[var(--console-border)] bg-black/35 px-3 py-2.5">
                      <div>
                        <Label htmlFor="anr-enabled">ANR Backfill</Label>
                        <p className="text-xs text-muted-foreground">Recover SD-card gaps</p>
                      </div>
                      <Switch
                        id="anr-enabled"
                        data-testid="anr-enabled-switch"
                        checked={form.anr_enabled}
                        onCheckedChange={(checked) => updateField("anr_enabled", checked)}
                      />
                    </div>
                  </div>

                  {scheduleEnabled && (
                    <div className="space-y-3 rounded-md border border-[var(--console-border)] bg-black/25 p-3">
                      {periods.map((period, idx) => (
                        <div key={idx} className="space-y-3 rounded-md border border-[var(--console-border)] bg-black/30 p-3">
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-medium text-[var(--console-text)]">
                              Period {idx + 1}
                            </span>
                            {periods.length > 1 && (
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-muted-foreground hover:text-red-400"
                                onClick={() => removePeriod(idx)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            )}
                          </div>

                          <div className="flex flex-wrap gap-1.5">
                            {DAY_LABELS.map((label, dayIdx) => (
                              <label
                                key={dayIdx}
                                className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium cursor-pointer transition-colors ${
                                  period.days.includes(dayIdx)
                                    ? "bg-[var(--console-accent)] text-[var(--console-accent-foreground)]"
                                    : "bg-[var(--console-raised)] text-muted-foreground hover:bg-[var(--console-border)]"
                                }`}
                              >
                                <Checkbox
                                  checked={period.days.includes(dayIdx)}
                                  onCheckedChange={() => togglePeriodDay(idx, dayIdx)}
                                  className="sr-only"
                                />
                                {label}
                              </label>
                            ))}
                          </div>

                          <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-2">
                            <div className="space-y-1">
                              <Label className="text-xs text-muted-foreground">Start</Label>
                              <Input
                                type="time"
                                value={period.start}
                                onChange={(e) => handlePeriodChange(idx, "start", e.target.value)}
                                className="h-8 text-sm"
                              />
                            </div>
                            <span className="pb-1.5 text-muted-foreground">to</span>
                            <div className="space-y-1">
                              <Label className="text-xs text-muted-foreground">End</Label>
                              <Input
                                type="time"
                                value={period.end}
                                onChange={(e) => handlePeriodChange(idx, "end", e.target.value)}
                                className="h-8 text-sm"
                              />
                            </div>
                          </div>
                        </div>
                      ))}

                      <Button type="button" variant="outline" size="sm" onClick={addPeriod} className="w-full">
                        <Plus className="h-3.5 w-3.5 mr-1.5" />
                        Add Time Period
                      </Button>
                    </div>
                  )}
                </div>
              </section>
            </div>

            <section className="mt-4 rounded-lg border border-[var(--console-border)] bg-[var(--console-panel)] p-4">
              <div className="mb-4 flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-[var(--console-accent)]" />
                <div>
                  <h3 className="text-sm font-semibold text-[var(--console-text)]">ONVIF Configuration</h3>
                  <p className="text-xs text-muted-foreground">
                    Required for PTZ, events, imaging, and device management
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-[1.3fr_120px_1fr_1fr] gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="onvif-host">Host / IP</Label>
                  <Input
                    id="onvif-host"
                    placeholder="192.168.1.100"
                    value={form.onvif_host}
                    onChange={(e) => updateField("onvif_host", e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="onvif-port">Port</Label>
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
                <div className="space-y-1.5">
                  <Label htmlFor="onvif-user">Username</Label>
                  <Input
                    id="onvif-user"
                    placeholder="admin"
                    value={form.onvif_username}
                    onChange={(e) => updateField("onvif_username", e.target.value)}
                    autoComplete="off"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="onvif-pass">
                    Password{" "}
                    {isEdit && (
                      <span className="text-muted-foreground font-normal">(keep blank)</span>
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
            </section>
          </div>

          <DialogFooter className="shrink-0 gap-2 border-t border-[var(--console-border)] bg-black/95 px-5 py-3">
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
