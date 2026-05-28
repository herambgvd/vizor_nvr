// =============================================================================
// IntegrationsPage — settings for new modules
// Route: /settings/integrations (admin only)
// =============================================================================
// Covers: Twilio SMS, Twilio WhatsApp, POS overlay TCP port, ANR,
//         Dewarp defaults, RAID monitoring, Archive schedule, Cluster node.
// All settings are saved to the backend via PATCH /api/settings (key/value).
// =============================================================================

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  MessageSquare,
  Phone,
  Cpu,
  Database,
  HardDrive,
  Server,
  Archive,
  Eye,
} from "lucide-react";
import { cn } from "../../lib/utils";

// ── API helpers ───────────────────────────────────────────────────────────

const api = (path, opts = {}) =>
  fetch(`/api${path}`, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${localStorage.getItem("nvr_access_token")}`,
      ...opts.headers,
    },
    ...opts,
  }).then(async (r) => {
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${r.status}`);
    }
    return r.json();
  });

const fetchSettings = () => api("/settings");
const patchSetting = ({ key, value }) =>
  api("/settings", {
    method: "PATCH",
    body: JSON.stringify({ key, value }),
  });

const testSMS = (to) =>
  api("/notifications/sms/test", {
    method: "POST",
    body: JSON.stringify({ to, message: "GVD NVR SMS test" }),
  });

const testWhatsApp = (to) =>
  api("/notifications/whatsapp/test", {
    method: "POST",
    body: JSON.stringify({ to, message: "GVD NVR WhatsApp test" }),
  });

// ── Section component ─────────────────────────────────────────────────────

const Section = ({ icon: Icon, title, children }) => (
  <div className="border border-border rounded-lg overflow-hidden mb-6">
    <div className="flex items-center gap-2 px-4 py-3 bg-card/40 border-b border-border">
      <Icon className="h-4 w-4 text-teal-400" />
      <h3 className="text-sm font-semibold">{title}</h3>
    </div>
    <div className="p-4 space-y-4">{children}</div>
  </div>
);

// ── Field component ───────────────────────────────────────────────────────

const Field = ({ label, hint, children }) => (
  <div className="grid grid-cols-1 md:grid-cols-3 gap-2 items-start">
    <div>
      <div className="text-sm font-medium">{label}</div>
      {hint && <div className="text-xs text-zinc-500 mt-0.5">{hint}</div>}
    </div>
    <div className="md:col-span-2">{children}</div>
  </div>
);

const Input = ({ value, onChange, type = "text", placeholder, className }) => (
  <input
    type={type}
    value={value}
    onChange={(e) => onChange(e.target.value)}
    placeholder={placeholder}
    className={cn(
      "w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm",
      "focus:outline-none focus:ring-2 focus:ring-teal-500",
      className
    )}
  />
);

const Button = ({ onClick, disabled, loading, children, variant = "primary" }) => (
  <button
    onClick={onClick}
    disabled={disabled || loading}
    className={cn(
      "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
      variant === "primary"
        ? "bg-teal-600 hover:bg-teal-500 text-white disabled:opacity-50"
        : "border border-border hover:bg-card/60 text-zinc-300 disabled:opacity-50"
    )}
  >
    {loading && (
      <span className="animate-spin h-3.5 w-3.5 border-2 border-white border-t-transparent rounded-full" />
    )}
    {children}
  </button>
);

// ── Main page ─────────────────────────────────────────────────────────────

