// =============================================================================
// TimeSettingsPage — /settings/time
// NTP server, timezone selector, push time to cameras. Admin only.
// =============================================================================

import React, { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Clock, RefreshCw, Radio, Wifi } from "lucide-react";
import { toast } from "sonner";
import { getSystemTime, setSystemTime, pushTimeToCameras } from "../../api/system";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";

// Timezones from browser Intl
const TZ_LIST = (() => {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC", "America/New_York", "America/Los_Angeles", "Europe/London",
            "Europe/Berlin", "Asia/Kolkata", "Asia/Tokyo", "Australia/Sydney"];
  }
})();

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

  // Seed form from server data
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
    onError: (e) => toast.error(e?.response?.data?.detail || "Save failed"),
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
    onError: (e) => toast.error(e?.response?.data?.detail || "Push failed"),
  });

  const mark = () => setDirty(true);

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-2xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Time &amp; NTP Settings
        </h2>
        <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isLoading}>
          <RefreshCw className={cn("h-4 w-4 mr-1.5", isLoading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Live clock card */}
      <div className="rounded-lg border border-border bg-card/40 p-5 flex items-center gap-4">
        <div className="p-2.5 rounded-md bg-teal-500/15">
          <Clock className="h-5 w-5 text-teal-300" />
        </div>
        <div>
          <p className="text-xs text-muted-foreground uppercase tracking-wider mb-0.5">
            NVR Current Time (UTC)
          </p>
          <p className="text-lg font-mono tabular-nums text-teal-200">
            {data?.now_utc
              ? new Date(data.now_utc).toUTCString()
              : "—"}
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            NTP:{" "}
            <span
              className={
                data?.ntp_synced === true
                  ? "text-teal-400"
                  : data?.ntp_synced === false
                    ? "text-rose-400"
                    : "text-zinc-400"
              }
            >
              {data?.ntp_synced === true
                ? "Synchronized"
                : data?.ntp_synced === false
                  ? "Not synchronized"
                  : "Unknown"}
            </span>
          </p>
        </div>
      </div>

      {/* Timezone */}
      <div className="rounded-lg border border-border bg-card/40 p-5 space-y-4">
        <h3 className="text-sm font-semibold">Timezone</h3>
        <div>
          <label className="block text-xs text-muted-foreground mb-1.5">
            Display timezone (NVR logs + UI)
          </label>
          <select
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            value={timezone}
            onChange={(e) => { setTimezone(e.target.value); mark(); }}
          >
            {TZ_LIST.map((tz) => (
              <option key={tz} value={tz}>{tz}</option>
            ))}
          </select>
        </div>
      </div>

      {/* NTP / Manual */}
      <div className="rounded-lg border border-border bg-card/40 p-5 space-y-4">
        <h3 className="text-sm font-semibold">Time Source</h3>

        {/* Toggle */}
        <div className="flex gap-2">
          <button
            onClick={() => { setUseNtp(true); mark(); }}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
              useNtp
                ? "bg-teal-500/20 text-teal-300 border border-teal-500/40"
                : "text-zinc-400 border border-border hover:text-white",
            )}
          >
            <Wifi className="h-3.5 w-3.5" /> NTP (recommended)
          </button>
          <button
            onClick={() => { setUseNtp(false); mark(); }}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
              !useNtp
                ? "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                : "text-zinc-400 border border-border hover:text-white",
            )}
          >
            <Radio className="h-3.5 w-3.5" /> Manual
          </button>
        </div>

        {useNtp ? (
          <div>
            <label className="block text-xs text-muted-foreground mb-1.5">
              NTP server
            </label>
            <input
              type="text"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
              value={ntpServer}
              onChange={(e) => { setNtpServer(e.target.value); mark(); }}
              placeholder="pool.ntp.org"
            />
          </div>
        ) : (
          <div>
            <label className="block text-xs text-muted-foreground mb-1.5">
              Manual UTC time (ISO-8601)
            </label>
            <input
              type="datetime-local"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
              value={manualUtc}
              onChange={(e) => { setManualUtc(e.target.value); mark(); }}
            />
            <p className="text-[11px] text-amber-400/80 mt-1">
              Note: Setting system clock requires the backend container to run
              with sufficient host privileges.
            </p>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <Button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending || !dirty}
        >
          {saveMutation.isPending ? (
            <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
          ) : null}
          Save Settings
        </Button>
        <Button
          variant="outline"
          onClick={() => pushMutation.mutate()}
          disabled={pushMutation.isPending}
        >
          {pushMutation.isPending ? (
            <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
          ) : null}
          Push Time to All Cameras
        </Button>
      </div>

      {/* Push results */}
      {pushMutation.data && (
        <div className="rounded-lg border border-border bg-card/40 p-4 text-sm space-y-1">
          <p className="text-teal-300 font-medium">
            Pushed to {pushMutation.data.pushed} cameras
          </p>
          {pushMutation.data.failed?.map((f) => (
            <p key={f.camera_id} className="text-rose-400 text-xs font-mono">
              Failed: {f.name} ({f.host})
            </p>
          ))}
        </div>
      )}
    </div>
  );
};

export default TimeSettingsPage;
