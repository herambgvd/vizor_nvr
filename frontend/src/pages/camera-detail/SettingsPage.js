// =============================================================================
// SettingsPage — /cameras/:id/settings
// =============================================================================

import React, { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { SlidersHorizontal, Upload, KeyRound, Loader2, Network, Save, RefreshCw as RefreshCwIcon, HardDrive, DownloadCloud, Clock, AlertCircle, CheckCircle2, Search, XCircle, Receipt, Globe } from "lucide-react";
import { toast } from "sonner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getBandwidthPolicy, updateBandwidthPolicy } from "../../api/monitoring";
import { CameraSettingsPanel, LinkageRuleBuilder } from "../../components/nvr";
import PtzTourPanel from "../../components/nvr/PtzTourPanel";
import { usePermissions } from "../../hooks/usePermissions";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { maskStreamUrl } from "../../lib/utils";
import apiClient from "../../api/client";

// ── Firmware Upload Card ─────────────────────────────────────────────────────

const FirmwareCard = ({ cameraId, firmwareVersion }) => {
  const [file, setFile] = useState(null);

  const { mutate: uploadFw, isPending } = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.append("firmware", file);
      return apiClient.post(`/cameras/${cameraId}/firmware/upload`, form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000,
      });
    },
    onSuccess: () => {
      toast.success("Firmware upload started — camera will reboot");
      setFile(null);
    },
    onError: (err) =>
      toast.error(err?.response?.data?.detail || "Firmware upload failed"),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          <Upload className="h-4 w-4" /> Firmware Upgrade
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {firmwareVersion && (
          <p className="text-xs text-[#8a8f98]">
            Current firmware: <span className="font-mono">{firmwareVersion}</span>
          </p>
        )}
        <p className="text-xs text-amber-400">
          Warning: Camera will reboot after firmware upgrade. Recording will be
          interrupted.
        </p>
        <div className="flex items-center gap-2">
          <Input
            type="file"
            accept=".bin,.fw,.img,.tar,.zip"
            disabled={isPending}
            onChange={(e) => setFile(e.target.files[0] || null)}
            className="text-xs"
          />
          <Button
            size="sm"
            disabled={!file || isPending}
            onClick={() => uploadFw()}
          >
            {isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              "Upload"
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};

// ── Credential Rotation Card ─────────────────────────────────────────────────

const CredentialCard = ({ cameraId, username }) => {
  const [newPass, setNewPass] = useState("");
  const [confirmPass, setConfirmPass] = useState("");

  const { mutate: rotate, isPending } = useMutation({
    mutationFn: () =>
      apiClient
        .post(`/cameras/${cameraId}/credentials/rotate`, {
          new_password: newPass,
        })
        .then((r) => r.data),
    onSuccess: () => {
      toast.success("Credentials rotated successfully");
      setNewPass("");
      setConfirmPass("");
    },
    onError: (err) =>
      toast.error(err?.response?.data?.detail || "Credential rotation failed"),
  });

  const handleSubmit = () => {
    if (newPass.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }
    if (newPass !== confirmPass) {
      toast.error("Passwords do not match");
      return;
    }
    rotate();
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          <KeyRound className="h-4 w-4" /> Rotate Credentials
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1">
          <Label className="text-xs text-[#8a8f98]">Username</Label>
          <Input value={username || "admin"} readOnly className="bg-[#141414]/30" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">New Password</Label>
          <Input
            type="password"
            value={newPass}
            onChange={(e) => setNewPass(e.target.value)}
            placeholder="Min 8 characters"
            disabled={isPending}
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Confirm Password</Label>
          <Input
            type="password"
            value={confirmPass}
            onChange={(e) => setConfirmPass(e.target.value)}
            placeholder="Repeat new password"
            disabled={isPending}
          />
        </div>
        <Button
          className="w-full"
          size="sm"
          disabled={!newPass || isPending}
          onClick={handleSubmit}
        >
          {isPending ? (
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
          ) : null}
          Rotate Credentials
        </Button>
      </CardContent>
    </Card>
  );
};

