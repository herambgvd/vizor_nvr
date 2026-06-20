// =============================================================================
// TimeSettingsPage — /settings/time
// NTP server, timezone selector, push time to cameras. Admin only.
// =============================================================================

import React, { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Clock, RefreshCw, Radio, Wifi } from "lucide-react";
import { toast } from "sonner";
import { getSystemTime, setSystemTime, pushTimeToCameras } from "../../api/system";
import SearchableSelect from "../../components/ui/searchable-select";
import { friendlyError } from "../../lib/utils";

// ─── Timezone list ────────────────────────────────────────────────────────────

const TZ_LIST = (() => {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return [
      "UTC",
      "America/New_York",
      "America/Los_Angeles",
      "Europe/London",
      "Europe/Berlin",
      "Asia/Kolkata",
      "Asia/Tokyo",
      "Australia/Sydney",
    ];
  }
})();

// ─── Shared primitives ────────────────────────────────────────────────────────

const PrimaryBtn = ({ children, disabled, onClick, type = "button" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className="inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] font-semibold uppercase tracking-wide transition-opacity disabled:opacity-50"
    style={{ background: "var(--console-accent)", color: "#06231f" }}
  >
    {children}
  </button>
);

const SecondaryBtn = ({ children, disabled, onClick, type = "button" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className="inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] border transition-colors hover:bg-white/5 disabled:opacity-50"
    style={{
      background: "var(--console-raised)",
      borderColor: "var(--console-border)",
      color: "var(--console-muted)",
    }}
  >
    {children}
  </button>
);

const ConsoleCard = ({ children, className = "" }) => (
  <div
    className={`rounded ${className}`}
    style={{
      background: "var(--console-panel)",
      border: "1px solid var(--console-border)",
    }}
  >
    {children}
  </div>
);

const CardHeader = ({ children }) => (
  <div
    className="flex items-center gap-2 px-4 py-3 border-b"
    style={{ borderColor: "var(--console-border)" }}
  >
    {children}
  </div>
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

const FieldLabel = ({ children }) => (
  <label
    className="block font-telemetry text-[10px] uppercase tracking-wide mb-1"
    style={{ color: "var(--console-muted)" }}
  >
    {children}
  </label>
);

// Settings endpoints return short, operator-safe validation strings in
// `detail` (e.g. "Enter a valid NTP server hostname"). Surface those as-is,
// but fall back to friendlyError for 5xx / network / validation-array faults
// so no raw backend internals ever reach the operator.
const settingsError = (e, fallback) => {
  const detail = e?.response?.data?.detail;
  const status = e?.response?.status;
  if (status === 400 && typeof detail === "string" && detail) return detail;
  return friendlyError(e, fallback);
};

// ─── Main Page ────────────────────────────────────────────────────────────────

const TimeSettingsPage = () => {
  const qc = useQueryClient();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["system-time"],
    queryFn: getSystemTime,
    refetchInterval: 10_000,
  });

  const [timezone, setTimezone] = useState("UTC");
  const [ntpServer, setNtpServer] = useState("pool.ntp.org");
  const [useNtp, setUseNtp] = useState(true);
  const [manualUtc, setManualUtc] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!data) return;
    setTimezone(data.timezone || "UTC");
    setNtpServer(data.ntp_server || "pool.ntp.org");
    setUseNtp(!!data.ntp_server);
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: () =>
      setSystemTime({
        timezone,
        ntp_server: useNtp ? ntpServer : null,
        manual_utc: !useNtp && manualUtc ? manualUtc : null,
      }),
    onSuccess: () => {
      toast.success("Time settings saved");
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["system-time"] });
    },
    onError: (e) => toast.error(settingsError(e, "Couldn't save time settings.")),
  });

  const pushMutation = useMutation({
    mutationFn: pushTimeToCameras,
    onSuccess: (res) => {
      const n = res.pushed ?? 0;
      const f = res.failed?.length ?? 0;
      if (f > 0) {
        toast.warning(`Pushed to ${n} cameras, ${f} failed`);
      } else {
        toast.success(`Time pushed to ${n} camera${n !== 1 ? "s" : ""}`);
      }
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't push time to cameras.")),
  });

  const mark = () => setDirty(true);

  const ntpSyncColor =
    data?.ntp_synced === true
      ? "var(--console-online)"
      : data?.ntp_synced === false
      ? "var(--console-rec)"
      : "var(--console-muted)";

  const ntpSyncLabel =
    data?.ntp_synced === true
      ? "Synchronized"
      : data?.ntp_synced === false
      ? "Not synchronized"
      : "Unknown";

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
            Time &amp; NTP
          </span>
        </div>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isLoading}
          className="inline-flex items-center h-[28px] px-2 rounded font-telemetry text-[11px] border transition-colors hover:bg-white/5 disabled:opacity-50"
          style={{
            background: "transparent",
            borderColor: "var(--console-border)",
            color: "var(--console-muted)",
          }}
        >
          <RefreshCw
            className={`h-3.5 w-3.5 mr-1.5 ${isLoading ? "animate-spin" : ""}`}
          />
          Refresh
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4 md:p-6 space-y-4">

        {/* Live clock card */}
        <ConsoleCard>
          <div className="flex items-center gap-4 p-4">
            <div
              className="p-2.5 rounded"
              style={{ background: "rgba(20,184,166,0.12)" }}
            >
              <Clock className="h-5 w-5" style={{ color: "var(--console-accent)" }} />
            </div>
            <div>
              <p
                className="font-telemetry text-[10px] uppercase tracking-widest mb-0.5"
                style={{ color: "var(--console-muted)" }}
              >
                NVR Current Time {data?.tz_abbrev ? `(${data.tz_abbrev})` : "(UTC)"}
              </p>
              <p
                className="font-telemetry text-sm tabular-nums"
                style={{ color: "var(--console-accent)" }}
              >
                {data?.now_local || data?.now_utc
                  ? new Date(data.now_local || data.now_utc).toLocaleString("en-GB", {
                      timeZone: data?.timezone && data.timezone !== "UTC" ? data.timezone : "UTC",
                      weekday: "short", day: "2-digit", month: "short", year: "numeric",
                      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
                    })
                  : "—"}
              </p>
              <p
                className="font-telemetry text-[11px] mt-0.5"
                style={{ color: "var(--console-muted)" }}
              >
                NTP:{" "}
                <span style={{ color: ntpSyncColor }}>{ntpSyncLabel}</span>
              </p>
            </div>
          </div>
        </ConsoleCard>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
        {/* Timezone */}
        <ConsoleCard>
          <CardHeader>
            <span
              className="font-telemetry text-xs font-semibold uppercase tracking-wide"
              style={{ color: "var(--console-text)" }}
            >
              Timezone
            </span>
          </CardHeader>
          <div className="p-4">
            <FieldLabel>Display timezone (NVR logs + UI)</FieldLabel>
            <SearchableSelect
              value={timezone}
              onChange={(v) => {
                setTimezone(v);
                mark();
              }}
              options={TZ_LIST}
              placeholder="Select timezone…"
              searchPlaceholder="Search timezone…"
              emptyText="No matching timezone"
            />
          </div>
        </ConsoleCard>

        {/* NTP / Manual */}
        <ConsoleCard>
          <CardHeader>
            <span
              className="font-telemetry text-xs font-semibold uppercase tracking-wide"
              style={{ color: "var(--console-text)" }}
            >
              Time Source
            </span>
          </CardHeader>
          <div className="p-4 space-y-4">
            {/* Toggle */}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => {
                  setUseNtp(true);
                  mark();
                }}
                className="inline-flex items-center gap-1.5 h-[28px] px-3 rounded font-telemetry text-[11px] border transition-colors"
                style={
                  useNtp
                    ? {
                        background: "rgba(20,184,166,0.12)",
                        borderColor: "rgba(20,184,166,0.4)",
                        color: "var(--console-accent)",
                      }
                    : {
                        background: "var(--console-raised)",
                        borderColor: "var(--console-border)",
                        color: "var(--console-muted)",
                      }
                }
              >
                <Wifi className="h-3.5 w-3.5" /> NTP (recommended)
              </button>
              <button
                type="button"
                onClick={() => {
                  setUseNtp(false);
                  mark();
                }}
                className="inline-flex items-center gap-1.5 h-[28px] px-3 rounded font-telemetry text-[11px] border transition-colors"
                style={
                  !useNtp
                    ? {
                        background: "rgba(245,158,11,0.12)",
                        borderColor: "rgba(245,158,11,0.4)",
                        color: "var(--console-alarm)",
                      }
                    : {
                        background: "var(--console-raised)",
                        borderColor: "var(--console-border)",
                        color: "var(--console-muted)",
                      }
                }
              >
                <Radio className="h-3.5 w-3.5" /> Manual
              </button>
            </div>

            {useNtp ? (
              <div>
                <FieldLabel>NTP server</FieldLabel>
                <ConsoleInput
                  type="text"
                  value={ntpServer}
                  onChange={(e) => {
                    setNtpServer(e.target.value);
                    mark();
                  }}
                  placeholder="pool.ntp.org"
                />
              </div>
            ) : (
              <div>
                <FieldLabel>Manual UTC time (ISO-8601)</FieldLabel>
                <ConsoleInput
                  type="datetime-local"
                  value={manualUtc}
                  onChange={(e) => {
                    setManualUtc(e.target.value);
                    mark();
                  }}
                />
                <p
                  className="font-telemetry text-[10px] mt-1"
                  style={{ color: "var(--console-alarm)" }}
                >
                  Note: Setting system clock requires the backend container to
                  run with sufficient host privileges.
                </p>
              </div>
            )}
          </div>
        </ConsoleCard>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-3">
          <PrimaryBtn
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !dirty}
          >
            {saveMutation.isPending && (
              <RefreshCw className="h-3.5 w-3.5 mr-1.5 animate-spin" />
            )}
            Save Settings
          </PrimaryBtn>
          <SecondaryBtn
            onClick={() => pushMutation.mutate()}
            disabled={pushMutation.isPending}
          >
            {pushMutation.isPending && (
              <RefreshCw className="h-3.5 w-3.5 mr-1.5 animate-spin" />
            )}
            Push Time to All Cameras
          </SecondaryBtn>
        </div>

        {/* Push results */}
        {pushMutation.data && (
          <ConsoleCard>
            <div className="p-4 space-y-1">
              <p
                className="font-telemetry text-xs font-semibold"
                style={{ color: "var(--console-online)" }}
              >
                Pushed to {pushMutation.data.pushed} cameras
              </p>
              {pushMutation.data.failed?.map((f) => (
                <p
                  key={f.camera_id}
                  className="font-telemetry text-[11px]"
                  style={{ color: "var(--console-rec)" }}
                >
                  Failed: {f.name} ({f.host})
                </p>
              ))}
            </div>
          </ConsoleCard>
        )}
      </div>
    </div>
  );
};

export default TimeSettingsPage;
