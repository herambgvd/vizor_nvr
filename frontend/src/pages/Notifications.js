// =============================================================================
// Notifications — Webhook + SMTP Email management
// =============================================================================

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bell, Plus, Trash2, TestTube2, CheckCircle, XCircle,
  Mail, Webhook, ChevronDown, RefreshCw, Eye, EyeOff,
  AlertCircle, Settings2, MessageSquare, Smartphone,
} from "lucide-react";
import { toast } from "sonner";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Switch } from "../components/ui/switch";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "../components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "../components/ui/table";
import { Checkbox } from "../components/ui/checkbox";
import { ScrollArea } from "../components/ui/scroll-area";
import api from "../api/client";

// ─── shared styles ────────────────────────────────────────────────────────────

const inputStyle = {
  background: "var(--console-raised)",
  border: "1px solid var(--console-border)",
  color: "var(--console-text)",
};

// ─── API helpers ──────────────────────────────────────────────────────────────

const fetchWebhooks = () => api.get("/notifications/webhooks").then((r) => r.data);
const fetchEventTypes = () => api.get("/notifications/events").then((r) => r.data);
const fetchLogs = (params) =>
  api.get("/notifications/logs", { params }).then((r) => r.data);
const fetchSettings = () => api.get("/settings").then((r) => r.data);

// ─── ONVIF event type labels ────────────────────────────────────────────────

const EVENT_LABELS = {
  camera_online: "Camera Online",
  camera_offline: "Camera Offline",
  camera_error: "Camera Error",
  motion_detected: "Motion Detected",
  camera_tamper: "Camera Tamper",
  digital_input_change: "Digital Input",
  line_crossing: "Line Crossing",
  zone_intrusion: "Zone Intrusion",
  audio_alarm: "Audio Alarm",
  face_detected: "Face Detected",
  recording_gap: "Recording Gap",
  recording_started: "Recording Started",
  recording_stopped: "Recording Stopped",
  storage_low: "Storage Low",
  disk_full: "Disk Full",
  system_error: "System Error",
  video_loss: "Video Loss",
};

const TABS = [
  { id: "webhooks", label: "Webhooks", icon: Webhook },
  { id: "email", label: "Email (SMTP)", icon: Mail },
  { id: "sms", label: "SMS / WhatsApp", icon: Smartphone },
  { id: "logs", label: "Delivery Logs", icon: Bell },
];

// ─── Webhook Form Dialog ────────────────────────────────────────────────────