// ── Bandwidth Policy Card (D2) ───────────────────────────────────────────────

const BandwidthPolicyCard = ({ cameraId }) => {
  const qc = useQueryClient();
  const { data: policy, isLoading } = useQuery({
    queryKey: ["bw-policy", cameraId],
    queryFn: () => getBandwidthPolicy(cameraId),
  });

  const [limitKbps, setLimitKbps] = useState(null);
  const [thresholdPct, setThresholdPct] = useState(null);

  const eff_limit = limitKbps !== null ? limitKbps : (policy?.bandwidth_limit_kbps ?? 0);
  const eff_pct = thresholdPct !== null ? thresholdPct : (policy?.bandwidth_alert_threshold_pct ?? 80);

  const mutation = useMutation({
    mutationFn: (data) => updateBandwidthPolicy(cameraId, data),
    onSuccess: () => {
      toast.success("Bandwidth policy saved");
      qc.invalidateQueries(["bw-policy", cameraId]);
    },
    onError: (e) => toast.error(`Save failed: ${e?.response?.data?.detail || e.message}`),
  });

  const handleSave = () => {
    mutation.mutate({
      bandwidth_limit_kbps: Number(eff_limit) || 0,
      bandwidth_alert_threshold_pct: Math.min(100, Math.max(1, Number(eff_pct) || 80)),
    });
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-zinc-400 text-sm py-4">
        <RefreshCwIcon className="h-4 w-4 animate-spin" /> Loading bandwidth policy…
      </div>
    );
  }

  return (
    <div className="bg-[#0a0a0a] border border-[#1f1f1f] rounded-lg p-6 space-y-5">
      <div className="flex items-center gap-2">
        <Network className="h-5 w-5 text-zinc-400" />
        <h2 className="text-base font-semibold text-white">Bandwidth Policy</h2>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <div className="space-y-1.5">
          <label className="block text-xs font-medium text-zinc-400 uppercase tracking-wide">
            Limit (kbps — 0 = unlimited)
          </label>
          <input
            type="number"
            min={0}
            value={eff_limit}
            onChange={(e) => setLimitKbps(Number(e.target.value))}
            className="w-full px-3 py-2 text-sm bg-zinc-900 border border-[#1f1f1f] rounded-md text-zinc-200"
            placeholder="e.g. 4096"
          />
        </div>
        <div className="space-y-1.5">
          <label className="block text-xs font-medium text-zinc-400 uppercase tracking-wide">
            Alert threshold (% of limit)
          </label>
          <input
            type="number"
            min={1}
            max={100}
            value={eff_pct}
            onChange={(e) => setThresholdPct(Number(e.target.value))}
            className="w-full px-3 py-2 text-sm bg-zinc-900 border border-[#1f1f1f] rounded-md text-zinc-200"
            placeholder="80"
          />
        </div>
      </div>
      <p className="text-xs text-zinc-500">
        An alert event fires when the camera exceeds{" "}
        <span className="text-zinc-300">{eff_pct}%</span> of{" "}
        <span className="text-zinc-300">{eff_limit ? `${eff_limit} kbps` : "no limit"}</span>{" "}
        for 3 consecutive samples (≈ 90 s).
      </p>
      <Button
        onClick={handleSave}
        disabled={mutation.isPending}
      >
        {mutation.isPending ? (
          <RefreshCwIcon className="h-4 w-4 mr-2 animate-spin" />
        ) : (
          <Save className="h-4 w-4 mr-2" />
        )}
        Save Policy
      </Button>
    </div>
  );
};

// ── ANR Settings Card ────────────────────────────────────────────────────────

const ANR_STATUS_ICONS = {
  idle: Clock,
  pending: Clock,
  searching: Search,
  downloading: Loader2,
  completed: CheckCircle2,
  failed: XCircle,
};

