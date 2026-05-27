// =============================================================================
// SettingsPage — /cameras/:id/settings
// =============================================================================

import React, { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { SlidersHorizontal, Upload, KeyRound, Loader2, Network, Save, RefreshCw as RefreshCwIcon } from "lucide-react";
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
          <p className="text-xs text-muted-foreground">
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
          <Label className="text-xs text-muted-foreground">Username</Label>
          <Input value={username || "admin"} readOnly className="bg-muted/30" />
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
    <div className="bg-card border border-border rounded-lg p-6 space-y-5">
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
            className="w-full px-3 py-2 text-sm bg-zinc-900 border border-border rounded-md text-zinc-200"
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
            className="w-full px-3 py-2 text-sm bg-zinc-900 border border-border rounded-md text-zinc-200"
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
        className="bg-teal-600 hover:bg-teal-500 text-white"
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
        <SlidersHorizontal className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
        <p className="text-muted-foreground">
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
        <div className="border-t border-border pt-6">
          <PtzTourPanel cameraId={cameraId} ptzCapable={camera.ptz_capable} />
        </div>
      )}

      {/* Admin-only: Firmware + Credentials */}
      {isAdmin && camera?.onvif_host && (
        <div className="border-t border-border pt-6 grid gap-4 md:grid-cols-2">
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

      <div className="border-t border-border pt-6">
        <LinkageRuleBuilder />
      </div>

      {/* Bandwidth Policy — D2 */}
      <div className="border-t border-border pt-6">
        <BandwidthPolicyCard cameraId={cameraId} />
      </div>
    </div>
  );
};

export default SettingsPage;
