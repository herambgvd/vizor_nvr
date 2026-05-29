// =============================================================================
// IntegrationsPage — settings for new modules
// Route: /settings/integrations (admin only)
// =============================================================================
// Covers: Twilio SMS, Twilio WhatsApp, POS overlay TCP port, ANR,
//         Dewarp defaults, RAID monitoring, Archive schedule, Cluster node.
// All settings are saved to the backend via PUT /api/settings/{key}.
// Uses the shared apiClient so auth + token refresh are handled centrally.
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
import apiClient from "../../api/client";

// ── API helpers ───────────────────────────────────────────────────────────
// All requests go through the shared axios client, which attaches the access
// token and transparently refreshes it on 401. A bespoke fetch wrapper here
// previously read the wrong localStorage key and used a non-existent PATCH
// route, so loads 401'd and saves 405'd.

const fetchSettings = () => apiClient.get("/settings").then((r) => r.data);
const patchSetting = ({ key, value }) =>
  apiClient.put(`/settings/${key}`, { value: String(value) }).then((r) => r.data);

const testSMS = (to) =>
  apiClient
    .post("/notifications/sms/test", { to, message: "GVD NVR SMS test" })
    .then((r) => r.data);

const testWhatsApp = (to) =>
  apiClient
    .post("/notifications/whatsapp/test", { to, message: "GVD NVR WhatsApp test" })
    .then((r) => r.data);

// ── Shared primitives ─────────────────────────────────────────────────────

const PrimaryBtn = ({ children, disabled, onClick, loading, type = "button" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled || loading}
    className="inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] font-semibold uppercase tracking-wide transition-opacity disabled:opacity-50"
    style={{ background: "var(--console-accent)", color: "#06231f" }}
  >
    {loading && (
      <span
        className="animate-spin h-3.5 w-3.5 border-2 border-current border-t-transparent rounded-full mr-1.5"
      />
    )}
    {children}
  </button>
);

const ConsoleInput = ({ value, onChange, type = "text", placeholder, className = "" }) => (
  <input
    type={type}
    value={value}
    onChange={(e) => onChange(e.target.value)}
    placeholder={placeholder}
    className={`w-full rounded font-telemetry text-xs h-[30px] px-2 border outline-none focus:ring-1 ${className}`}
    style={{
      background: "var(--console-raised)",
      border: "1px solid var(--console-border)",
      color: "var(--console-text)",
      "--tw-ring-color": "var(--console-accent)",
    }}
  />
);

// ── Section component ─────────────────────────────────────────────────────

const Section = ({ icon: Icon, title, children }) => (
  <div
    className="rounded overflow-hidden mb-4 break-inside-avoid"
    style={{ border: "1px solid var(--console-border)" }}
  >
    <div
      className="flex items-center gap-2 px-4 py-3 border-b"
      style={{
        background: "var(--console-panel)",
        borderColor: "var(--console-border)",
      }}
    >
      <Icon className="h-3.5 w-3.5" style={{ color: "var(--console-accent)" }} />
      <span
        className="font-telemetry text-xs font-semibold uppercase tracking-wide"
        style={{ color: "var(--console-text)" }}
      >
        {title}
      </span>
    </div>
    <div
      className="p-4 space-y-4"
      style={{ background: "var(--console-panel)" }}
    >
      {children}
    </div>
  </div>
);

// ── Field component ───────────────────────────────────────────────────────

