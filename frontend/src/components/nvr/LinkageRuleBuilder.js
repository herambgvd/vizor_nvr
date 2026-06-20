// =============================================================================
// LinkageRuleBuilder — Visual event linkage rule editor (trigger → actions)
// =============================================================================

import React, { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Link2,
  Plus,
  Trash2,
  Save,
  Power,
  PowerOff,
  Pencil,
  ChevronDown,
} from "lucide-react";
import {
  getLinkageRules,
  createLinkageRule,
  updateLinkageRule,
  deleteLinkageRule,
} from "../../api/events";
import { getAllCameras } from "../../api/cameras";
import { eventTypeLabel } from "../../lib/eventLabels";
import { friendlyError } from "../../lib/utils";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import { Switch } from "../ui/switch";
import { toast } from "sonner";

const TRIGGER_TYPES = [
  "motion_detected",
  "video_loss",
  "camera_tamper",
  "camera_offline",
  "camera_online",
  "camera_credentials_invalid",
  "recording_error",
  "storage_low",
  "storage_critical",
  "disk_full",
  "disk_warning",
  "bandwidth_alert",
  "system_error",
  "line_crossing",
  "zone_intrusion",
  "face_recognized",
  "face_unknown",
  "ppe_violation",
  "crowd",
].map((value) => ({ value, label: eventTypeLabel(value) }));

const ACTION_TYPES = [
  { value: "start_recording", label: "Start Recording" },
  { value: "send_email", label: "Send Email" },
  { value: "send_webhook", label: "Send Webhook" },
  { value: "notify_channel", label: "Notify Channel" },
  { value: "trigger_alarm_output", label: "Trigger Alarm Output" },
];

const emptyRule = {
  name: "",
  description: "",
  trigger_type: "motion_detected",
  trigger_config: {},
  actions: [{ action: "start_recording", config: {} }],
  camera_ids: [],
  enabled: true,
  cooldown_seconds: 30,
};