const IntegrationsPage = () => {
  const qc = useQueryClient();
  const { data: raw = {}, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: fetchSettings,
  });

  // Flatten settings array/object into a key→value map
  const settings = React.useMemo(() => {
    if (Array.isArray(raw)) {
      return Object.fromEntries(raw.map((s) => [s.key, s.value]));
    }
    return raw;
  }, [raw]);

  const [local, setLocal] = useState({});
  const get = (key, fallback = "") =>
    local[key] !== undefined ? local[key] : (settings[key] ?? fallback);
  const set = (key, value) => setLocal((p) => ({ ...p, [key]: value }));

  const saveMut = useMutation({
    mutationFn: patchSetting,
    onSuccess: () => qc.invalidateQueries(["settings"]),
  });

  const save = (key) => {
    const value = local[key];
    if (value === undefined) return;
    saveMut.mutate(
      { key, value },
      {
        onSuccess: () => toast.success(`Saved ${key}`),
        onError: (e) => toast.error(`Failed: ${e.message}`),
      }
    );
  };

  const saveMany = (keys) => {
    const dirtyKeys = keys.filter((k) => local[k] !== undefined);
    if (!dirtyKeys.length) {
      toast.info("No changes to save");
      return;
    }
    Promise.all(dirtyKeys.map((k) => saveMut.mutateAsync({ key: k, value: local[k] })))
      .then(() => {
        toast.success("Settings saved");
        qc.invalidateQueries(["settings"]);
      })
      .catch((e) => toast.error(`Save failed: ${e.message}`));
  };

  // SMS test
  const [smsTestTo, setSmsTestTo] = useState("");
  const [smsTestLoading, setSmsTestLoading] = useState(false);
  const handleSmsTest = async () => {
    if (!smsTestTo) return;
    setSmsTestLoading(true);
    try {
      await testSMS(smsTestTo);
      toast.success("Test SMS sent");
    } catch (e) {
      toast.error(`SMS test failed: ${e.message}`);
    } finally {
      setSmsTestLoading(false);
    }
  };

  // WhatsApp test
  const [waTestTo, setWaTestTo] = useState("");
  const [waTestLoading, setWaTestLoading] = useState(false);
  const handleWaTest = async () => {
    if (!waTestTo) return;
    setWaTestLoading(true);
    try {
      await testWhatsApp(waTestTo);
      toast.success("Test WhatsApp message sent");
    } catch (e) {
      toast.error(`WhatsApp test failed: ${e.message}`);
    } finally {
      setWaTestLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32 text-zinc-500 text-sm">
        Loading…
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 max-w-3xl">
      <h2 className="text-base font-semibold mb-1">Integrations & Advanced</h2>
      <p className="text-xs text-zinc-500 mb-6">
        Configure SMS/WhatsApp alerts, POS overlay, ANR, dewarp, RAID
        monitoring, and archive scheduling.
      </p>

      {/* ── Twilio SMS ── */}
      <Section icon={MessageSquare} title="SMS Alerts (Twilio)">
        <Field label="Account SID" hint="Starts with AC">
          <Input
            value={get("twilio_account_sid")}
            onChange={(v) => set("twilio_account_sid", v)}
            placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            type="password"
          />
        </Field>
        <Field label="Auth Token">
          <Input
            value={get("twilio_auth_token")}
            onChange={(v) => set("twilio_auth_token", v)}
            placeholder="••••••••"
            type="password"
          />
        </Field>
        <Field label="From Number" hint="E.164 format e.g. +12015551234">
          <Input
            value={get("twilio_phone_number")}
            onChange={(v) => set("twilio_phone_number", v)}
            placeholder="+12015551234"
          />
        </Field>
        <div className="flex gap-2 pt-1">
          <Button onClick={() => saveMany(["twilio_account_sid", "twilio_auth_token", "twilio_phone_number"])}>
            Save SMS Settings
          </Button>
        </div>
        <Field label="Send test SMS" hint="Enter recipient number to verify config">
          <div className="flex gap-2">
            <Input
              value={smsTestTo}
              onChange={setSmsTestTo}
              placeholder="+919876543210"
            />
            <Button onClick={handleSmsTest} loading={smsTestLoading}>
              Send Test
            </Button>
          </div>
        </Field>
      </Section>

      {/* ── Twilio WhatsApp ── */}
      <Section icon={Phone} title="WhatsApp Alerts (Twilio)">
        <p className="text-xs text-zinc-500 -mt-1 mb-2">
          Requires a Twilio-approved WhatsApp Business number.{" "}
          <a
            href="https://console.twilio.com/us1/develop/sms/whatsapp/learn"
            target="_blank"
            rel="noopener noreferrer"
            className="text-teal-400 underline"
          >
            Register at twilio.com/console
          </a>
        </p>
        <Field label="WhatsApp From" hint="Approved business number (E.164)">
          <Input
            value={get("twilio_whatsapp_number")}
            onChange={(v) => set("twilio_whatsapp_number", v)}
            placeholder="+14155551234"
          />
        </Field>
        <div className="flex gap-2 pt-1">
          <Button onClick={() => save("twilio_whatsapp_number")}>
            Save WhatsApp Number
          </Button>
        </div>
        <Field label="Send test message" hint="WhatsApp recipient number">
          <div className="flex gap-2">
            <Input
              value={waTestTo}
              onChange={setWaTestTo}
              placeholder="+919876543210"
            />
            <Button onClick={handleWaTest} loading={waTestLoading}>
              Send Test
            </Button>
          </div>
        </Field>
      </Section>

      {/* ── POS / ATM Overlay ── */}
      <Section icon={Cpu} title="POS / ATM Text Overlay">
        <p className="text-xs text-zinc-500 -mt-1 mb-2">
          Changes take effect on next backend restart (port binding). IP→camera
          mapping is done via <code className="bg-zinc-800 px-1 rounded">POS_CAM_&lt;IP&gt;=&lt;camera-uuid&gt;</code> env vars.
        </p>
        <Field label="TCP Port" hint="Default 9100 (raw-print). Change to avoid conflict.">
          <Input
            value={get("pos_overlay_port", "9100")}
            onChange={(v) => set("pos_overlay_port", v)}
            placeholder="9100"
          />
        </Field>
        <Field label="Max Message Size" hint="Bytes per message before connection is closed (default 4096)">
          <Input
            value={get("pos_max_message_bytes", "4096")}
            onChange={(v) => set("pos_max_message_bytes", v)}
            placeholder="4096"
          />
        </Field>
        <div className="flex gap-2 pt-1">
          <Button onClick={() => saveMany(["pos_overlay_port", "pos_max_message_bytes"])}>
            Save POS Settings
          </Button>
        </div>
      </Section>

      {/* ── ANR ── */}
      <Section icon={Database} title="ANR — Automatic Network Replenishment">
        <Field
          label="Debounce (seconds)"
          hint="Camera must be stable online for this long before ANR triggers"
        >
          <Input
            value={get("anr_debounce_seconds", "60")}
            onChange={(v) => set("anr_debounce_seconds", v)}
            placeholder="60"
          />
        </Field>
        <Field label="Max Concurrent Jobs" hint="Limits aggregate ANR download bandwidth">
          <Input
            value={get("anr_max_concurrent_jobs", "2")}
            onChange={(v) => set("anr_max_concurrent_jobs", v)}
            placeholder="2"
          />
        </Field>
        <div className="flex gap-2 pt-1">
          <Button onClick={() => saveMany(["anr_debounce_seconds", "anr_max_concurrent_jobs"])}>
            Save ANR Settings
          </Button>
        </div>
      </Section>

      {/* ── Dewarp ── */}
      <Section icon={Eye} title="Dewarp (360° Fisheye)">
        <p className="text-xs text-zinc-500 -mt-1 mb-2">
          Requires FFmpeg ≥ 4.3 (v360 filter). Without a GPU encoder, output is
          automatically scaled to the fallback resolution.
        </p>
        <Field label="Max Concurrent Jobs" hint="CPU guard — default 4">
          <Input
            value={get("dewarp_max_concurrent", "4")}
            onChange={(v) => set("dewarp_max_concurrent", v)}
            placeholder="4"
          />
        </Field>
        <Field label="Fallback Width (px)" hint="Used when no GPU encoder available">
          <Input
            value={get("dewarp_fallback_width", "1280")}
            onChange={(v) => set("dewarp_fallback_width", v)}
            placeholder="1280"
          />
        </Field>
        <Field label="Fallback Height (px)">
          <Input
            value={get("dewarp_fallback_height", "720")}
            onChange={(v) => set("dewarp_fallback_height", v)}
            placeholder="720"
          />
        </Field>
        <div className="flex gap-2 pt-1">
          <Button
            onClick={() =>
              saveMany(["dewarp_max_concurrent", "dewarp_fallback_width", "dewarp_fallback_height"])
            }
          >
            Save Dewarp Settings
          </Button>
        </div>
      </Section>

      {/* ── RAID ── */}
      <Section icon={HardDrive} title="RAID Monitoring">
        <p className="text-xs text-zinc-500 -mt-1 mb-2">
          RAID management requires Linux + mdadm. On macOS/Windows containers
          the RAID service returns <code className="bg-zinc-800 px-1 rounded">available: false</code>.
        </p>
        <Field label="Poll Interval (seconds)" hint="How often to check for degraded arrays">
          <Input
            value={get("raid_poll_interval", "60")}
            onChange={(v) => set("raid_poll_interval", v)}
            placeholder="60"
          />
        </Field>
        <div className="flex gap-2 pt-1">
          <Button onClick={() => save("raid_poll_interval")}>
            Save RAID Settings
          </Button>
        </div>
      </Section>

      {/* ── Archive ── */}
      <Section icon={Archive} title="Archive / Scheduled Backup">
        <Field
          label="NAS Max Backoff (seconds)"
          hint="Maximum retry delay when NAS is unreachable (default 960 = 16 min)"
        >
          <Input
            value={get("archive_nas_max_backoff", "960")}
            onChange={(v) => set("archive_nas_max_backoff", v)}
            placeholder="960"
          />
        </Field>
        <Field label="Check Interval (seconds)" hint="How often cron schedules are evaluated">
          <Input
            value={get("archive_check_interval", "60")}
            onChange={(v) => set("archive_check_interval", v)}
            placeholder="60"
          />
        </Field>
        <div className="flex gap-2 pt-1">
          <Button onClick={() => saveMany(["archive_nas_max_backoff", "archive_check_interval"])}>
            Save Archive Settings
          </Button>
        </div>
      </Section>

      {/* ── Cluster ── */}
      <Section icon={Server} title="Cluster / N+1 Hot Standby">
        <p className="text-xs text-zinc-500 -mt-1 mb-2">
          These settings take effect on restart. Leader election uses Postgres
          advisory locks — requires PostgreSQL (SQLite is single-node only).
        </p>
        <Field label="Node ID" hint="Unique name for this NVR node (default: hostname)">
          <Input
            value={get("nvr_node_id", "")}
            onChange={(v) => set("nvr_node_id", v)}
            placeholder="nvr-node-01"
          />
        </Field>
        <Field label="Heartbeat Interval (s)" hint="How often each node tries to acquire leadership">
          <Input
            value={get("cluster_heartbeat_interval", "5")}
            onChange={(v) => set("cluster_heartbeat_interval", v)}
            placeholder="5"
          />
        </Field>
        <Field label="Lease TTL (s)" hint="Standby takes over if leader misses this many seconds">
          <Input
            value={get("cluster_lease_ttl", "15")}
            onChange={(v) => set("cluster_lease_ttl", v)}
            placeholder="15"
          />
        </Field>
        <div className="flex gap-2 pt-1">
          <Button
            onClick={() =>
              saveMany(["nvr_node_id", "cluster_heartbeat_interval", "cluster_lease_ttl"])
            }
          >
            Save Cluster Settings
          </Button>
        </div>
      </Section>
    </div>
  );
};

export default IntegrationsPage;
