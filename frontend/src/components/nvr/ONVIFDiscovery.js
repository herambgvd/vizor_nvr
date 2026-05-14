// =============================================================================
// ONVIF Discovery Dialog — multi-select bulk-add with per-row snapshot
// =============================================================================
// Layout: max-w-5xl. Each row shows a 160x90 ONVIF snapshot thumbnail
// pulled in the background, full device metadata (manufacturer, model,
// firmware, serial, MAC, capabilities) and an inline editable name.
// Selection is multi via checkboxes. "Add N cameras" probes + creates
// in parallel with bounded concurrency.
// =============================================================================

import React, { useMemo, useState, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Camera,
  Check,
  Eye,
  EyeOff,
  Info,
  KeyRound,
  Loader2,
  Move3D,
  RefreshCw,
  Search,
  Sparkles,
  Wifi,
  X,
} from "lucide-react";

import {
  onvifDiscover,
  onvifProbe,
  onvifSnapshotBlobUrl,
  createCamera,
} from "../../api/cameras";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Checkbox } from "../ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { cn } from "../../lib/utils";
import { toast } from "sonner";


const PROBE_CONCURRENCY = 4;
const SNAPSHOT_CONCURRENCY = 3;


// CIDR helpers ────────────────────────────────────────────────────────────


function normalizeSubnet(raw) {
  const trimmed = (raw || "").trim();
  if (!trimmed) return null;
  const ipv4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\/(\d{1,2}))?$/;
  const m = trimmed.match(ipv4);
  if (!m) return null;
  const octets = [m[1], m[2], m[3], m[4]].map(Number);
  if (octets.some((o) => o < 0 || o > 255)) return null;
  let prefix = m[5] !== undefined ? Number(m[5]) : 24;
  if (prefix < 8 || prefix > 32) prefix = 24;
  if (prefix < 24) prefix = 24;
  if (prefix >= 24) octets[3] = 0;
  return `${octets[0]}.${octets[1]}.${octets[2]}.${octets[3]}/${prefix}`;
}


// Bounded-concurrency parallel runner — keeps Triton/network from being
// hammered when scanning many devices.
async function runBounded(items, fn, concurrency) {
  const queue = [...items];
  const running = new Set();
  const results = [];

  const launch = () => {
    while (running.size < concurrency && queue.length > 0) {
      const item = queue.shift();
      const p = fn(item).then((r) => {
        running.delete(p);
        results.push(r);
      });
      running.add(p);
    }
  };
  launch();
  while (running.size > 0) {
    await Promise.race(running);
    launch();
  }
  return results;
}


// ─────────────────────────────────────────────────────────────────────────