export const LinkageRuleBuilder = () => {
  const qc = useQueryClient();

  const [editing, setEditing] = useState(null); // null = list, object = form
  const [form, setForm] = useState({ ...emptyRule });

  // --- Queries ---
  const { data: rules = [] } = useQuery({
    queryKey: ["linkage-rules"],
    queryFn: getLinkageRules,
  });

  const { data: cameras = [] } = useQuery({
    queryKey: ["cameras"],
    queryFn: getAllCameras,
  });

  // --- Mutations ---
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["linkage-rules"] });

  const createMutation = useMutation({
    mutationFn: createLinkageRule,
    onSuccess: () => {
      toast.success("Rule created");
      invalidate();
      setEditing(null);
    },
    onError: (err) => toast.error(friendlyError(err, "Couldn't create the rule")),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => updateLinkageRule(id, data),
    onSuccess: () => {
      toast.success("Rule updated");
      invalidate();
      setEditing(null);
    },
    onError: (err) => toast.error(friendlyError(err, "Couldn't update the rule")),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteLinkageRule,
    onSuccess: () => {
      toast.success("Rule deleted");
      invalidate();
    },
    onError: (err) => toast.error(friendlyError(err, "Couldn't delete the rule")),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }) => updateLinkageRule(id, { enabled }),
    onSuccess: invalidate,
    onError: (err) => toast.error(friendlyError(err, "Couldn't update the rule")),
  });

  // --- Helpers ---
  const openCreate = () => {
    setForm({ ...emptyRule });
    setEditing("new");
  };

  const openEdit = (rule) => {
    setForm({
      name: rule.name,
      description: rule.description || "",
      trigger_type: rule.trigger_type,
      trigger_config: rule.trigger_config || {},
      actions: rule.actions?.length
        ? rule.actions
        : [{ action: "start_recording", config: {} }],
      camera_ids: rule.camera_ids || [],
      enabled: rule.enabled,
      cooldown_seconds: rule.cooldown_seconds,
    });
    setEditing(rule.id);
  };

  const handleSubmit = () => {
    if (!form.name.trim()) {
      toast.error("Rule name required");
      return;
    }
    const payload = {
      ...form,
      camera_ids: form.camera_ids.length ? form.camera_ids : null,
    };
    if (editing === "new") createMutation.mutate(payload);
    else updateMutation.mutate({ id: editing, data: payload });
  };

  // --- Action management ---
  const addAction = () =>
    setForm((f) => ({
      ...f,
      actions: [...f.actions, { action: "start_recording", config: {} }],
    }));

  const removeAction = (idx) =>
    setForm((f) => ({ ...f, actions: f.actions.filter((_, i) => i !== idx) }));

  const updateAction = (idx, key, value) =>
    setForm((f) => ({
      ...f,
      actions: f.actions.map((a, i) =>
        i === idx ? { ...a, [key]: value } : a,
      ),
    }));

  const updateActionConfig = (idx, cfgKey, cfgVal) =>
    setForm((f) => ({
      ...f,
      actions: f.actions.map((a, i) =>
        i === idx ? { ...a, config: { ...a.config, [cfgKey]: cfgVal } } : a,
      ),
    }));

  // Camera toggle for selection
  const toggleCamera = (camId) =>
    setForm((f) => ({
      ...f,
      camera_ids: f.camera_ids.includes(camId)
        ? f.camera_ids.filter((c) => c !== camId)
        : [...f.camera_ids, camId],
    }));

  // ========== RULE FORM ==========
  if (editing !== null) {
    return (
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold">
            {editing === "new" ? "Create Rule" : "Edit Rule"}
          </h3>
          <Button variant="ghost" size="sm" onClick={() => setEditing(null)}>
            Cancel
          </Button>
        </div>

        {/* Name & description */}
        <div className="grid gap-3">
          <div>
            <Label>Name</Label>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Motion starts recording"
            />
          </div>
          <div>
            <Label>Description</Label>
            <Input
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
              placeholder="Optional description"
            />
          </div>
        </div>

        {/* Trigger */}
        <div>
          <Label>Trigger Event</Label>
          <Select
            value={form.trigger_type}
            onValueChange={(v) => setForm({ ...form, trigger_type: v })}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TRIGGER_TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Camera scope */}
        <div>
          <Label>Apply to Cameras</Label>
          <p className="text-xs text-muted-foreground mb-2">
            Leave empty for all cameras
          </p>
          <div className="flex flex-wrap gap-2">
            {cameras.map((cam) => (
              <button
                key={cam.id}
                type="button"
                onClick={() => toggleCamera(cam.id)}
                className={`px-2 py-1 text-xs rounded border ${
                  form.camera_ids.includes(cam.id)
                    ? "bg-primary text-primary-foreground border-primary"
                    : "border-border"
                }`}
              >
                {cam.name}
              </button>
            ))}
          </div>
        </div>

        {/* Actions */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <Label>Actions</Label>
            <Button variant="outline" size="sm" onClick={addAction}>
              <Plus className="h-3 w-3 mr-1" /> Add
            </Button>
          </div>
          <div className="space-y-3">
            {form.actions.map((act, idx) => (
              <div key={idx} className="border rounded p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <Select
                    value={act.action}
                    onValueChange={(v) => updateAction(idx, "action", v)}
                  >
                    <SelectTrigger className="flex-1">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ACTION_TYPES.map((a) => (
                        <SelectItem key={a.value} value={a.value}>
                          {a.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {form.actions.length > 1 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => removeAction(idx)}
                      className="text-red-500 h-8 w-8 p-0"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>

                {/* Action-specific config */}
                {act.action === "start_recording" && (
                  <Input
                    type="number"
                    min={5}
                    max={600}
                    value={act.config?.duration || 60}
                    onChange={(e) =>
                      updateActionConfig(
                        idx,
                        "duration",
                        parseInt(e.target.value) || 60,
                      )
                    }
                    placeholder="Duration (seconds)"
                    className="h-8 text-sm"
                  />
                )}
                {act.action === "send_email" && (
                  <Input
                    value={act.config?.recipients || ""}
                    onChange={(e) =>
                      updateActionConfig(idx, "recipients", e.target.value)
                    }
                    placeholder="Comma-separated emails"
                    className="h-8 text-sm"
                  />
                )}
                {act.action === "send_webhook" && (
                  <Input
                    value={act.config?.url || ""}
                    onChange={(e) =>
                      updateActionConfig(idx, "url", e.target.value)
                    }
                    placeholder="Webhook URL"
                    className="h-8 text-sm"
                  />
                )}
                {act.action === "notify_channel" && (
                  <Input
                    value={act.config?.channel || "alerts"}
                    onChange={(e) =>
                      updateActionConfig(idx, "channel", e.target.value)
                    }
                    placeholder="Channel name"
                    className="h-8 text-sm"
                  />
                )}
                {act.action === "trigger_alarm_output" && (
                  <div className="grid grid-cols-2 gap-2">
                    <Input
                      value={act.config?.relay_token || ""}
                      onChange={(e) =>
                        updateActionConfig(idx, "relay_token", e.target.value)
                      }
                      placeholder="Relay output (optional)"
                      className="h-8 text-sm"
                    />
                    <Input
                      type="number"
                      min={0}
                      max={300}
                      value={act.config?.release_after_seconds ?? 5}
                      onChange={(e) =>
                        updateActionConfig(
                          idx,
                          "release_after_seconds",
                          parseInt(e.target.value) || 0,
                        )
                      }
                      placeholder="Auto-release (seconds)"
                      className="h-8 text-sm"
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Cooldown & enabled */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Cooldown (seconds)</Label>
            <Input
              type="number"
              min={0}
              max={3600}
              value={form.cooldown_seconds}
              onChange={(e) =>
                setForm({
                  ...form,
                  cooldown_seconds: parseInt(e.target.value) || 0,
                })
              }
            />
          </div>
          <div className="flex items-end gap-2 pb-1">
            <Switch
              checked={form.enabled}
              onCheckedChange={(v) => setForm({ ...form, enabled: v })}
            />
            <Label>Enabled</Label>
          </div>
        </div>

        <Button
          onClick={handleSubmit}
          disabled={createMutation.isPending || updateMutation.isPending}
        >
          <Save className="h-4 w-4 mr-1" />
          {editing === "new" ? "Create Rule" : "Save Changes"}
        </Button>
      </div>
    );
  }

  // ========== RULE LIST ==========
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Link2 className="h-5 w-5" />
          <h3 className="font-semibold">Event Linkage Rules</h3>
        </div>
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4 mr-1" /> New Rule
        </Button>
      </div>

      {rules.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8 text-center">
          No linkage rules configured. Create one to automate responses to
          events.
        </p>
      ) : (
        <div className="space-y-2">
          {rules.map((rule) => (
            <div
              key={rule.id}
              className="border rounded-lg p-3 flex items-center justify-between"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm truncate">
                    {rule.name}
                  </span>
                  <span
                    className={`text-xs px-1.5 py-0.5 rounded ${
                      rule.enabled
                        ? "bg-[hsl(var(--ring)/0.20)] text-[var(--console-accent)]"
                        : "bg-card/70 text-muted-foreground"
                    }`}
                  >
                    {rule.enabled ? "Active" : "Disabled"}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  {TRIGGER_TYPES.find((t) => t.value === rule.trigger_type)
                    ?.label || rule.trigger_type}{" "}
                  → {rule.actions?.length || 0} action(s)
                  {rule.camera_ids?.length
                    ? ` • ${rule.camera_ids.length} camera(s)`
                    : " • All cameras"}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0"
                  onClick={() =>
                    toggleMutation.mutate({
                      id: rule.id,
                      enabled: !rule.enabled,
                    })
                  }
                >
                  {rule.enabled ? (
                    <PowerOff className="h-4 w-4" />
                  ) : (
                    <Power className="h-4 w-4" />
                  )}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0"
                  onClick={() => openEdit(rule)}
                >
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0 text-red-500"
                  onClick={() => deleteMutation.mutate(rule.id)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