const Field = ({ label, hint, children }) => (
  <div className="grid grid-cols-1 md:grid-cols-3 gap-2 items-start">
    <div>
      <div
        className="font-telemetry text-xs font-semibold"
        style={{ color: "var(--console-text)" }}
      >
        {label}
      </div>
      {hint && (
        <div
          className="font-telemetry text-[10px] mt-0.5"
          style={{ color: "var(--console-muted)" }}
        >
          {hint}
        </div>
      )}
    </div>
    <div className="md:col-span-2">{children}</div>
  </div>
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
      <div
        className="flex items-center justify-center h-32 font-telemetry text-xs"
        style={{ color: "var(--console-muted)" }}
      >
        Loading…
      </div>
    );
  }

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
        <div className="flex items-center gap-2">
          <span
            className="w-0.5 h-4 rounded-full flex-shrink-0"
            style={{ background: "var(--console-accent)" }}
          />
          <span
            className="font-telemetry text-xs font-semibold uppercase tracking-widest"
            style={{ color: "var(--console-text)" }}
          >
            Integrations
          </span>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4 md:p-6">
        <p
          className="font-telemetry text-[11px] mb-5"
          style={{ color: "var(--console-muted)" }}
        >
          Configure SMS/WhatsApp alerts, POS overlay, ANR, dewarp, RAID
          monitoring, and archive scheduling.
        </p>

        <div className="columns-1 lg:columns-2 2xl:columns-3 gap-4">
        {/* ── Twilio SMS ── */}
        <Section icon={MessageSquare} title="SMS Alerts (Twilio)">
          <Field label="Account SID" hint="Starts with AC">
            <ConsoleInput
              value={get("twilio_account_sid")}
              onChange={(v) => set("twilio_account_sid", v)}
              placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
              type="password"
            />
          </Field>
          <Field label="Auth Token">
            <ConsoleInput
              value={get("twilio_auth_token")}
              onChange={(v) => set("twilio_auth_token", v)}
              placeholder="••••••••"
              type="password"
            />
          </Field>
          <Field label="From Number" hint="E.164 format e.g. +12015551234">
            <ConsoleInput
              value={get("twilio_phone_number")}
              onChange={(v) => set("twilio_phone_number", v)}
              placeholder="+12015551234"
            />
          </Field>
          <div className="flex gap-2 pt-1">
            <PrimaryBtn
              onClick={() =>
                saveMany(["twilio_account_sid", "twilio_auth_token", "twilio_phone_number"])
              }
            >
              Save
            </PrimaryBtn>
          </div>
          <Field label="Send test SMS" hint="Enter recipient number to verify config">
            <div className="flex gap-2">
              <ConsoleInput
                value={smsTestTo}
                onChange={setSmsTestTo}
                placeholder="+919876543210"
              />
              <PrimaryBtn onClick={handleSmsTest} loading={smsTestLoading}>
                Send Test
              </PrimaryBtn>
            </div>
          </Field>
        </Section>

        {/* ── Twilio WhatsApp ── */}
        <Section icon={Phone} title="WhatsApp Alerts (Twilio)">
          <p
            className="font-telemetry text-[11px] -mt-1 mb-2"
            style={{ color: "var(--console-muted)" }}
          >
            Requires a Twilio-approved WhatsApp Business number.{" "}
            <a
              href="https://console.twilio.com/us1/develop/sms/whatsapp/learn"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: "var(--console-accent)" }}
            >
              Register at twilio.com/console
            </a>
          </p>
          <Field label="WhatsApp From" hint="Approved business number (E.164)">
            <ConsoleInput
              value={get("twilio_whatsapp_number")}
              onChange={(v) => set("twilio_whatsapp_number", v)}
              placeholder="+14155551234"
            />
          </Field>
          <div className="flex gap-2 pt-1">
            <PrimaryBtn onClick={() => save("twilio_whatsapp_number")}>
              Save
            </PrimaryBtn>
          </div>
          <Field label="Send test message" hint="WhatsApp recipient number">
            <div className="flex gap-2">
              <ConsoleInput
                value={waTestTo}
                onChange={setWaTestTo}
                placeholder="+919876543210"
              />
              <PrimaryBtn onClick={handleWaTest} loading={waTestLoading}>
                Send Test
              </PrimaryBtn>
            </div>
          </Field>
        </Section>

        {/* ── POS / ATM Overlay ── */}
        <Section icon={Cpu} title="POS / ATM Text Overlay">
          <p
            className="font-telemetry text-[11px] -mt-1 mb-2"
            style={{ color: "var(--console-muted)" }}
          >
            Changes take effect on next backend restart (port binding). IP→camera
            mapping is done via{" "}
            <code
              className="px-1 rounded"
              style={{ background: "var(--console-raised)", color: "var(--console-text)" }}
            >
              POS_CAM_&lt;IP&gt;=&lt;camera-uuid&gt;
            </code>{" "}
            env vars.
          </p>
          <Field label="TCP Port" hint="Default 9100 (raw-print). Change to avoid conflict.">
            <ConsoleInput
              value={get("pos_overlay_port", "9100")}
              onChange={(v) => set("pos_overlay_port", v)}
              placeholder="9100"
            />
          </Field>
          <Field
            label="Max Message Size"
            hint="Bytes per message before connection is closed (default 4096)"
          >
            <ConsoleInput
              value={get("pos_max_message_bytes", "4096")}
              onChange={(v) => set("pos_max_message_bytes", v)}
              placeholder="4096"
            />
          </Field>
          <div className="flex gap-2 pt-1">
            <PrimaryBtn
              onClick={() => saveMany(["pos_overlay_port", "pos_max_message_bytes"])}
            >
              Save
            </PrimaryBtn>
          </div>
        </Section>

        {/* ── ANR ── */}
        <Section icon={Database} title="ANR — Automatic Network Replenishment">
          <Field
            label="Debounce (seconds)"
            hint="Camera must be stable online for this long before ANR triggers"
          >
            <ConsoleInput
              value={get("anr_debounce_seconds", "60")}
              onChange={(v) => set("anr_debounce_seconds", v)}
              placeholder="60"
            />
          </Field>
          <Field label="Max Concurrent Jobs" hint="Limits aggregate ANR download bandwidth">
            <ConsoleInput
              value={get("anr_max_concurrent_jobs", "2")}
              onChange={(v) => set("anr_max_concurrent_jobs", v)}
              placeholder="2"
            />
          </Field>
          <div className="flex gap-2 pt-1">
            <PrimaryBtn
              onClick={() => saveMany(["anr_debounce_seconds", "anr_max_concurrent_jobs"])}
            >
              Save
            </PrimaryBtn>
          </div>
        </Section>

        {/* ── Dewarp ── */}
        <Section icon={Eye} title="Dewarp (360° Fisheye)">
          <p
            className="font-telemetry text-[11px] -mt-1 mb-2"
            style={{ color: "var(--console-muted)" }}
          >
            Requires FFmpeg ≥ 4.3 (v360 filter). Without a GPU encoder, output is
            automatically scaled to the fallback resolution.
          </p>
          <Field label="Max Concurrent Jobs" hint="CPU guard — default 4">
            <ConsoleInput
              value={get("dewarp_max_concurrent", "4")}
              onChange={(v) => set("dewarp_max_concurrent", v)}
              placeholder="4"
            />
          </Field>
          <Field label="Fallback Width (px)" hint="Used when no GPU encoder available">
            <ConsoleInput
              value={get("dewarp_fallback_width", "1280")}
              onChange={(v) => set("dewarp_fallback_width", v)}
              placeholder="1280"
            />
          </Field>
          <Field label="Fallback Height (px)">
            <ConsoleInput
              value={get("dewarp_fallback_height", "720")}
              onChange={(v) => set("dewarp_fallback_height", v)}
              placeholder="720"
            />
          </Field>
          <div className="flex gap-2 pt-1">
            <PrimaryBtn
              onClick={() =>
                saveMany([
                  "dewarp_max_concurrent",
                  "dewarp_fallback_width",
                  "dewarp_fallback_height",
                ])
              }
            >
              Save
            </PrimaryBtn>
          </div>
        </Section>

        {/* ── RAID ── */}
        <Section icon={HardDrive} title="RAID Monitoring">
          <p
            className="font-telemetry text-[11px] -mt-1 mb-2"
            style={{ color: "var(--console-muted)" }}
          >
            RAID management requires Linux + mdadm. On macOS/Windows containers
            the RAID service returns{" "}
            <code
              className="px-1 rounded"
              style={{ background: "var(--console-raised)", color: "var(--console-text)" }}
            >
              available: false
            </code>
            .
          </p>
          <Field label="Poll Interval (seconds)" hint="How often to check for degraded arrays">
            <ConsoleInput
              value={get("raid_poll_interval", "60")}
              onChange={(v) => set("raid_poll_interval", v)}
              placeholder="60"
            />
          </Field>
          <div className="flex gap-2 pt-1">
            <PrimaryBtn onClick={() => save("raid_poll_interval")}>
              Save
            </PrimaryBtn>
          </div>
        </Section>

        {/* ── Archive ── */}
        <Section icon={Archive} title="Archive / Scheduled Backup">
          <Field
            label="NAS Max Backoff (seconds)"
            hint="Maximum retry delay when NAS is unreachable (default 960 = 16 min)"
          >
            <ConsoleInput
              value={get("archive_nas_max_backoff", "960")}
              onChange={(v) => set("archive_nas_max_backoff", v)}
              placeholder="960"
            />
          </Field>
          <Field label="Check Interval (seconds)" hint="How often cron schedules are evaluated">
            <ConsoleInput
              value={get("archive_check_interval", "60")}
              onChange={(v) => set("archive_check_interval", v)}
              placeholder="60"
            />
          </Field>
          <div className="flex gap-2 pt-1">
            <PrimaryBtn
              onClick={() =>
                saveMany(["archive_nas_max_backoff", "archive_check_interval"])
              }
            >
              Save
            </PrimaryBtn>
          </div>
        </Section>

        {/* ── Cluster ── */}
        <Section icon={Server} title="Cluster / N+1 Hot Standby">
          <p
            className="font-telemetry text-[11px] -mt-1 mb-2"
            style={{ color: "var(--console-muted)" }}
          >
            These settings take effect on restart. Leader election uses Postgres
            advisory locks — requires PostgreSQL (SQLite is single-node only).
          </p>
          <Field label="Node ID" hint="Unique name for this NVR node (default: hostname)">
            <ConsoleInput
              value={get("nvr_node_id", "")}
              onChange={(v) => set("nvr_node_id", v)}
              placeholder="nvr-node-01"
            />
          </Field>
          <Field
            label="Heartbeat Interval (s)"
            hint="How often each node tries to acquire leadership"
          >
            <ConsoleInput
              value={get("cluster_heartbeat_interval", "5")}
              onChange={(v) => set("cluster_heartbeat_interval", v)}
              placeholder="5"
            />
          </Field>
          <Field
            label="Lease TTL (s)"
            hint="Standby takes over if leader misses this many seconds"
          >
            <ConsoleInput
              value={get("cluster_lease_ttl", "15")}
              onChange={(v) => set("cluster_lease_ttl", v)}
              placeholder="15"
            />
          </Field>
          <div className="flex gap-2 pt-1">
            <PrimaryBtn
              onClick={() =>
                saveMany([
                  "nvr_node_id",
                  "cluster_heartbeat_interval",
                  "cluster_lease_ttl",
                ])
              }
            >
              Save
            </PrimaryBtn>
          </div>
        </Section>
        </div>
      </div>
    </div>
  );
};

export default IntegrationsPage;