const WebhookFormDialog = ({ open, onClose, webhook, eventTypes }) => {
  const qc = useQueryClient();
  const isEdit = !!webhook;
  const [form, setForm] = useState({
    name: webhook?.name || "",
    url: webhook?.url || "",
    secret: "",
    events: webhook?.events || [],
    is_active: webhook?.is_active ?? true,
    retry_count: webhook?.retry_count ?? 3,
    timeout_seconds: webhook?.timeout_seconds ?? 10,
  });
  const [showSecret, setShowSecret] = useState(false);
  const [testing, setTesting] = useState(false);

  const saveMutation = useMutation({
    mutationFn: (data) =>
      isEdit
        ? api.put(`/notifications/webhooks/${webhook.id}`, data)
        : api.post("/notifications/webhooks", data),
    onSuccess: () => {
      qc.invalidateQueries(["webhooks"]);
      toast.success(isEdit ? "Webhook updated" : "Webhook created");
      onClose();
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Save failed"),
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    const payload = { ...form };
    if (!payload.secret) delete payload.secret;
    saveMutation.mutate(payload);
  };

  const handleTest = async () => {
    if (!form.url) return toast.error("Enter a URL first");
    setTesting(true);
    try {
      const { data } = await api.post("/notifications/webhooks/test", {
        url: form.url,
        secret: form.secret || undefined,
      });
      if (data.success) toast.success(`Test delivered — HTTP ${data.status_code}`);
      else toast.error(`Test failed: ${data.error || "unknown error"}`);
    } catch {
      toast.error("Test request failed");
    } finally {
      setTesting(false);
    }
  };

  const toggleEvent = (ev) => {
    setForm((f) => ({
      ...f,
      events: f.events.includes(ev) ? f.events.filter((e) => e !== ev) : [...f.events, ev],
    }));
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent
        className="max-w-lg"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)", color: "var(--console-text)" }}
      >
        <DialogHeader>
          <DialogTitle className="font-telemetry text-xs uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
            {isEdit ? "Edit Webhook" : "New Webhook"}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <DlgField label="Name">
                <ConsoleInput value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required />
              </DlgField>
            </div>
            <div className="col-span-2">
              <DlgField label="URL">
                <div className="flex gap-2">
                  <ConsoleInput
                    value={form.url}
                    onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                    placeholder="https://hooks.example.com/nvr"
                    type="url"
                    required
                    className="flex-1"
                  />
                  <SecondaryBtn type="button" onClick={handleTest} disabled={testing}>
                    {testing ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <TestTube2 className="h-3.5 w-3.5" />}
                  </SecondaryBtn>
                </div>
              </DlgField>
            </div>
            <div className="col-span-2">
              <DlgField label="HMAC Secret (optional)">
                <div className="flex gap-2">
                  <ConsoleInput
                    value={form.secret}
                    onChange={(e) => setForm((f) => ({ ...f, secret: e.target.value }))}
                    type={showSecret ? "text" : "password"}
                    placeholder={isEdit ? "Leave blank to keep existing" : "Optional signing secret"}
                    className="flex-1"
                  />
                  <GhostIconBtn type="button" onClick={() => setShowSecret((v) => !v)}>
                    {showSecret ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  </GhostIconBtn>
                </div>
              </DlgField>
            </div>
            <DlgField label="Retry attempts">
              <ConsoleInput
                type="number"
                min={0}
                max={5}
                value={form.retry_count}
                onChange={(e) => setForm((f) => ({ ...f, retry_count: +e.target.value }))}
              />
            </DlgField>
            <DlgField label="Timeout (s)">
              <ConsoleInput
                type="number"
                min={1}
                max={60}
                value={form.timeout_seconds}
                onChange={(e) => setForm((f) => ({ ...f, timeout_seconds: +e.target.value }))}
              />
            </DlgField>
          </div>

          {/* Event filter */}
          <div>
            <label className="block font-telemetry text-[10px] uppercase tracking-wide mb-1" style={{ color: "var(--console-muted)" }}>
              Subscribed Events
            </label>
            <ScrollArea
              className="h-44 rounded p-2"
              style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
            >
              <div className="grid grid-cols-2 gap-1.5">
                {(eventTypes || []).map(({ value }) => (
                  <div key={value} className="flex items-center gap-2">
                    <Checkbox
                      id={`ev-${value}`}
                      checked={form.events.includes(value)}
                      onCheckedChange={() => toggleEvent(value)}
                    />
                    <label htmlFor={`ev-${value}`} className="font-telemetry text-[11px] cursor-pointer" style={{ color: "var(--console-text)" }}>
                      {EVENT_LABELS[value] || value}
                    </label>
                  </div>
                ))}
              </div>
            </ScrollArea>
            <p className="font-telemetry text-[10px] mt-1" style={{ color: "var(--console-muted)" }}>Empty = receive all events.</p>
          </div>

          <div className="flex items-center gap-2">
            <Switch
              checked={form.is_active}
              onCheckedChange={(v) => setForm((f) => ({ ...f, is_active: v }))}
            />
            <label className="font-telemetry text-xs" style={{ color: "var(--console-text)" }}>Active</label>
          </div>

          <DialogFooter>
            <SecondaryBtn type="button" onClick={onClose}>Cancel</SecondaryBtn>
            <PrimaryBtn type="submit" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? "Saving…" : isEdit ? "Save" : "Create"}
            </PrimaryBtn>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

// ─── SMTP Config Panel ───────────────────────────────────────────────────────

const SMTPPanel = ({ settings }) => {
  const qc = useQueryClient();
  const asBool = (v) => v === true || v === "true";
  const buildForm = (s) => ({
    smtp_host: s?.smtp_host || "",
    smtp_port: s?.smtp_port ? Number(s.smtp_port) : 587,
    smtp_username: s?.smtp_username || "",
    smtp_password: "",
    smtp_use_tls: s?.smtp_use_tls != null ? asBool(s.smtp_use_tls) : true,
    smtp_use_ssl: asBool(s?.smtp_use_ssl),
    smtp_from_email: s?.smtp_from_email || "",
    smtp_from_name: s?.smtp_from_name || "Vizor NVR",
    smtp_recipients: s?.smtp_recipients || "",
  });

  const [form, setForm] = useState(buildForm(settings));

  React.useEffect(() => {
    if (!settings) return;
    setForm((prev) => ({
      ...buildForm(settings),
      smtp_password: prev.smtp_password,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    settings?.smtp_host,
    settings?.smtp_port,
    settings?.smtp_username,
    settings?.smtp_use_tls,
    settings?.smtp_use_ssl,
    settings?.smtp_from_email,
    settings?.smtp_from_name,
    settings?.smtp_recipients,
  ]);
  const [showPassword, setShowPassword] = useState(false);
  const [testing, setTesting] = useState(false);

  const saveMutation = useMutation({
    mutationFn: (data) =>
      api.put("/settings", {
        settings: Object.fromEntries(
          Object.entries(data).map(([k, v]) => [k, String(v)]),
        ),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      toast.success("SMTP settings saved");
    },
    onError: () => toast.error("Failed to save SMTP settings"),
  });

  const handleSave = (e) => {
    e.preventDefault();
    const payload = { ...form, smtp_enabled: true };
    if (!payload.smtp_password) delete payload.smtp_password;
    saveMutation.mutate(payload);
  };

  const handleTest = async () => {
    if (!form.smtp_host || !form.smtp_from_email) {
      return toast.error("Fill in host and from email first");
    }
    const recipients = form.smtp_recipients
      ? form.smtp_recipients.split(",").map((s) => s.trim()).filter(Boolean)
      : [];
    if (!recipients.length) return toast.error("Add at least one recipient");

    setTesting(true);
    try {
      await api.post("/notifications/email/test", {
        host: form.smtp_host, port: +form.smtp_port,
        username: form.smtp_username, password: form.smtp_password,
        use_tls: form.smtp_use_tls, use_ssl: form.smtp_use_ssl,
        from_email: form.smtp_from_email, from_name: form.smtp_from_name,
        recipients,
      });
      toast.success("Test email sent successfully");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Test email failed");
    } finally {
      setTesting(false);
    }
  };

  return (
    <form onSubmit={handleSave} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <FormRow label="SMTP Host">
          <ConsoleInput value={form.smtp_host} onChange={(e) => setForm((f) => ({ ...f, smtp_host: e.target.value }))} placeholder="smtp.gmail.com" />
        </FormRow>
        <FormRow label="Port">
          <ConsoleInput type="number" value={form.smtp_port} onChange={(e) => setForm((f) => ({ ...f, smtp_port: +e.target.value }))} />
        </FormRow>
        <FormRow label="Username">
          <ConsoleInput value={form.smtp_username} onChange={(e) => setForm((f) => ({ ...f, smtp_username: e.target.value }))} />
        </FormRow>
        <FormRow label="Password">
          <div className="flex gap-2">
            <ConsoleInput
              type={showPassword ? "text" : "password"}
              value={form.smtp_password}
              onChange={(e) => setForm((f) => ({ ...f, smtp_password: e.target.value }))}
              placeholder="Leave blank to keep existing"
              className="flex-1"
            />
            <GhostIconBtn type="button" onClick={() => setShowPassword((v) => !v)}>
              {showPassword ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </GhostIconBtn>
          </div>
        </FormRow>
        <FormRow label="From Email">
          <ConsoleInput type="email" value={form.smtp_from_email} onChange={(e) => setForm((f) => ({ ...f, smtp_from_email: e.target.value }))} />
        </FormRow>
        <FormRow label="From Name">
          <ConsoleInput value={form.smtp_from_name} onChange={(e) => setForm((f) => ({ ...f, smtp_from_name: e.target.value }))} />
        </FormRow>
        <div className="col-span-2">
          <FormRow label="Recipients (comma-separated)">
            <ConsoleInput value={form.smtp_recipients} onChange={(e) => setForm((f) => ({ ...f, smtp_recipients: e.target.value }))} placeholder="ops@company.com, security@company.com" />
          </FormRow>
        </div>
        <div className="col-span-2 flex items-center gap-6">
          <div className="flex items-center gap-2">
            <Switch
              checked={form.smtp_use_tls === true || form.smtp_use_tls === "true"}
              onCheckedChange={(v) => setForm((f) => ({ ...f, smtp_use_tls: v }))}
            />
            <label className="font-telemetry text-xs" style={{ color: "var(--console-text)" }}>TLS (STARTTLS)</label>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              checked={form.smtp_use_ssl === true || form.smtp_use_ssl === "true"}
              onCheckedChange={(v) => setForm((f) => ({ ...f, smtp_use_ssl: v }))}
            />
            <label className="font-telemetry text-xs" style={{ color: "var(--console-text)" }}>SSL</label>
          </div>
        </div>
      </div>

      <div className="flex gap-2">
        <PrimaryBtn type="submit" disabled={saveMutation.isPending}>
          {saveMutation.isPending ? "Saving…" : "Save SMTP Settings"}
        </PrimaryBtn>
        <SecondaryBtn type="button" onClick={handleTest} disabled={testing}>
          {testing ? (
            <><RefreshCw className="h-3.5 w-3.5 mr-1.5 animate-spin" />Sending…</>
          ) : (
            <><TestTube2 className="h-3.5 w-3.5 mr-1.5" />Send Test Email</>
          )}
        </SecondaryBtn>
      </div>
    </form>
  );
};

// ─── Twilio SMS / WhatsApp Panel ─────────────────────────────────────────────

const TwilioPanel = ({ settings }) => {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    twilio_account_sid: settings?.twilio_account_sid || "",
    twilio_auth_token: "",
    twilio_phone_number: settings?.twilio_phone_number || "",
    twilio_whatsapp_number: settings?.twilio_whatsapp_number || "",
    sms_recipients: settings?.sms_recipients || "",
    whatsapp_recipients: settings?.whatsapp_recipients || "",
    sms_alert_events: settings?.sms_alert_events || "camera_offline,recording_error,storage_full",
    whatsapp_alert_events: settings?.whatsapp_alert_events || "camera_offline,recording_error,storage_full",
  });
  const [showToken, setShowToken] = useState(false);
  const [testingSms, setTestingSms] = useState(false);
  const [testingWa, setTestingWa] = useState(false);

  React.useEffect(() => {
    setForm((prev) => ({
      ...prev,
      twilio_account_sid: settings?.twilio_account_sid || "",
      twilio_phone_number: settings?.twilio_phone_number || "",
      twilio_whatsapp_number: settings?.twilio_whatsapp_number || "",
      sms_recipients: settings?.sms_recipients || "",
      whatsapp_recipients: settings?.whatsapp_recipients || "",
      sms_alert_events: settings?.sms_alert_events || "camera_offline,recording_error,storage_full",
      whatsapp_alert_events: settings?.whatsapp_alert_events || "camera_offline,recording_error,storage_full",
    }));
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: (data) => api.put("/settings", { settings: data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      toast.success("Twilio settings saved");
    },
    onError: () => toast.error("Failed to save Twilio settings"),
  });

  const handleSave = (e) => {
    e.preventDefault();
    const payload = { ...form };
    if (!payload.twilio_auth_token) delete payload.twilio_auth_token;
    saveMutation.mutate(payload);
  };

  const testSms = async () => {
    if (!form.sms_recipients) return toast.error("Add at least one SMS recipient");
    setTestingSms(true);
    try {
      await api.post("/notifications/sms/test", { to: form.sms_recipients.split(",")[0].trim(), message: "Vizor NVR SMS test" });
      toast.success("Test SMS sent");
    } catch (e) {
      toast.error(e.response?.data?.detail || "SMS test failed");
    } finally {
      setTestingSms(false);
    }
  };

  const testWa = async () => {
    if (!form.whatsapp_recipients) return toast.error("Add at least one WhatsApp recipient");
    setTestingWa(true);
    try {
      await api.post("/notifications/whatsapp/test", { to: form.whatsapp_recipients.split(",")[0].trim(), message: "Vizor NVR WhatsApp test" });
      toast.success("Test WhatsApp sent");
    } catch (e) {
      toast.error(e.response?.data?.detail || "WhatsApp test failed");
    } finally {
      setTestingWa(false);
    }
  };

  return (
    <form onSubmit={handleSave} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <FormRow label="Account SID">
          <ConsoleInput value={form.twilio_account_sid} onChange={(e) => setForm((f) => ({ ...f, twilio_account_sid: e.target.value }))} placeholder="ACxxxxxxxxxxxxxxxx" />
        </FormRow>
        <FormRow label="Auth Token">
          <div className="flex gap-2">
            <ConsoleInput type={showToken ? "text" : "password"} value={form.twilio_auth_token} onChange={(e) => setForm((f) => ({ ...f, twilio_auth_token: e.target.value }))} placeholder="Leave blank to keep existing" className="flex-1" />
            <GhostIconBtn type="button" onClick={() => setShowToken((v) => !v)}>
              {showToken ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </GhostIconBtn>
          </div>
        </FormRow>
        <FormRow label="SMS Sender Number">
          <ConsoleInput value={form.twilio_phone_number} onChange={(e) => setForm((f) => ({ ...f, twilio_phone_number: e.target.value }))} placeholder="+1234567890" />
        </FormRow>
        <FormRow label="WhatsApp Sender Number">
          <ConsoleInput value={form.twilio_whatsapp_number} onChange={(e) => setForm((f) => ({ ...f, twilio_whatsapp_number: e.target.value }))} placeholder="+1234567890" />
        </FormRow>
        <div className="col-span-2">
          <FormRow label="SMS Recipients (comma-separated)">
            <ConsoleInput value={form.sms_recipients} onChange={(e) => setForm((f) => ({ ...f, sms_recipients: e.target.value }))} placeholder="+911234567890, +911234567891" />
          </FormRow>
        </div>
        <div className="col-span-2">
          <FormRow label="WhatsApp Recipients (comma-separated)">
            <ConsoleInput value={form.whatsapp_recipients} onChange={(e) => setForm((f) => ({ ...f, whatsapp_recipients: e.target.value }))} placeholder="+911234567890, +911234567891" />
          </FormRow>
        </div>
        <div className="col-span-2">
          <FormRow label="SMS Alert Events (comma-separated)">
            <ConsoleInput value={form.sms_alert_events} onChange={(e) => setForm((f) => ({ ...f, sms_alert_events: e.target.value }))} />
          </FormRow>
        </div>
        <div className="col-span-2">
          <FormRow label="WhatsApp Alert Events (comma-separated)">
            <ConsoleInput value={form.whatsapp_alert_events} onChange={(e) => setForm((f) => ({ ...f, whatsapp_alert_events: e.target.value }))} />
          </FormRow>
        </div>
      </div>

      <div className="flex gap-2">
        <PrimaryBtn type="submit" disabled={saveMutation.isPending}>
          {saveMutation.isPending ? "Saving…" : "Save Twilio Settings"}
        </PrimaryBtn>
        <SecondaryBtn type="button" onClick={testSms} disabled={testingSms}>
          {testingSms ? <RefreshCw className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <MessageSquare className="h-3.5 w-3.5 mr-1.5" />}
          Test SMS
        </SecondaryBtn>
        <SecondaryBtn type="button" onClick={testWa} disabled={testingWa}>
          {testingWa ? <RefreshCw className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Smartphone className="h-3.5 w-3.5 mr-1.5" />}
          Test WhatsApp
        </SecondaryBtn>
      </div>
    </form>
  );
};

// ─── Notification Logs ───────────────────────────────────────────────────────

const LogsPanel = () => {
  const [filter, setFilter] = useState({ webhook_id: "", event_type: "" });
  const { data: logs = [], isLoading, refetch } = useQuery({
    queryKey: ["notif-logs", filter],
    queryFn: () => fetchLogs({ limit: 100, ...filter }),
  });

  const statusColor = {
    sent: "var(--console-online)",
    failed: "var(--console-rec)",
    pending: "var(--console-alarm)",
  };

  return (
    <div className="space-y-3">
      <div className="flex gap-2 items-center">
        <ConsoleInput
          placeholder="Filter by event type…"
          value={filter.event_type}
          onChange={(e) => setFilter((f) => ({ ...f, event_type: e.target.value }))}
          style={{ maxWidth: "200px" }}
        />
        <GhostIconBtn onClick={refetch}>
          <RefreshCw className="h-3.5 w-3.5" />
        </GhostIconBtn>
      </div>

      {isLoading ? (
        <p className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>Loading…</p>
      ) : logs.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16" style={{ color: "var(--console-muted)" }}>
          <Bell className="h-10 w-10 mb-3 opacity-30" />
          <p className="font-telemetry text-xs">No notification logs yet.</p>
        </div>
      ) : (
        <div
          className="rounded overflow-hidden"
          style={{ border: "1px solid var(--console-border)" }}
        >
          <table className="w-full font-telemetry text-[11px]">
            <thead style={{ background: "var(--console-raised)", borderBottom: "1px solid var(--console-border)" }}>
              <tr>
                {["Event", "Status", "HTTP", "Attempts", "Time"].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left font-semibold uppercase tracking-wide" style={{ color: "var(--console-muted)" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id} className="border-b last:border-0" style={{ borderColor: "var(--console-border)" }}>
                  <td className="px-3 py-2.5" style={{ color: "var(--console-text)" }}>
                    {EVENT_LABELS[log.event_type] || log.event_type}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="font-semibold" style={{ color: statusColor[log.status] || "var(--console-muted)" }}>
                      {log.status}
                    </span>
                  </td>
                  <td className="px-3 py-2.5" style={{ color: "var(--console-muted)" }}>{log.response_code || "—"}</td>
                  <td className="px-3 py-2.5" style={{ color: "var(--console-muted)" }}>{log.attempts}</td>
                  <td className="px-3 py-2.5" style={{ color: "var(--console-muted)" }}>
                    {log.created_at ? new Date(log.created_at).toLocaleString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Notifications() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editWebhook, setEditWebhook] = useState(null);
  const [tab, setTab] = useState("webhooks");

  const { data: webhooks = [], isLoading: wLoading } = useQuery({
    queryKey: ["webhooks"],
    queryFn: fetchWebhooks,
  });
  const { data: eventTypes = [] } = useQuery({
    queryKey: ["notif-event-types"],
    queryFn: fetchEventTypes,
  });
  const { data: rawSettings } = useQuery({
    queryKey: ["settings"],
    queryFn: fetchSettings,
  });
  // The /settings endpoint may return either an object map or an array of
  // { key, value } rows (documented past bug). Normalize to a flat object so
  // SMTP/Twilio fields read correctly and saving doesn't wipe config.
  const settings = React.useMemo(() => {
    if (Array.isArray(rawSettings)) {
      return Object.fromEntries(rawSettings.map((s) => [s.key, s.value]));
    }
    return rawSettings;
  }, [rawSettings]);

  const deleteMutation = useMutation({
    mutationFn: (id) => api.delete(`/notifications/webhooks/${id}`),
    onSuccess: () => {
      qc.invalidateQueries(["webhooks"]);
      toast.success("Webhook deleted");
    },
    onError: () => toast.error("Delete failed"),
  });

  const toggleActiveMutation = useMutation({
    mutationFn: ({ id, is_active }) =>
      api.put(`/notifications/webhooks/${id}`, { is_active }),
    onSuccess: () => qc.invalidateQueries(["webhooks"]),
  });

  const handleEdit = (wh) => { setEditWebhook(wh); setShowForm(true); };
  const handleClose = () => { setShowForm(false); setEditWebhook(null); };

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
          Notifications
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
        {/* ── Webhooks ── */}
        <div className={tab === "webhooks" ? "" : "hidden"}>
          <ConsoleSection
            title="Webhooks"
            subtitle="HTTP POST callbacks on NVR events"
            action={
              <PrimaryBtn onClick={() => { setEditWebhook(null); setShowForm(true); }}>
                <Plus className="h-3.5 w-3.5 mr-1" />
                Add Webhook
              </PrimaryBtn>
            }
          >
            {wLoading ? (
              <p className="font-telemetry text-xs py-8 text-center" style={{ color: "var(--console-muted)" }}>Loading…</p>
            ) : webhooks.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16" style={{ color: "var(--console-muted)" }}>
                <Webhook className="h-12 w-12 mb-3 opacity-30" />
                <p className="font-telemetry text-xs font-semibold">No webhooks configured</p>
                <p className="font-telemetry text-[10px] mt-1">Add one to start receiving event notifications.</p>
                <PrimaryBtn onClick={() => setShowForm(true)} className="mt-4">
                  <Plus className="h-3.5 w-3.5 mr-1" />Add Webhook
                </PrimaryBtn>
              </div>
            ) : (
              <div
                className="rounded overflow-hidden"
                style={{ border: "1px solid var(--console-border)" }}
              >
                <table className="w-full font-telemetry text-[11px]">
                  <thead style={{ background: "var(--console-raised)", borderBottom: "1px solid var(--console-border)" }}>
                    <tr>
                      {["Name", "URL", "Events", "Stats", "Active", ""].map((h, i) => (
                        <th key={i} className="px-3 py-2.5 text-left font-semibold uppercase tracking-wide" style={{ color: "var(--console-muted)" }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {webhooks.map((wh) => (
                      <tr key={wh.id} className="border-b last:border-0" style={{ borderColor: "var(--console-border)" }}>
                        <td className="px-3 py-2.5 font-semibold" style={{ color: "var(--console-text)" }}>
                          {wh.name}
                        </td>
                        <td className="px-3 py-2.5 max-w-[200px] truncate" style={{ color: "var(--console-muted)" }}>
                          {wh.url}
                        </td>
                        <td className="px-3 py-2.5" style={{ color: "var(--console-muted)" }}>
                          {wh.events?.length ? (
                            <span>{wh.events.length} event{wh.events.length !== 1 ? "s" : ""}</span>
                          ) : (
                            <span
                              className="px-1.5 py-0.5 rounded text-[10px]"
                              style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)", color: "var(--console-muted)" }}
                            >
                              All
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2.5">
                          <span style={{ color: "var(--console-online)" }}>{wh.success_count ?? 0} ok</span>
                          {" / "}
                          <span style={{ color: "var(--console-rec)" }}>{wh.failure_count ?? 0} fail</span>
                        </td>
                        <td className="px-3 py-2.5">
                          <Switch
                            checked={wh.is_active}
                            onCheckedChange={(v) => toggleActiveMutation.mutate({ id: wh.id, is_active: v })}
                          />
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="flex gap-0.5">
                            <GhostIconBtn onClick={() => handleEdit(wh)}>
                              <Settings2 className="h-3.5 w-3.5" />
                            </GhostIconBtn>
                            <GhostIconBtn
                              onClick={() => {
                                if (window.confirm(`Delete webhook "${wh.name}"?`)) {
                                  deleteMutation.mutate(wh.id);
                                }
                              }}
                            >
                              <Trash2 className="h-3.5 w-3.5" style={{ color: "var(--console-rec)" }} />
                            </GhostIconBtn>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </ConsoleSection>
        </div>

        {/* ── Email ── */}
        <div className={tab === "email" ? "" : "hidden"}>
          <ConsoleSection title="Email / SMTP" subtitle="Send alert emails for camera events, storage warnings, and system errors">
            <SMTPPanel settings={settings} />
          </ConsoleSection>
        </div>

        {/* ── SMS / WhatsApp ── */}
        <div className={tab === "sms" ? "" : "hidden"}>
          <ConsoleSection title="SMS / WhatsApp (Twilio)" subtitle="Send SMS and WhatsApp alerts via Twilio">
            <TwilioPanel settings={settings} />
          </ConsoleSection>
        </div>

        {/* ── Logs ── */}
        <div className={tab === "logs" ? "" : "hidden"}>
          <ConsoleSection title="Delivery Logs" subtitle="History of all notification attempts">
            <LogsPanel />
          </ConsoleSection>
        </div>
      </div>

      {/* Webhook form dialog */}
      {showForm && (
        <WebhookFormDialog
          open={showForm}
          onClose={handleClose}
          webhook={editWebhook}
          eventTypes={eventTypes}
        />
      )}
    </div>
  );
}

// ─── Shared UI primitives ────────────────────────────────────────────────────

const ConsoleSection = ({ title, subtitle, action, children }) => (
  <div
    className="rounded mb-4"
    style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
  >
    <div
      className="flex items-center justify-between px-4 py-3 border-b"
      style={{ borderColor: "var(--console-border)" }}
    >
      <div>
        <p className="font-telemetry text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
          {title}
        </p>
        {subtitle && (
          <p className="font-telemetry text-[10px] mt-0.5" style={{ color: "var(--console-muted)" }}>
            {subtitle}
          </p>
        )}
      </div>
      {action && <div>{action}</div>}
    </div>
    <div className="p-4">{children}</div>
  </div>
);

const FormRow = ({ label, children }) => (
  <div>
    <label className="block font-telemetry text-[10px] uppercase tracking-wide mb-1" style={{ color: "var(--console-muted)" }}>
      {label}
    </label>
    {children}
  </div>
);

const DlgField = ({ label, children }) => (
  <div>
    <label className="block font-telemetry text-[10px] uppercase tracking-wide mb-1" style={{ color: "var(--console-muted)" }}>
      {label}
    </label>
    {children}
  </div>
);

const PrimaryBtn = ({ children, disabled, onClick, type = "button", className = "" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className={`inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] font-semibold uppercase tracking-wide transition-opacity disabled:opacity-50 ${className}`}
    style={{ background: "var(--console-accent)", color: "#06231f" }}
  >
    {children}
  </button>
);

const SecondaryBtn = ({ children, disabled, onClick, type = "button", className = "" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className={`inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] border transition-colors hover:bg-white/5 disabled:opacity-50 ${className}`}
    style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}
  >
    {children}
  </button>
);

const GhostIconBtn = ({ children, onClick, disabled, title, type = "button" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    title={title}
    className="h-7 w-7 flex items-center justify-center rounded transition-colors hover:bg-white/5 disabled:opacity-50"
    style={{ color: "var(--console-muted)" }}
  >
    {children}
  </button>
);

const ConsoleInput = ({ className = "", style: extraStyle = {}, ...props }) => (
  <input
    {...props}
    className={`w-full rounded font-telemetry text-xs h-[30px] px-2 border outline-none focus:ring-1 ${className}`}
    style={{
      background: "var(--console-raised)",
      border: "1px solid var(--console-border)",
      color: "var(--console-text)",
      "--tw-ring-color": "var(--console-accent)",
      ...extraStyle,
    }}
  />
);