const ANR_STATUS_COLORS = {
  idle: "text-zinc-400",
  pending: "text-amber-400",
  searching: "text-blue-400",
  downloading: "text-blue-400",
  completed: "text-teal-400",
  failed: "text-rose-400",
};

const AnrSettingsCard = ({ cameraId, camera }) => {
  const qc = useQueryClient();
  const [maxGapHours, setMaxGapHours] = useState(camera?.anr_max_gap_hours ?? 24);

  const { mutate: updateAnr, isPending: saving } = useMutation({
    mutationFn: (data) =>
      apiClient.patch(`/cameras/${cameraId}`, data).then((r) => r.data),
    onSuccess: () => {
      toast.success("ANR settings saved");
      qc.invalidateQueries(["camera", cameraId]);
    },
    onError: (err) =>
      toast.error(err?.response?.data?.detail || "Failed to save ANR settings"),
  });

  const { mutate: triggerAnr, isPending: triggering } = useMutation({
    mutationFn: () =>
      apiClient.post(`/cameras/${cameraId}/anr/trigger`, {}).then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.message || "ANR backfill triggered");
      qc.invalidateQueries(["anr-status", cameraId]);
      qc.invalidateQueries(["anr-jobs", cameraId]);
    },
    onError: (err) =>
      toast.error(err?.response?.data?.detail || "Failed to trigger ANR"),
  });

  const { data: anrStatus, isLoading: statusLoading } = useQuery({
    queryKey: ["anr-status", cameraId],
    queryFn: () => apiClient.get(`/cameras/${cameraId}/anr/status`).then((r) => r.data),
    enabled: !!cameraId,
    refetchInterval: 5000,
  });

  const { data: anrJobs, isLoading: jobsLoading } = useQuery({
    queryKey: ["anr-jobs", cameraId],
    queryFn: () => apiClient.get(`/cameras/${cameraId}/anr/jobs?limit=5`).then((r) => r.data),
    enabled: !!cameraId,
    refetchInterval: 10000,
  });

  const enabled = camera?.anr_enabled ?? false;
  const status = anrStatus?.anr_status || "idle";
  const StatusIcon = ANR_STATUS_ICONS[status] || Clock;
  const statusColor = ANR_STATUS_COLORS[status] || "text-zinc-400";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          <DownloadCloud className="h-4 w-4" /> Automatic Network Replenishment (ANR)
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Enable Toggle */}
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label className="text-sm font-medium">Enable ANR</Label>
            <p className="text-xs text-[#8a8f98]">
              Automatically backfill recording gaps from camera local storage after network outages
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            disabled={saving}
            onClick={() => updateAnr({ anr_enabled: !enabled })}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
              enabled ? "bg-teal-600" : "bg-zinc-600"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
                enabled ? "translate-x-4.5" : "translate-x-0.5"
              }`}
            />
          </button>
        </div>

        {enabled && (
          <>
            {/* Max Gap Hours */}
            <div className="space-y-1.5">
              <Label className="text-xs text-[#8a8f98]">Maximum gap to backfill (hours)</Label>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min={1}
                  max={168}
                  value={maxGapHours}
                  onChange={(e) => setMaxGapHours(Number(e.target.value))}
                  className="w-24"
                />
                <Button
                  size="sm"
                  disabled={saving || maxGapHours === (camera?.anr_max_gap_hours ?? 24)}
                  onClick={() => updateAnr({ anr_max_gap_hours: maxGapHours })}
                >
                  {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save"}
                </Button>
              </div>
              <p className="text-xs text-zinc-500">
                Gaps larger than this will be skipped to avoid excessive download time
              </p>
            </div>

            {/* Status + Trigger */}
            <div className="bg-[#141414] border border-[#1f1f1f] rounded-lg p-3 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <StatusIcon className={`h-4 w-4 ${statusColor} ${status === "downloading" ? "animate-spin" : ""}`} />
                  <span className="text-sm font-medium capitalize">{status.replace(/_/g, " ")}</span>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={triggering || ["pending", "searching", "downloading"].includes(status)}
                  onClick={() => triggerAnr()}
                >
                  {triggering ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <DownloadCloud className="h-3.5 w-3.5 mr-1" />}
                  Backfill Now
                </Button>
              </div>

              {anrStatus?.anr_last_run_at && (
                <p className="text-xs text-[#8a8f98]">
                  Last run: {new Date(anrStatus.anr_last_run_at).toLocaleString()}
                </p>
              )}

              {anrStatus?.job && (
                <div className="text-xs space-y-1 border-t border-[#1f1f1f] pt-2">
                  <p className="text-[#8a8f98]">Active job</p>
                  <div className="grid grid-cols-3 gap-2">
                    <div className="text-zinc-400">Found: <span className="text-zinc-200">{anrStatus.job.segments_found}</span></div>
                    <div className="text-zinc-400">Downloaded: <span className="text-teal-400">{anrStatus.job.segments_downloaded}</span></div>
                    <div className="text-zinc-400">Failed: <span className="text-rose-400">{anrStatus.job.segments_failed}</span></div>
                  </div>
                  {anrStatus.job.error_message && (
                    <p className="text-rose-400 truncate">{anrStatus.job.error_message}</p>
                  )}
                </div>
              )}
            </div>

            {/* Recent Jobs */}
            {anrJobs && anrJobs.length > 0 && (
              <div className="space-y-2">
                <Label className="text-xs text-[#8a8f98]">Recent backfill jobs</Label>
                <div className="space-y-1.5 max-h-48 overflow-y-auto">
                  {anrJobs.map((job) => (
                    <div
                      key={job.id}
                      className="flex items-center justify-between text-xs px-2 py-1.5 rounded bg-[#141414] border border-[#1f1f1f]"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        {(ANR_STATUS_ICONS[job.status] || Clock) && (
                          <span className={ANR_STATUS_COLORS[job.status] || "text-zinc-400"}>
                            {React.createElement(ANR_STATUS_ICONS[job.status] || Clock, { className: "h-3 w-3" })}
                          </span>
                        )}
                        <span className="capitalize truncate">{job.status}</span>
                      </div>
                      <div className="flex items-center gap-3 text-zinc-500 shrink-0">
                        <span>{job.segments_downloaded} downloaded</span>
                        <span>{new Date(job.created_at).toLocaleDateString()}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
};

// ── Sub-stream Recording Toggle (N5) ────────────────────────────────────────

const SubStreamRecordingCard = ({ cameraId, camera }) => {
  const qc = useQueryClient();
  const enabled = camera?.record_substream ?? false;
  const hasSubStream = !!camera?.sub_stream_url;

  const { mutate: toggle, isPending } = useMutation({
    mutationFn: (val) =>
      apiClient
        .patch(`/cameras/${cameraId}`, { record_substream: val })
        .then((r) => r.data),
    onSuccess: () => {
      toast.success("Recording stream preference saved");
      qc.invalidateQueries(["camera", cameraId]);
    },
    onError: (err) =>
      toast.error(err?.response?.data?.detail || "Failed to save preference"),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          <HardDrive className="h-4 w-4" /> Storage Optimization
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {!hasSubStream && (
          <p className="text-xs text-amber-400">
            No sub-stream URL configured. Add a sub-stream URL in the camera
            settings to enable this option.
          </p>
        )}
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label className="text-sm font-medium">
              Record from sub-stream
            </Label>
            <p className="text-xs text-[#8a8f98]">
              Lower quality (~480p) but ~80% less storage write rate. Best for
              non-evidence cameras.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            disabled={!hasSubStream || isPending}
            onClick={() => toggle(!enabled)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
              enabled ? "bg-teal-600" : "bg-zinc-600"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
                enabled ? "translate-x-4.5" : "translate-x-0.5"
              }`}
            />
          </button>
        </div>
        {enabled && hasSubStream && (
          <p className="text-xs text-teal-400">
            Active — FFmpeg will record from sub-stream:{" "}
            <span className="font-mono break-all">{maskStreamUrl(camera.sub_stream_url)}</span>
          </p>
        )}
      </CardContent>
    </Card>
  );
};