export const ONVIFDiscovery = ({ open, onOpenChange, onAdded }) => {
  const [devices, setDevices] = useState([]);
  const [subnet, setSubnet] = useState("");
  const [credentials, setCredentials] = useState({
    username: "admin",
    password: "",
  });
  const [showGlobalPw, setShowGlobalPw] = useState(false);
  // Per-row password reveal toggles, keyed by rowKey.
  const [showRowPw, setShowRowPw] = useState({});
  const toggleRowPw = (key) =>
    setShowRowPw((s) => ({ ...s, [key]: !s[key] }));

  // Per-row UI state, keyed by `${ip}:${port}`. Holds inline name
  // override, status flag, error string, and snapshot blob URL.
  const [rowState, setRowState] = useState({});
  const [adding, setAdding] = useState(false);

  const rowKey = (d) => `${d.ip}:${d.port || 80}`;
  const setRow = (key, patch) =>
    setRowState((s) => ({ ...s, [key]: { ...(s[key] || {}), ...patch } }));

  // Free snapshot blob URLs on unmount / re-scan to avoid leaking memory.
  useEffect(() => {
    return () => {
      Object.values(rowState).forEach((s) => {
        if (s.snapshotUrl) URL.revokeObjectURL(s.snapshotUrl);
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Discover ───────────────────────────────────────────────────────

  // Pull effective creds for a single row — row override beats the
  // dialog-level defaults. Used by snapshot fetch + reconnect + probe.
  const rowCreds = (key) => {
    const row = rowState[key] || {};
    return {
      username: row.username ?? credentials.username,
      password: row.password ?? credentials.password,
    };
  };

  const fetchSnapshot = async (dev) => {
    const key = rowKey(dev);
    const { username, password } = rowCreds(key);
    let url = null;
    try {
      url = await onvifSnapshotBlobUrl({
        host: dev.ip,
        port: dev.port || 80,
        username,
        password,
      });
    } catch (_e) {
      // Network/transport error — keep placeholder.
      return false;
    }
    if (!url) return false; // 404 / empty body → no snapshot available

    setRowState((s) => {
      const prev = s[key]?.snapshotUrl;
      if (prev) URL.revokeObjectURL(prev);
      return { ...s, [key]: { ...(s[key] || {}), snapshotUrl: url } };
    });
    return true;
  };

  const fetchSnapshots = (list) =>
    runBounded(list, fetchSnapshot, SNAPSHOT_CONCURRENCY);

  const discoverMut = useMutation({
    mutationFn: (params) => onvifDiscover(params),
    onSuccess: (data) => {
      const list = Array.isArray(data) ? data : (data?.devices ?? []);

      // Revoke previously-held snapshot blob URLs before replacing.
      Object.values(rowState).forEach((s) => {
        if (s.snapshotUrl) URL.revokeObjectURL(s.snapshotUrl);
      });

      setDevices(list);
      const initial = {};
      list.forEach((d) => {
        initial[rowKey(d)] = {
          selected: !!d.manufacturer, // pre-select likely cameras
          name: d.name || d.model || `Camera ${d.ip}`,
          status: "idle",
          error: null,
          snapshotUrl: null,
        };
      });
      setRowState(initial);

      if (list.length === 0) {
        toast.info("No devices found on the network");
      } else {
        // Kick off snapshot fetches in background; UI shows placeholders.
        fetchSnapshots(list);
      }
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Discovery failed"),
  });

  const handleDiscover = () => {
    const rawSubnet = subnet.trim();
    const params = { timeout: 5 };
    if (rawSubnet) {
      const cidr = normalizeSubnet(rawSubnet);
      if (!cidr) {
        toast.error(
          "Invalid subnet — use a CIDR like 192.168.1.0/24 or any IP in the LAN",
        );
        return;
      }
      params.subnet = cidr;
    }
    if (credentials.username) params.username = credentials.username;
    if (credentials.password) params.password = credentials.password;
    discoverMut.mutate(params);
  };

  // Re-probe a single row using its current per-row credentials. Updates
  // the device metadata in-place and refetches the snapshot. Used when
  // the operator typed the camera's real password into the row fields.
  const handleReconnect = async (dev) => {
    const key = rowKey(dev);
    const { username, password } = rowCreds(key);
    if (!password) {
      toast.error("Enter the camera password before reconnecting");
      return;
    }
    setRow(key, { status: "probing", error: null });
    try {
      const probed = await onvifProbe({
        host: dev.ip,
        port: dev.port || 80,
        username,
        password,
      });

      // Merge probe result into the device row so badges + metadata update.
      setDevices((curr) =>
        curr.map((d) =>
          rowKey(d) === key
            ? {
                ...d,
                manufacturer: probed?.manufacturer ?? d.manufacturer,
                model: probed?.model ?? d.model,
                name: probed?.name ?? d.name,
                firmware: probed?.firmware ?? d.firmware,
                serial_number: probed?.serial_number ?? d.serial_number,
                hardware_id: probed?.hardware_id ?? d.hardware_id,
                mac: probed?.mac ?? d.mac,
                has_ptz: probed?.has_ptz ?? d.has_ptz,
                has_analytics: probed?.has_analytics ?? d.has_analytics,
                has_events: probed?.has_events ?? d.has_events,
                has_imaging: probed?.has_imaging ?? d.has_imaging,
              }
            : d,
        ),
      );

      setRow(key, {
        status: "idle",
        // Bump name to discovered model when row name still placeholder.
        name:
          rowState[key]?.name &&
          !rowState[key].name.startsWith("Camera ") &&
          rowState[key].name !== ""
            ? rowState[key].name
            : probed?.name || probed?.model || rowState[key]?.name,
      });

      // Refresh snapshot with the new creds.
      const ok = await fetchSnapshot(dev);
      if (ok) {
        toast.success(`Reconnected ${dev.ip}`);
      } else {
        toast.info(`Reconnected ${dev.ip} — snapshot not available`);
      }
    } catch (e) {
      setRow(key, {
        status: "error",
        error: e.response?.data?.detail || "Reconnect failed",
      });
      toast.error(`Reconnect failed: ${e.response?.data?.detail || e.message}`);
    }
  };

  // ── Selection ──────────────────────────────────────────────────────

  const selectedCount = useMemo(
    () => Object.values(rowState).filter((s) => s.selected).length,
    [rowState],
  );

  const allSelected = devices.length > 0 && selectedCount === devices.length;

  const toggleAll = (value) => {
    setRowState((s) => {
      const next = { ...s };
      devices.forEach((d) => {
        const k = rowKey(d);
        next[k] = { ...(next[k] || {}), selected: value };
      });
      return next;
    });
  };

  // ── Bulk add ───────────────────────────────────────────────────────

  const probeAndCreate = async (dev) => {
    const key = rowKey(dev);
    const row = rowState[key] || {};
    const { username, password } = rowCreds(key);
    setRow(key, { status: "probing", error: null });
    let probed = null;
    try {
      probed = await onvifProbe({
        host: dev.ip,
        port: dev.port || 80,
        username,
        password,
      });
    } catch (e) {
      setRow(key, {
        status: "error",
        error: e.response?.data?.detail || "Probe failed",
      });
      return { ok: false };
    }

    const streamUrl = probed?.stream_uri || probed?.main_stream_url || null;
    if (!streamUrl) {
      setRow(key, {
        status: "error",
        error: "Camera did not return a stream URL (check credentials)",
      });
      return { ok: false };
    }

    setRow(key, { status: "adding" });
    const body = {
      name: row.name || dev.name || dev.model || `Camera ${dev.ip}`,
      main_stream_url: streamUrl,
      sub_stream_url: probed?.sub_stream_url || null,
      description:
        `${dev.manufacturer || ""} ${dev.model || ""}${
          probed?.firmware ? ` · FW ${probed.firmware}` : ""
        }`.trim(),
      is_enabled: true,
      recording_mode: "manual",
      onvif_host: dev.ip,
      onvif_port: dev.port || 80,
      onvif_username: username || null,
      onvif_password: password || null,
    };
    try {
      await createCamera(body);
      setRow(key, { status: "done" });
      return { ok: true };
    } catch (e) {
      const detail = e.response?.data?.detail;
      setRow(key, {
        status: "error",
        error: Array.isArray(detail)
          ? detail.map((d) => d.msg).join("; ")
          : detail || "Create failed",
      });
      return { ok: false };
    }
  };

  const handleBulkAdd = async () => {
    const selected = devices.filter((d) => rowState[rowKey(d)]?.selected);
    if (selected.length === 0) {
      toast.error("Select at least one camera");
      return;
    }
    setAdding(true);
    const results = await runBounded(selected, probeAndCreate, PROBE_CONCURRENCY);
    setAdding(false);

    const okCount = results.filter((r) => r.ok).length;
    const failCount = results.length - okCount;
    if (okCount > 0) {
      toast.success(
        `Added ${okCount} ${okCount === 1 ? "camera" : "cameras"}${
          failCount > 0 ? ` · ${failCount} failed` : ""
        }`,
      );
      onAdded?.(okCount);
    } else if (failCount > 0) {
      toast.error(`All ${failCount} camera adds failed — see rows for detail`);
    }
    // Auto-close whenever at least one camera was added. Previously
    // we only closed on full success — but with partial failures
    // (camera-limit / unreachable rows) operators saw the success
    // toast while the modal stayed open, looking stuck. Failed rows
    // are already marked with an inline error chip on the row, so the
    // user doesn't lose that context by closing.
    if (okCount > 0) {
      setTimeout(() => onOpenChange(false), 800);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-5xl max-h-[92vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wifi className="h-5 w-5" />
            ONVIF Discovery
          </DialogTitle>
          <DialogDescription>
            Scan the LAN, select one or many cameras, and add them in a
            single click.
          </DialogDescription>
        </DialogHeader>

        {/* Credentials + subnet */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <Label className="text-xs">ONVIF Username</Label>
            <Input
              value={credentials.username}
              onChange={(e) =>
                setCredentials((c) => ({ ...c, username: e.target.value }))
              }
              placeholder="admin"
            />
          </div>
          <div>
            <Label className="text-xs">ONVIF Password</Label>
            <div className="relative">
              <Input
                type={showGlobalPw ? "text" : "password"}
                value={credentials.password}
                onChange={(e) =>
                  setCredentials((c) => ({ ...c, password: e.target.value }))
                }
                placeholder="••••••"
                className="pr-9"
              />
              <button
                type="button"
                onClick={() => setShowGlobalPw((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-zinc-200"
                title={showGlobalPw ? "Hide password" : "Show password"}
              >
                {showGlobalPw ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>
          <div>
            <Label className="text-xs">Subnet (CIDR, optional)</Label>
            <Input
              value={subnet}
              onChange={(e) => setSubnet(e.target.value)}
              placeholder="192.168.1.0/24"
            />
          </div>
        </div>

        {/* Scan button */}
        <Button
          onClick={handleDiscover}
          disabled={discoverMut.isPending}
          className="w-full"
        >
          {discoverMut.isPending ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Scanning…
            </>
          ) : (
            <>
              <Search className="h-4 w-4 mr-2" />
              Scan Network
            </>
          )}
        </Button>

        {/* Results */}
        <div className="flex-1 overflow-y-auto -mx-2 px-2">
          {devices.length > 0 ? (
            <>
              <div className="flex items-center justify-between sticky top-0 bg-background py-2 z-10">
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={allSelected}
                    onCheckedChange={(v) => toggleAll(!!v)}
                  />
                  <span className="text-xs text-zinc-400">
                    {selectedCount} of {devices.length} selected
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  Pre-selected: rows with manufacturer info
                </p>
              </div>

              <div className="space-y-2">
                {devices.map((dev) => {
                  const key = rowKey(dev);
                  const row = rowState[key] || {};
                  return (
                    <div
                      key={key}
                      className={cn(
                        "p-3 rounded-lg border transition-colors",
                        row.selected
                          ? "border-blue-500/50 bg-blue-500/[0.06]"
                          : "border-border bg-card/40",
                      )}
                    >
                      <div className="flex items-start gap-3">
                        <Checkbox
                          checked={!!row.selected}
                          onCheckedChange={(v) =>
                            setRow(key, { selected: !!v })
                          }
                          className="mt-1"
                        />

                        {/* Snapshot thumbnail */}
                        <div className="w-40 h-24 rounded bg-black/40 border border-border flex-shrink-0 overflow-hidden flex items-center justify-center">
                          {row.snapshotUrl ? (
                            <img
                              src={row.snapshotUrl}
                              alt={`${dev.ip} preview`}
                              className="w-full h-full object-cover"
                            />
                          ) : (
                            <Camera className="h-6 w-6 text-zinc-700" />
                          )}
                        </div>

                        {/* Editable name + per-row credentials + metadata */}
                        <div className="flex-1 min-w-0 space-y-2">
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                            <div className="md:col-span-1">
                              <Label className="text-[10px] text-muted-foreground uppercase">
                                Camera Name
                              </Label>
                              <Input
                                value={row.name || ""}
                                onChange={(e) =>
                                  setRow(key, { name: e.target.value })
                                }
                                className="h-8 text-sm"
                                placeholder="Camera name"
                              />
                            </div>
                            <div>
                              <Label className="text-[10px] text-muted-foreground uppercase flex items-center gap-1">
                                <KeyRound className="h-3 w-3" />
                                Username
                              </Label>
                              <Input
                                value={
                                  row.username !== undefined
                                    ? row.username
                                    : credentials.username
                                }
                                onChange={(e) =>
                                  setRow(key, { username: e.target.value })
                                }
                                className="h-8 text-sm font-mono"
                                placeholder="admin"
                              />
                            </div>
                            <div>
                              <Label className="text-[10px] text-muted-foreground uppercase flex items-center justify-between gap-2">
                                <span className="flex items-center gap-1">
                                  <KeyRound className="h-3 w-3" />
                                  Password
                                </span>
                                <button
                                  type="button"
                                  onClick={() => handleReconnect(dev)}
                                  disabled={row.status === "probing"}
                                  className="text-blue-400 hover:text-blue-300 normal-case text-[10px] flex items-center gap-1 disabled:opacity-50"
                                  title="Reconnect with these credentials"
                                >
                                  <RefreshCw
                                    className={cn(
                                      "h-3 w-3",
                                      row.status === "probing" && "animate-spin",
                                    )}
                                  />
                                  Reconnect
                                </button>
                              </Label>
                              <div className="relative">
                                <Input
                                  type={showRowPw[key] ? "text" : "password"}
                                  value={
                                    row.password !== undefined
                                      ? row.password
                                      : credentials.password
                                  }
                                  onChange={(e) =>
                                    setRow(key, { password: e.target.value })
                                  }
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") handleReconnect(dev);
                                  }}
                                  className="h-8 text-sm pr-8"
                                  placeholder="••••••"
                                />
                                <button
                                  type="button"
                                  onClick={() => toggleRowPw(key)}
                                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-zinc-200"
                                  title={
                                    showRowPw[key]
                                      ? "Hide password"
                                      : "Show password"
                                  }
                                >
                                  {showRowPw[key] ? (
                                    <EyeOff className="h-3.5 w-3.5" />
                                  ) : (
                                    <Eye className="h-3.5 w-3.5" />
                                  )}
                                </button>
                              </div>
                            </div>
                          </div>

                          {/* Metadata grid */}
                          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-3 gap-y-1 text-[11px]">
                            <MetaCell label="Address" value={`${dev.ip}:${dev.port || 80}`} mono />
                            <MetaCell label="Manufacturer" value={dev.manufacturer} />
                            <MetaCell label="Model" value={dev.model} />
                            <MetaCell label="Firmware" value={dev.firmware} />
                            <MetaCell label="Serial" value={dev.serial_number} mono />
                            <MetaCell label="MAC" value={dev.mac} mono />
                          </div>

                          {/* Capability badges + status */}
                          <div className="flex items-center justify-between gap-2 flex-wrap">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {dev.manufacturer ? (
                                <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 text-[10px]">
                                  ONVIF verified
                                </span>
                              ) : (
                                <span className="px-2 py-0.5 rounded bg-zinc-500/10 text-zinc-400 border border-zinc-500/20 text-[10px]">
                                  Unverified
                                </span>
                              )}
                              {dev.has_ptz ? (
                                <span className="px-2 py-0.5 rounded bg-purple-500/10 text-purple-300 border border-purple-500/20 text-[10px] flex items-center gap-1">
                                  <Move3D className="h-3 w-3" />
                                  PTZ
                                </span>
                              ) : null}
                              {dev.has_analytics ? (
                                <span className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-300 border border-blue-500/20 text-[10px] flex items-center gap-1">
                                  <Sparkles className="h-3 w-3" />
                                  Analytics
                                </span>
                              ) : null}
                              {dev.has_events ? (
                                <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20 text-[10px]">
                                  Events
                                </span>
                              ) : null}
                              {dev.has_imaging ? (
                                <span className="px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 text-[10px]">
                                  Imaging
                                </span>
                              ) : null}
                            </div>

                            <div className="flex items-center gap-2 text-[11px]">
                              {row.status === "probing" && (
                                <span className="flex items-center gap-1 text-yellow-400">
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                  probing
                                </span>
                              )}
                              {row.status === "adding" && (
                                <span className="flex items-center gap-1 text-blue-400">
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                  adding
                                </span>
                              )}
                              {row.status === "done" && (
                                <span className="flex items-center gap-1 text-emerald-400">
                                  <Check className="h-3 w-3" />
                                  added
                                </span>
                              )}
                              {row.status === "error" && (
                                <span
                                  className="flex items-center gap-1 text-rose-400"
                                  title={row.error}
                                >
                                  <X className="h-3 w-3" />
                                  failed
                                </span>
                              )}
                            </div>
                          </div>

                          {row.status === "error" && row.error && (
                            <div className="text-[11px] text-rose-300/80">
                              {row.error}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            !discoverMut.isPending && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground py-8 justify-center">
                <Info className="h-4 w-4" />
                Press "Scan Network" to discover cameras
              </div>
            )
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleBulkAdd}
            disabled={adding || selectedCount === 0}
          >
            {adding ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Adding {selectedCount}…
              </>
            ) : (
              `Add ${selectedCount || ""} ${
                selectedCount === 1 ? "Camera" : "Cameras"
              }`.trim()
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};


// Small key-value cell shown in the per-row metadata grid. Renders nothing
// when the value is null so empty fields don't show up as "—".
function MetaCell({ label, value, mono }) {
  if (!value) return null;
  return (
    <div className="min-w-0">
      <span className="text-muted-foreground">{label}: </span>
      <span
        className={cn(
          "text-zinc-300",
          mono && "font-mono",
        )}
      >
        {value}
      </span>
    </div>
  );
}


export default ONVIFDiscovery;
