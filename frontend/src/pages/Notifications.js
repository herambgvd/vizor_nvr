// =============================================================================
// Notifications — Webhook + SMTP Email management
// =============================================================================

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bell, Plus, Trash2, TestTube2, CheckCircle, XCircle,
  Mail, Webhook, ChevronDown, RefreshCw, Eye, EyeOff,
  AlertCircle, Settings2,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Switch } from "../components/ui/switch";
import PageTabs from "../components/ui/page-tabs";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "../components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "../components/ui/table";
import { Checkbox } from "../components/ui/checkbox";
import { ScrollArea } from "../components/ui/scroll-area";
import api from "../api/client";

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
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Webhook" : "New Webhook"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2 space-y-1">
              <Label>Name</Label>
              <Input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required />
            </div>
            <div className="col-span-2 space-y-1">
              <Label>URL</Label>
              <div className="flex gap-2">
                <Input
                  value={form.url}
                  onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                  placeholder="https://hooks.example.com/nvr"
                  type="url"
                  required
                  className="flex-1"
                />
                <Button type="button" variant="outline" size="sm" onClick={handleTest} disabled={testing}>
                  {testing ? <RefreshCw className="h-4 w-4 animate-spin" /> : <TestTube2 className="h-4 w-4" />}
                </Button>
              </div>
            </div>
            <div className="col-span-2 space-y-1">
              <Label>HMAC Secret (optional)</Label>
              <div className="flex gap-2">
                <Input
                  value={form.secret}
                  onChange={(e) => setForm((f) => ({ ...f, secret: e.target.value }))}
                  type={showSecret ? "text" : "password"}
                  placeholder={isEdit ? "Leave blank to keep existing" : "Optional signing secret"}
                  className="flex-1"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowSecret((v) => !v)}
                >
                  {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
              </div>
            </div>
            <div className="space-y-1">
              <Label>Retry attempts</Label>
              <Input
                type="number"
                min={0}
                max={5}
                value={form.retry_count}
                onChange={(e) => setForm((f) => ({ ...f, retry_count: +e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <Label>Timeout (s)</Label>
              <Input
                type="number"
                min={1}
                max={60}
                value={form.timeout_seconds}
                onChange={(e) => setForm((f) => ({ ...f, timeout_seconds: +e.target.value }))}
              />
            </div>
          </div>

          {/* Event filter */}
          <div className="space-y-2">
            <Label>Subscribed Events</Label>
            <ScrollArea className="h-44 rounded border p-2">
              <div className="grid grid-cols-2 gap-1.5">
                {(eventTypes || []).map(({ value }) => (
                  <div key={value} className="flex items-center gap-2">
                    <Checkbox
                      id={`ev-${value}`}
                      checked={form.events.includes(value)}
                      onCheckedChange={() => toggleEvent(value)}
                    />
                    <label htmlFor={`ev-${value}`} className="text-sm cursor-pointer">
                      {EVENT_LABELS[value] || value}
                    </label>
                  </div>
                ))}
              </div>
            </ScrollArea>
            <p className="text-xs text-muted-foreground">Empty = receive all events.</p>
          </div>

          <div className="flex items-center gap-2">
            <Switch
              checked={form.is_active}
              onCheckedChange={(v) => setForm((f) => ({ ...f, is_active: v }))}
            />
            <Label>Active</Label>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? "Saving…" : isEdit ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

// ─── SMTP Config Panel ───────────────────────────────────────────────────────

const SMTPPanel = ({ settings }) => {
  const qc = useQueryClient();
  // Settings stored as strings on backend — normalize types here
  const asBool = (v) => v === true || v === "true";
  const buildForm = (s) => ({
    smtp_host: s?.smtp_host || "",
    smtp_port: s?.smtp_port ? Number(s.smtp_port) : 587,
    smtp_username: s?.smtp_username || "",
    smtp_password: "",
    smtp_use_tls: s?.smtp_use_tls != null ? asBool(s.smtp_use_tls) : true,
    smtp_use_ssl: asBool(s?.smtp_use_ssl),
    smtp_from_email: s?.smtp_from_email || "",
    smtp_from_name: s?.smtp_from_name || "GVD NVR",
    smtp_recipients: s?.smtp_recipients || "",
  });

  const [form, setForm] = useState(buildForm(settings));

  // Re-init when settings arrive from the API after initial mount.
  // Re-run if any tracked field changed (server canonical version).
  React.useEffect(() => {
    if (!settings) return;
    setForm((prev) => ({
      ...buildForm(settings),
      // Preserve in-flight password edits — backend never echoes the
      // current password back.
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
    // Drop empty password so existing one isn't overwritten with blank.
    // SMTP is implicitly enabled — selection-level granularity comes later.
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
        host: form.smtp_host,
        port: +form.smtp_port,
        username: form.smtp_username,
        password: form.smtp_password,
        use_tls: form.smtp_use_tls,
        use_ssl: form.smtp_use_ssl,
        from_email: form.smtp_from_email,
        from_name: form.smtp_from_name,
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
    <form onSubmit={handleSave} className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <Label>SMTP Host</Label>
          <Input
            value={form.smtp_host}
            onChange={(e) => setForm((f) => ({ ...f, smtp_host: e.target.value }))}
            placeholder="smtp.gmail.com"
          />
        </div>
        <div className="space-y-1">
          <Label>Port</Label>
          <Input
            type="number"
            value={form.smtp_port}
            onChange={(e) => setForm((f) => ({ ...f, smtp_port: +e.target.value }))}
          />
        </div>
        <div className="space-y-1">
          <Label>Username</Label>
          <Input
            value={form.smtp_username}
            onChange={(e) => setForm((f) => ({ ...f, smtp_username: e.target.value }))}
          />
        </div>
        <div className="space-y-1">
          <Label>Password</Label>
          <div className="flex gap-2">
            <Input
              type={showPassword ? "text" : "password"}
              value={form.smtp_password}
              onChange={(e) => setForm((f) => ({ ...f, smtp_password: e.target.value }))}
              placeholder="Leave blank to keep existing"
              className="flex-1"
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setShowPassword((v) => !v)}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>
        </div>
        <div className="space-y-1">
          <Label>From Email</Label>
          <Input
            type="email"
            value={form.smtp_from_email}
            onChange={(e) => setForm((f) => ({ ...f, smtp_from_email: e.target.value }))}
          />
        </div>
        <div className="space-y-1">
          <Label>From Name</Label>
          <Input
            value={form.smtp_from_name}
            onChange={(e) => setForm((f) => ({ ...f, smtp_from_name: e.target.value }))}
          />
        </div>
        <div className="col-span-2 space-y-1">
          <Label>Recipients (comma-separated)</Label>
          <Input
            value={form.smtp_recipients}
            onChange={(e) => setForm((f) => ({ ...f, smtp_recipients: e.target.value }))}
            placeholder="ops@company.com, security@company.com"
          />
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Switch
              checked={form.smtp_use_tls === true || form.smtp_use_tls === "true"}
              onCheckedChange={(v) => setForm((f) => ({ ...f, smtp_use_tls: v }))}
            />
            <Label>TLS (STARTTLS)</Label>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              checked={form.smtp_use_ssl === true || form.smtp_use_ssl === "true"}
              onCheckedChange={(v) => setForm((f) => ({ ...f, smtp_use_ssl: v }))}
            />
            <Label>SSL</Label>
          </div>
        </div>
      </div>

      <div className="flex gap-3">
        <Button type="submit" disabled={saveMutation.isPending}>
          {saveMutation.isPending ? "Saving…" : "Save SMTP Settings"}
        </Button>
        <Button type="button" variant="outline" onClick={handleTest} disabled={testing}>
          {testing ? (
            <><RefreshCw className="h-4 w-4 mr-2 animate-spin" />Sending…</>
          ) : (
            <><TestTube2 className="h-4 w-4 mr-2" />Send Test Email</>
          )}
        </Button>
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
    sent: "text-green-600",
    failed: "text-red-600",
    pending: "text-yellow-600",
  };

  return (
    <div className="space-y-4">
      <div className="flex gap-3 items-center">
        <Input
          placeholder="Filter by event type…"
          value={filter.event_type}
          onChange={(e) => setFilter((f) => ({ ...f, event_type: e.target.value }))}
          className="w-48"
        />
        <Button variant="outline" size="sm" onClick={refetch}>
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : logs.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <Bell className="h-10 w-10 mb-3 opacity-30" />
          <p>No notification logs yet.</p>
        </div>
      ) : (
        <div className="rounded-md border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Event</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>HTTP</TableHead>
                <TableHead>Attempts</TableHead>
                <TableHead>Time</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {logs.map((log) => (
                <TableRow key={log.id}>
                  <TableCell className="font-mono text-xs">
                    {EVENT_LABELS[log.event_type] || log.event_type}
                  </TableCell>
                  <TableCell>
                    <span className={`text-xs font-medium ${statusColor[log.status] || ""}`}>
                      {log.status}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{log.response_code || "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{log.attempts}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {log.created_at ? new Date(log.created_at).toLocaleString() : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
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
  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: fetchSettings,
  });

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

  const handleEdit = (wh) => {
    setEditWebhook(wh);
    setShowForm(true);
  };

  const handleClose = () => {
    setShowForm(false);
    setEditWebhook(null);
  };

  const tabs = [
    { id: "webhooks", label: "Webhooks", icon: Webhook },
    { id: "email", label: "Email (SMTP)", icon: Mail },
    { id: "logs", label: "Delivery Logs", icon: Bell },
  ];

  return (
    <div className="p-4 md:p-6 h-full overflow-y-auto">
      <div className="mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Notifications
        </h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          Configure webhooks and email alerts
        </p>
      </div>

      <PageTabs tabs={tabs} value={tab} onValueChange={setTab} className="mb-6" />

      <div className={tab === "webhooks" ? "" : "hidden"}>
        {/* ── Webhooks ── */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <div>
                <CardTitle>Webhooks</CardTitle>
                <CardDescription>HTTP POST callbacks on NVR events</CardDescription>
              </div>
              <Button size="sm" onClick={() => { setEditWebhook(null); setShowForm(true); }}>
                <Plus className="h-4 w-4 mr-2" />
                Add Webhook
              </Button>
            </CardHeader>
            <CardContent>
              {wLoading ? (
                <p className="text-sm text-muted-foreground py-8 text-center">Loading…</p>
              ) : webhooks.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                  <Webhook className="h-12 w-12 mb-3 opacity-30" />
                  <p className="font-medium">No webhooks configured</p>
                  <p className="text-sm mt-1">Add one to start receiving event notifications.</p>
                  <Button
                    size="sm"
                    variant="outline"
                    className="mt-4"
                    onClick={() => setShowForm(true)}
                  >
                    <Plus className="h-4 w-4 mr-2" />Add Webhook
                  </Button>
                </div>
              ) : (
                <div className="rounded-md border overflow-hidden">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Name</TableHead>
                        <TableHead>URL</TableHead>
                        <TableHead>Events</TableHead>
                        <TableHead>Stats</TableHead>
                        <TableHead>Active</TableHead>
                        <TableHead />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {webhooks.map((wh) => (
                        <TableRow key={wh.id}>
                          <TableCell className="font-medium">{wh.name}</TableCell>
                          <TableCell className="font-mono text-xs text-muted-foreground max-w-[200px] truncate">
                            {wh.url}
                          </TableCell>
                          <TableCell>
                            {wh.events?.length ? (
                              <span className="text-xs text-muted-foreground">
                                {wh.events.length} event{wh.events.length !== 1 ? "s" : ""}
                              </span>
                            ) : (
                              <Badge variant="secondary" className="text-xs">All</Badge>
                            )}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            <span className="text-green-600">{wh.success_count ?? 0} ok</span>
                            {" / "}
                            <span className="text-red-500">{wh.failure_count ?? 0} fail</span>
                          </TableCell>
                          <TableCell>
                            <Switch
                              checked={wh.is_active}
                              onCheckedChange={(v) =>
                                toggleActiveMutation.mutate({ id: wh.id, is_active: v })
                              }
                            />
                          </TableCell>
                          <TableCell>
                            <div className="flex gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleEdit(wh)}
                              >
                                <Settings2 className="h-4 w-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="text-red-500 hover:text-red-700"
                                onClick={() => {
                                  if (window.confirm(`Delete webhook "${wh.name}"?`)) {
                                    deleteMutation.mutate(wh.id);
                                  }
                                }}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
      </div>

      <div className={tab === "email" ? "" : "hidden"}>
        {/* ── Email ── */}
        <Card>
          <CardHeader>
            <CardTitle>Email / SMTP</CardTitle>
            <CardDescription>
              Send alert emails for camera events, storage warnings, and system errors
            </CardDescription>
          </CardHeader>
          <CardContent>
            <SMTPPanel settings={settings} />
          </CardContent>
        </Card>
      </div>

      <div className={tab === "logs" ? "" : "hidden"}>
        {/* ── Logs ── */}
        <Card>
          <CardHeader>
            <CardTitle>Delivery Logs</CardTitle>
            <CardDescription>History of all notification attempts</CardDescription>
          </CardHeader>
          <CardContent>
            <LogsPanel />
          </CardContent>
        </Card>
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