// ── POS / ATM Overlay Card ───────────────────────────────────────────────────

const PosOverlayCard = ({ cameraId, camera }) => {
  const qc = useQueryClient();
  const config = camera?.pos_overlay_config || {};
  const enabled = config.enabled ?? false;

  const { mutate: update, isPending } = useMutation({
    mutationFn: (data) => apiClient.patch(`/cameras/${cameraId}`, { pos_overlay_config: data }).then((r) => r.data),
    onSuccess: () => {
      toast.success("POS overlay settings saved");
      qc.invalidateQueries(["camera", cameraId]);
    },
    onError: (err) => toast.error(err?.response?.data?.detail || "Failed to save"),
  });

  const [text, setText] = React.useState("TEST TRANSACTION: $123.45");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          <Receipt className="h-4 w-4" /> POS / ATM Text Overlay
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label className="text-sm font-medium">Enable Overlay</Label>
            <p className="text-xs text-[#8a8f98]">Burn POS/ATM transaction text onto recordings</p>
          </div>
          <button
            type="button" role="switch" aria-checked={enabled}
            disabled={isPending}
            onClick={() => update({ ...config, enabled: !enabled })}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${enabled ? "bg-teal-600" : "bg-zinc-600"}`}
          >
            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${enabled ? "translate-x-4.5" : "translate-x-0.5"}`} />
          </button>
        </div>
        {enabled && (
          <>
            <div className="space-y-1.5">
              <Label className="text-xs text-[#8a8f98]">Text Style (FFmpeg drawtext opts)</Label>
              <Input
                value={config.text_style || "fontsize=24:fontcolor=white@0.9:box=1:boxcolor=black@0.5"}
                onChange={(e) => update({ ...config, text_style: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-[#8a8f98]">Position (x=y=...)</Label>
              <Input
                value={config.position || "x=10:y=10"}
                onChange={(e) => update({ ...config, position: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-[#8a8f98]">Test Text</Label>
              <div className="flex gap-2">
                <Input value={text} onChange={(e) => setText(e.target.value)} />
                <Button size="sm" onClick={() => apiClient.post(`/pos-overlay/${cameraId}`, { text }).then(() => toast.success("Sent")).catch(() => toast.error("Failed"))}>
                  Send
                </Button>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
};

// ── Fisheye Dewarp Card ──────────────────────────────────────────────────────

const DewarpCard = ({ cameraId, camera }) => {
  const qc = useQueryClient();
  const config = camera?.dewarp_config || {};
  const enabled = config.enabled ?? false;

  const { mutate: update, isPending } = useMutation({
    mutationFn: (data) => apiClient.patch(`/cameras/${cameraId}`, { dewarp_config: data }).then((r) => r.data),
    onSuccess: () => {
      toast.success("Dewarp settings saved");
      qc.invalidateQueries(["camera", cameraId]);
    },
    onError: (err) => toast.error(err?.response?.data?.detail || "Failed to save"),
  });

  const modes = [
    { value: "ceiling", label: "Ceiling mount (looking down)" },
    { value: "wall", label: "Wall mount" },
    { value: "desktop", label: "Desktop / flat mount" },
  ];
  const views = [
    { value: "panoramic", label: "Panoramic (180°)" },
    { value: "quad", label: "Quad view (4x split)" },
    { value: "single", label: "Single PTZ-like view" },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          <Globe className="h-4 w-4" /> Fisheye Dewarp (360° Camera)
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label className="text-sm font-medium">Enable Dewarp</Label>
            <p className="text-xs text-[#8a8f98]">Convert fisheye/360° stream to rectilinear view</p>
          </div>
          <button
            type="button" role="switch" aria-checked={enabled}
            disabled={isPending}
            onClick={() => update({ ...config, enabled: !enabled })}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${enabled ? "bg-teal-600" : "bg-zinc-600"}`}
          >
            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${enabled ? "translate-x-4.5" : "translate-x-0.5"}`} />
          </button>
        </div>
        {enabled && (
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label className="text-xs text-[#8a8f98]">Mount mode</Label>
              <select
                className="w-full h-9 px-2 text-sm bg-zinc-900 border border-[#1f1f1f] rounded-md"
                value={config.mount_mode || "ceiling"}
                onChange={(e) => update({ ...config, mount_mode: e.target.value })}
              >
                {modes.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-[#8a8f98]">View mode</Label>
              <select
                className="w-full h-9 px-2 text-sm bg-zinc-900 border border-[#1f1f1f] rounded-md"
                value={config.view_mode || "panoramic"}
                onChange={(e) => update({ ...config, view_mode: e.target.value })}
              >
                {views.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-[#8a8f98]">FOV X (°)</Label>
              <Input type="number" value={config.fov_x || 90} onChange={(e) => update({ ...config, fov_x: Number(e.target.value) })} />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-[#8a8f98]">FOV Y (°)</Label>
              <Input type="number" value={config.fov_y || 60} onChange={(e) => update({ ...config, fov_y: Number(e.target.value) })} />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

// ── Main Settings Page ───────────────────────────────────────────────────────

const SettingsPage = () => {
  const { camera, cameraId } = useOutletContext();
  const { canManage, isAdmin } = usePermissions();

  const GO2RTC_URL =
    process.env.REACT_APP_GO2RTC_URL || "/go2rtc";
  const snapshotUrl = `${GO2RTC_URL}/api/frame.jpeg?src=${encodeURIComponent(cameraId)}`;

  if (!canManage) {
    return (
      <div className="p-6 text-center">
        <SlidersHorizontal className="h-10 w-10 text-[#8a8f98] mx-auto mb-3" />
        <p className="text-[#8a8f98]">
          You don't have permission to configure cameras.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 space-y-8 max-w-4xl">
      <CameraSettingsPanel cameraId={cameraId} snapshotUrl={snapshotUrl} />

      {/* PTZ Tour — visible only if camera has PTZ */}
      {camera?.ptz_capable && (
        <div className="border-t border-[#1f1f1f] pt-6">
          <PtzTourPanel cameraId={cameraId} ptzCapable={camera.ptz_capable} />
        </div>
      )}

      {/* Admin-only: Firmware + Credentials */}
      {isAdmin && camera?.onvif_host && (
        <div className="border-t border-[#1f1f1f] pt-6 grid gap-4 md:grid-cols-2">
          <FirmwareCard
            cameraId={cameraId}
            firmwareVersion={camera?.firmware}
          />
          <CredentialCard
            cameraId={cameraId}
            username={camera?.onvif_username_display || "admin"}
          />
        </div>
      )}

      <div className="border-t border-[#1f1f1f] pt-6">
        <LinkageRuleBuilder />
      </div>

      {/* ANR Settings */}
      <div className="border-t border-[#1f1f1f] pt-6">
        <AnrSettingsCard cameraId={cameraId} camera={camera} />
      </div>

      {/* Storage Optimization — N5 sub-stream recording */}
      {camera?.sub_stream_url && (
        <div className="border-t border-[#1f1f1f] pt-6">
          <SubStreamRecordingCard cameraId={cameraId} camera={camera} />
        </div>
      )}

      {/* POS Overlay */}
      <div className="border-t border-[#1f1f1f] pt-6">
        <PosOverlayCard cameraId={cameraId} camera={camera} />
      </div>

      {/* Fisheye Dewarp */}
      <div className="border-t border-[#1f1f1f] pt-6">
        <DewarpCard cameraId={cameraId} camera={camera} />
      </div>

      {/* Bandwidth Policy — D2 */}
      <div className="border-t border-[#1f1f1f] pt-6">
        <BandwidthPolicyCard cameraId={cameraId} />
      </div>
    </div>
  );
};

export default SettingsPage;
