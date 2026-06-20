// =============================================================================
// Events — Historical events console (console-themed master-detail)
// =============================================================================
// Left panel: filterable/searchable scrollable event list with severity accents.
// Right panel: detail card with snapshot thumbnail, metadata, and actions.
// All existing functionality preserved: filters, ack, false-alarm, bulk-delete,
// CSV export, pagination, live-view dialog, jump-to-playback.
// =============================================================================

import React, { useState, useMemo, useEffect, useCallback } from "react";
import {
  useQuery,
  useMutation,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Bell,
  BellOff,
  Check,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  Download,
  Filter,
  Search,
  Shield,
  XCircle,
  Activity,
  Video,
  VideoOff,
  Eye,
  Trash2,
  PlayCircle,
  RefreshCw,
} from "lucide-react";
import {
  getEvents,
  getEventStats,
  getUnacknowledgedCount,
  acknowledgeEvent,
  acknowledgeAllEvents,
  markFalseAlarm,
  exportEventsCSV,
  deleteEvent,
  bulkDeleteEvents,
} from "../api/events";
import { getAllCameras, getLatestSnapshot } from "../api/cameras";
import { WebRTCPlayer } from "../components/nvr/WebRTCPlayer";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Textarea } from "../components/ui/textarea";
import { cn, friendlyError } from "../lib/utils";
import { eventTypeLabel } from "../lib/eventLabels";
import { toast } from "sonner";
import { format } from "date-fns";

// ─── Constants ────────────────────────────────────────────────────────────────

const PAGE_SIZE = 50;

// Filter dropdown options. Labels come from the shared eventTypeLabel() map so
// they stay in sync with the rest of the app; icons are per-group.
const EVENT_TYPES = [
  { value: "motion_detected", icon: Activity },
  { value: "video_loss", icon: VideoOff },
  { value: "camera_tamper", icon: Shield },
  { value: "camera_offline", icon: VideoOff },
  { value: "camera_online", icon: Video },
  { value: "camera_credentials_invalid", icon: VideoOff },
  { value: "recording_error", icon: AlertTriangle },
  { value: "recording_gap", icon: AlertTriangle },
  { value: "storage_low", icon: AlertTriangle },
  { value: "storage_critical", icon: XCircle },
  { value: "disk_full", icon: XCircle },
  { value: "disk_warning", icon: AlertTriangle },
  { value: "bandwidth_alert", icon: Activity },
  { value: "system_error", icon: XCircle },
  { value: "cluster_failover", icon: AlertTriangle },
  { value: "line_crossing", icon: Shield },
  { value: "zone_intrusion", icon: Shield },
  { value: "face_recognized", icon: Eye },
  { value: "face_unknown", icon: Eye },
  { value: "ppe_violation", icon: Shield },
  { value: "crowd", icon: Activity },
  { value: "manual", icon: Bell },
].map((t) => ({ ...t, label: eventTypeLabel(t.value) }));

// Severity → accent-bar color (left edge of list row) + badge style
const SEVERITY_CONFIG = {
  info: {
    bar: "bg-blue-500",
    badge: "bg-blue-500/15 text-blue-300 border border-blue-500/30",
    label: "Info",
  },
  warning: {
    bar: "bg-amber-500",
    badge: "bg-amber-500/15 text-amber-300 border border-amber-500/30",
    label: "Warning",
  },
  critical: {
    bar: "bg-rose-500",
    badge: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
    label: "Critical",
  },
  alarm: {
    bar: "bg-rose-600",
    badge: "bg-rose-500/25 text-rose-200 border border-rose-500/50",
    label: "Alarm",
  },
};

const inputStyle = {
  background: "var(--console-raised)",
  borderColor: "var(--console-border)",
  color: "var(--console-text)",
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getEventIcon(type) {
  const et = EVENT_TYPES.find((e) => e.value === type);
  return et ? et.icon : Bell;
}

function severityOf(s) {
  return SEVERITY_CONFIG[s] || SEVERITY_CONFIG.info;
}

// ─── Sub-components ──────────────────────────────────────────────────────────

/** Compact label used inside the filter bar */
const FilterLabel = ({ children }) => (
  <span className="text-[10px] font-medium uppercase tracking-widest mb-0.5 block" style={{ color: "var(--console-muted)" }}>
    {children}
  </span>
);

/** Severity stat chip shown in the header */
const SeverityChip = ({ label, count, barClass }) => (
  <div
    className="flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-telemetry"
    style={{ background: "var(--console-raised)", borderColor: "var(--console-border)" }}
  >
    <span className={cn("h-2 w-2 rounded-sm flex-shrink-0", barClass)} />
    <span style={{ color: "var(--console-muted)" }}>{label}</span>
    <span className="font-medium" style={{ color: "var(--console-text)" }}>{count}</span>
  </div>
);

// ─── Main component ───────────────────────────────────────────────────────────

const Events = () => {
  const qc = useQueryClient();
  const navigate = useNavigate();

  // ── Filter state ─────────────────────────────────────────────────────────
  const [page, setPage] = useState(1);
  const [eventType, setEventType] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [cameraId, setCameraId] = useState("all");
  const [acknowledged, setAcknowledged] = useState("all");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  // ── Selection & detail ────────────────────────────────────────────────────
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [ackNote, setAckNote] = useState("");
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [liveOpen, setLiveOpen] = useState(false);

  // ── Snapshot state for detail panel ───────────────────────────────────────
  const [recSnapUrl, setRecSnapUrl] = useState(null);
  const [snapLoading, setSnapLoading] = useState(false);

  // ── Build query params ─────────────────────────────────────────────────────
  const params = useMemo(() => {
    const p = { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE };
    if (eventType !== "all") p.event_type = eventType;
    if (severity !== "all") p.severity = severity;
    if (cameraId !== "all") p.camera_id = cameraId;
    if (acknowledged !== "all") p.acknowledged = acknowledged === "true";
    if (startDate) p.start_date = startDate;
    if (endDate) p.end_date = endDate;
    return p;
  }, [page, eventType, severity, cameraId, acknowledged, startDate, endDate]);

  // ── Queries ───────────────────────────────────────────────────────────────
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["events", params],
    queryFn: () => getEvents(params),
    placeholderData: keepPreviousData,
    refetchInterval: 10000,
  });

  const { data: stats } = useQuery({
    queryKey: ["event-stats"],
    queryFn: getEventStats,
    refetchInterval: 15000,
  });

  const { data: unackData } = useQuery({
    queryKey: ["events-unack-count"],
    queryFn: () => getUnacknowledgedCount(),
    refetchInterval: 10000,
  });

  const { data: cameras } = useQuery({
    queryKey: ["cameras"],
    queryFn: getAllCameras,
  });

  const rawEvents = data?.events || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);
  const unackCount = unackData?.count || 0;

  // Client-side search filter applied on top of server-side filters
  const events = useMemo(() => {
    if (!searchQuery.trim()) return rawEvents;
    const q = searchQuery.toLowerCase();
    return rawEvents.filter((e) => {
      const cname = cameras?.find((c) => c.id === e.camera_id)?.name || "";
      return (
        (e.title || "").toLowerCase().includes(q) ||
        (e.event_type || "").toLowerCase().includes(q) ||
        cname.toLowerCase().includes(q)
      );
    });
  }, [rawEvents, searchQuery, cameras]);

  // ── Bulk selection helpers ────────────────────────────────────────────────
  const allOnPageSelected =
    events.length > 0 && events.every((e) => selectedIds.has(e.id));
  const someSelected = selectedIds.size > 0;

  // Drop selections that no longer appear on the current page
  useEffect(() => {
    if (!selectedIds.size) return;
    const visible = new Set(events.map((e) => e.id));
    let changed = false;
    const next = new Set();
    selectedIds.forEach((id) => {
      if (visible.has(id)) next.add(id);
      else changed = true;
    });
    if (changed) setSelectedIds(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events]);

  const toggleSelect = (id) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleSelectAllOnPage = () =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        events.forEach((e) => next.delete(e.id));
      } else {
        events.forEach((e) => next.add(e.id));
      }
      return next;
    });

  // ── Snapshot fetch for detail panel ──────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    let urls = [];
    const cleanup = () => urls.forEach((u) => URL.revokeObjectURL(u));

    if (!selectedEvent || !selectedEvent.camera_id) {
      setRecSnapUrl(null);
      return cleanup;
    }

    // Do NOT show a live-camera snapshot as a stand-in for events that carry no
    // snapshot of their own. The live grab is often a half-decoded/garbled frame
    // (H.265 ffmpeg snapshot) and is worse than a clean "No snapshot" message.
    // AI events (e.g. PPE) currently have no snapshot_path → show placeholder.
    if (!selectedEvent.snapshot_path) {
      setRecSnapUrl(null);
      setSnapLoading(false);
      return cleanup;
    }

    const camId = selectedEvent.camera_id;
    setSnapLoading(true);
    setRecSnapUrl(null);

    (async () => {
      try {
        const { getAccessToken, BACKEND_URL } = await import("../api/client");
        const latest = await getLatestSnapshot(camId);
        if (latest?.id && !cancelled) {
          const token = getAccessToken();
          const res = await fetch(
            `${BACKEND_URL}/api/cameras/snapshot-file/${latest.id}`,
            { headers: token ? { Authorization: `Bearer ${token}` } : {} },
          );
          if (res.ok && !cancelled) {
            const blob = await res.blob();
            const obj = URL.createObjectURL(blob);
            urls.push(obj);
            setRecSnapUrl(obj);
          }
        }
      } catch {
        // No prior snapshot available
      }
      if (!cancelled) setSnapLoading(false);
    })();

    return () => {
      cancelled = true;
      cleanup();
    };
  }, [selectedEvent]);

  // ── getCameraName ──────────────────────────────────────────────────────────
  const getCameraName = useCallback(
    (id) =>
      cameras?.find((c) => c.id === id)?.name || id?.slice(0, 8) || "System",
    [cameras],
  );

  // ── Mutations ─────────────────────────────────────────────────────────────
  const ackMutation = useMutation({
    mutationFn: ({ id, note }) => acknowledgeEvent(id, note),
    onSuccess: () => {
      toast.success("Event acknowledged");
      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["events-unack-count"] });
      qc.invalidateQueries({ queryKey: ["event-stats"] });
      setSelectedEvent((prev) =>
        prev ? { ...prev, acknowledged: true } : null,
      );
      setAckNote("");
    },
    onError: (err) => toast.error(friendlyError(err, "Couldn't acknowledge the event")),
  });

  const ackAllMutation = useMutation({
    mutationFn: (p) => acknowledgeAllEvents(p),
    onSuccess: (d) => {
      toast.success(`${d.acknowledged} events acknowledged`);
      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["events-unack-count"] });
      qc.invalidateQueries({ queryKey: ["event-stats"] });
    },
    onError: (err) => toast.error(friendlyError(err, "Couldn't acknowledge events")),
  });

  const falseAlarmMutation = useMutation({
    mutationFn: ({ id, note }) => markFalseAlarm(id, note),
    onSuccess: () => {
      toast.success("Marked as false alarm");
      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["events-unack-count"] });
      setSelectedEvent(null);
      setAckNote("");
    },
    onError: (err) => toast.error(friendlyError(err, "Couldn't update the event")),
  });

  const invalidateAfterDelete = () => {
    qc.invalidateQueries({ queryKey: ["events"] });
    qc.invalidateQueries({ queryKey: ["events-unack-count"] });
    qc.invalidateQueries({ queryKey: ["event-stats"] });
  };

  const deleteMutation = useMutation({
    mutationFn: (id) => deleteEvent(id),
    onSuccess: () => {
      toast.success("Event deleted");
      setSelectedEvent(null);
      invalidateAfterDelete();
    },
    onError: (err) => toast.error(friendlyError(err, "Couldn't delete the event")),
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: (body) => bulkDeleteEvents(body),
    onSuccess: (res) => {
      toast.success(`${res?.deleted ?? 0} events deleted`);
      setSelectedIds(new Set());
      setConfirmDelete(null);
      invalidateAfterDelete();
    },
    onError: (err) => toast.error(friendlyError(err, "Couldn't delete events")),
  });

  const runConfirmedDelete = () => {
    if (!confirmDelete) return;
    if (confirmDelete.mode === "single") {
      deleteMutation.mutate(confirmDelete.id, {
        onSuccess: () => setConfirmDelete(null),
      });
    } else if (confirmDelete.mode === "bulk") {
      bulkDeleteMutation.mutate({ event_ids: Array.from(selectedIds) });
    } else if (confirmDelete.mode === "filtered") {
      bulkDeleteMutation.mutate(confirmDelete.filters);
    }
  };

  const handleExportCSV = useCallback(async () => {
    try {
      const csvParams = {};
      if (eventType !== "all") csvParams.event_type = eventType;
      if (severity !== "all") csvParams.severity = severity;
      if (cameraId !== "all") csvParams.camera_id = cameraId;
      if (startDate) csvParams.start_date = startDate;
      if (endDate) csvParams.end_date = endDate;
      const blob = await exportEventsCSV(csvParams);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `events_${format(new Date(), "yyyyMMdd_HHmmss")}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Events exported");
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't export events"));
    }
  }, [eventType, severity, cameraId, startDate, endDate]);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden" style={{ background: "var(--console-bg)", color: "var(--console-text)" }}>

      {/* ── Console header ─────────────────────────────────────────────────── */}
      <div
        className="flex-shrink-0 px-4 py-3 border-b backdrop-blur-sm"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        <div className="flex items-center gap-4 flex-wrap">
          {/* Title */}
          <div className="flex items-center gap-2.5 flex-shrink-0">
            <Bell className="h-4 w-4 text-teal-400" />
            <span className="text-xs font-medium tracking-[0.18em] uppercase font-telemetry" style={{ color: "var(--console-text)" }}>
              Event Log
            </span>
            {unackCount > 0 && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-rose-500/20 text-rose-300 border border-rose-500/40">
                <BellOff className="h-3 w-3" />
                {unackCount} unack
              </span>
            )}
          </div>

          {/* Severity stat chips */}
          {stats && (
            <div className="flex items-center gap-1.5 flex-wrap">
              {Object.entries(SEVERITY_CONFIG).map(([key, { bar, label }]) => (
                <SeverityChip
                  key={key}
                  label={label}
                  count={stats.by_severity?.[key] || 0}
                  barClass={bar}
                />
              ))}
            </div>
          )}

          {/* Right action group */}
          <div className="ml-auto flex items-center gap-2 flex-wrap">
            {someSelected && (
              <Button
                variant="destructive"
                size="sm"
                className="h-7 text-xs"
                onClick={() =>
                  setConfirmDelete({ mode: "bulk", count: selectedIds.size })
                }
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                Delete {selectedIds.size}
              </Button>
            )}
            {!someSelected && total > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10"
                onClick={() => {
                  const filters = {};
                  if (eventType !== "all") filters.event_type = eventType;
                  if (severity !== "all") filters.severity = severity;
                  if (cameraId !== "all") filters.camera_id = cameraId;
                  if (acknowledged !== "all")
                    filters.acknowledged = acknowledged === "true";
                  if (endDate) filters.before = endDate;
                  if (Object.keys(filters).length === 0) {
                    toast.error(
                      "Apply at least one filter before deleting all matches",
                    );
                    return;
                  }
                  setConfirmDelete({
                    mode: "filtered",
                    filters,
                    label: `${total} matching events`,
                  });
                }}
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                Delete Filtered
              </Button>
            )}
            {unackCount > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs text-teal-400 hover:text-teal-300 hover:bg-teal-500/10"
                onClick={() => ackAllMutation.mutate({})}
                disabled={ackAllMutation.isPending}
              >
                <CheckCheck className="h-3.5 w-3.5 mr-1" />
                Ack All
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
                className="h-7 text-xs hover:bg-[var(--console-hover)]"
                style={{ color: "var(--console-muted)" }}
              onClick={handleExportCSV}
            >
              <Download className="h-3.5 w-3.5 mr-1" />
              CSV
            </Button>
          </div>
        </div>
      </div>

      {/* ── Filter bar ─────────────────────────────────────────────────────── */}
      <div
        className="flex-shrink-0 px-4 py-2.5 border-b"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        <div className="flex items-center gap-2 flex-wrap">
          <Filter className="h-3.5 w-3.5 flex-shrink-0" style={{ color: "var(--console-muted)" }} />

          {/* Free-text search */}
          <div className="relative flex-shrink-0">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 pointer-events-none" style={{ color: "var(--console-muted)" }} />
            <Input
              className="pl-6 h-7 w-44 text-xs"
              style={inputStyle}
              placeholder="Search title, type, camera…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <Select
            value={eventType}
            onValueChange={(v) => { setEventType(v); setPage(1); }}
          >
            <SelectTrigger className="h-7 w-36 text-xs" style={inputStyle}>
              <SelectValue placeholder="Event type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              {EVENT_TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={severity}
            onValueChange={(v) => { setSeverity(v); setPage(1); }}
          >
            <SelectTrigger className="h-7 w-28 text-xs" style={inputStyle}>
              <SelectValue placeholder="Severity" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="info">Info</SelectItem>
              <SelectItem value="warning">Warning</SelectItem>
              <SelectItem value="critical">Critical</SelectItem>
              <SelectItem value="alarm">Alarm</SelectItem>
            </SelectContent>
          </Select>

          <Select
            value={cameraId}
            onValueChange={(v) => { setCameraId(v); setPage(1); }}
          >
            <SelectTrigger className="h-7 w-36 text-xs" style={inputStyle}>
              <SelectValue placeholder="Camera" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Cameras</SelectItem>
              {cameras?.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={acknowledged}
            onValueChange={(v) => { setAcknowledged(v); setPage(1); }}
          >
            <SelectTrigger className="h-7 w-32 text-xs" style={inputStyle}>
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="false">Unacknowledged</SelectItem>
              <SelectItem value="true">Acknowledged</SelectItem>
            </SelectContent>
          </Select>

          <Input
            type="datetime-local"
            className="h-7 w-40 text-xs"
            style={inputStyle}
            value={startDate}
            onChange={(e) => { setStartDate(e.target.value); setPage(1); }}
          />
          <Input
            type="datetime-local"
            className="h-7 w-40 text-xs"
            style={inputStyle}
            value={endDate}
            onChange={(e) => { setEndDate(e.target.value); setPage(1); }}
          />
        </div>
      </div>

      {/* ── Master-detail body ─────────────────────────────────────────────── */}
      <div className="flex-1 flex min-h-0 overflow-hidden">

        {/* ── LEFT: Event list ─────────────────────────────────────────────── */}
        <div
          className="flex flex-col border-r"
          style={{ width: "420px", minWidth: "280px", maxWidth: "520px", flexShrink: 0, background: "var(--console-panel)", borderColor: "var(--console-border)" }}
        >

          {/* List header */}
          <div
            className="flex-shrink-0 flex items-center gap-2 px-3 py-2 border-b"
            style={{ background: "var(--console-raised)", borderColor: "var(--console-border)" }}
          >
            <input
              type="checkbox"
              aria-label="Select all on page"
              className="accent-teal-400 cursor-pointer"
              checked={allOnPageSelected}
              onChange={toggleSelectAllOnPage}
            />
            <span className="text-[10px] uppercase tracking-widest font-telemetry" style={{ color: "var(--console-muted)" }}>
              {total > 0 ? `${total} events` : "No events"}
              {searchQuery.trim() && events.length !== rawEvents.length
                ? ` · ${events.length} shown`
                : ""}
            </span>
          </div>

          {/* Scrollable event rows */}
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center py-16 text-xs" style={{ color: "var(--console-muted)" }}>
                Loading events…
              </div>
            ) : isError && rawEvents.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 gap-3 px-4 text-center">
                <AlertTriangle className="h-7 w-7" style={{ color: "var(--console-rec)" }} />
                <span className="text-xs" style={{ color: "var(--console-rec)" }}>
                  Failed to load events
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs hover:bg-[var(--console-hover)]"
                  style={{ borderColor: "var(--console-border)", color: "var(--console-text)" }}
                  onClick={() => refetch()}
                >
                  <RefreshCw className="h-3.5 w-3.5 mr-1" />
                  Retry
                </Button>
              </div>
            ) : events.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 gap-2" style={{ color: "var(--console-muted)" }}>
                <Bell className="h-7 w-7 opacity-30" />
                <span className="text-xs">No events found</span>
              </div>
            ) : (
              events.map((event) => {
                const Icon = getEventIcon(event.event_type);
                const sev = severityOf(event.severity);
                const isSelected = selectedEvent?.id === event.id;
                return (
                  <button
                    key={event.id}
                    type="button"
                    onClick={() => setSelectedEvent(event)}
                    className={cn(
                      "w-full flex items-stretch text-left border-b transition-colors focus:outline-none hover:bg-[var(--console-hover)]",
                      isSelected && "bg-teal-500/10 border-l-2 border-l-teal-500",
                      !isSelected && !event.acknowledged && "bg-rose-500/[0.03]",
                      selectedIds.has(event.id) && !isSelected && "bg-teal-500/[0.05]",
                    )}
                    style={{ borderColor: "var(--console-border)" }}
                  >
                    {/* Severity accent bar */}
                    {!isSelected && (
                      <span className={cn("w-1 flex-shrink-0 rounded-sm", sev.bar)} />
                    )}

                    {/* Checkbox cell */}
                    <span
                      className="flex items-center px-2 flex-shrink-0"
                      onClick={(e) => { e.stopPropagation(); toggleSelect(event.id); }}
                    >
                      <input
                        type="checkbox"
                        aria-label={`Select event ${event.id}`}
                        className="accent-teal-400 cursor-pointer"
                        checked={selectedIds.has(event.id)}
                        onChange={() => toggleSelect(event.id)}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </span>

                    {/* Content */}
                    <span className="flex-1 min-w-0 px-1 py-2.5">
                      {/* Row 1: type + timestamp */}
                      <span className="flex items-center justify-between gap-1 mb-1">
                        <span className="flex items-center gap-1.5 min-w-0">
                          <Icon className="h-3.5 w-3.5 flex-shrink-0" style={{ color: "var(--console-muted)" }} />
                          <span className="text-[11px] font-medium truncate" style={{ color: "var(--console-text)" }}>
                            {eventTypeLabel(event.event_type)}
                          </span>
                        </span>
                        <span className="text-[10px] font-telemetry flex-shrink-0" style={{ color: "var(--console-muted)" }}>
                          {event.triggered_at
                            ? format(new Date(event.triggered_at), "MMM dd HH:mm:ss")
                            : "—"}
                        </span>
                      </span>
                      {/* Row 2: camera + status badge */}
                      <span className="flex items-center justify-between gap-1">
                        <span className="text-[10px] truncate" style={{ color: "var(--console-muted)" }}>
                          {getCameraName(event.camera_id)}
                        </span>
                        <span className="flex items-center gap-1 flex-shrink-0">
                          <Badge
                            className={cn("text-[9px] px-1 py-0 h-4", sev.badge)}
                          >
                            {sev.label}
                          </Badge>
                          {event.is_false_alarm ? (
                            <Badge variant="outline" className="text-[9px] px-1 py-0 h-4">FA</Badge>
                          ) : event.acknowledged ? (
                            <Badge className="text-[9px] px-1 py-0 h-4 bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                              <Check className="h-2.5 w-2.5" />
                            </Badge>
                          ) : (
                            <Badge variant="destructive" className="text-[9px] px-1 py-0 h-4">
                              NEW
                            </Badge>
                          )}
                        </span>
                      </span>
                      {/* Row 3: title if present */}
                      {event.title && (
                        <span className="block text-[10px] truncate mt-0.5" style={{ color: "var(--console-muted)" }}>
                          {event.title}
                        </span>
                      )}
                    </span>

                    {/* Quick actions */}
                    <span className="flex flex-col justify-center gap-0.5 pr-2 pl-1 flex-shrink-0">
                      {!event.acknowledged && (
                        <span
                          role="button"
                          tabIndex={0}
                          title="Acknowledge"
                          className="p-1 rounded hover:bg-teal-500/20 text-zinc-500 hover:text-teal-400 transition-colors"
                          onClick={(e) => {
                            e.stopPropagation();
                            ackMutation.mutate({ id: event.id, note: null });
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.stopPropagation();
                              ackMutation.mutate({ id: event.id, note: null });
                            }
                          }}
                        >
                          <Check className="h-3 w-3" />
                        </span>
                      )}
                      <span
                        role="button"
                        tabIndex={0}
                        title="Delete event"
                        className="p-1 rounded hover:bg-rose-500/20 text-zinc-600 hover:text-rose-400 transition-colors"
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDelete({ mode: "single", id: event.id });
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.stopPropagation();
                            setConfirmDelete({ mode: "single", id: event.id });
                          }
                        }}
                      >
                        <Trash2 className="h-3 w-3" />
                      </span>
                    </span>
                  </button>
                );
              })
            )}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div
              className="flex-shrink-0 flex items-center justify-between border-t px-3 py-2"
              style={{ background: "var(--console-raised)", borderColor: "var(--console-border)" }}
            >
              <span className="text-[10px] font-telemetry" style={{ color: "var(--console-muted)" }}>
                Page {page}/{totalPages}
              </span>
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0 hover:bg-[var(--console-hover)]"
                  style={{ color: "var(--console-muted)" }}
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0 hover:bg-[var(--console-hover)]"
                  style={{ color: "var(--console-muted)" }}
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* ── RIGHT: Detail panel ───────────────────────────────────────────── */}
        <div
          className="flex-1 min-w-0 flex flex-col min-h-0"
          style={{ background: "var(--console-bg)" }}
        >
          {!selectedEvent ? (
            /* Empty state */
            <div className="flex flex-col items-center justify-center h-full gap-3" style={{ color: "var(--console-muted)" }}>
              <Bell className="h-10 w-10 opacity-20" />
              <p className="text-sm font-medium">No event selected</p>
              <p className="text-xs opacity-75">Click a row to view details</p>
            </div>
          ) : (
            <div className="flex flex-col h-full min-h-0">
              {/* Panel header */}
              <div
                className="flex-shrink-0 flex items-center justify-between px-4 py-2.5 border-b"
                style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
              >
                <div className="flex items-center gap-2">
                  {(() => {
                    const sev = severityOf(selectedEvent.severity);
                    return (
                      <>
                        <span className={cn("h-2 w-2 rounded-sm", sev.bar)} />
                        <span className="text-xs font-medium" style={{ color: "var(--console-text)" }}>
                          {eventTypeLabel(selectedEvent.event_type)}
                        </span>
                        <Badge className={cn("text-[10px] px-1.5 py-0", sev.badge)}>
                          {sev.label}
                        </Badge>
                      </>
                    );
                  })()}
                </div>
                <button
                  type="button"
                  className="text-[11px] transition-colors hover:opacity-80"
                  style={{ color: "var(--console-muted)" }}
                  onClick={() => setSelectedEvent(null)}
                >
                  Dismiss
                </button>
              </div>

              {/* Scrollable content — keeps action bar pinned below */}
              <div className="flex-1 min-h-0 overflow-y-auto">
              {/* Snapshot thumbnail */}
              <div className="flex-shrink-0 relative bg-black aspect-video w-full overflow-hidden">
                {recSnapUrl ? (
                  <img
                    src={recSnapUrl}
                    alt="event snapshot"
                    className="w-full h-full object-contain"
                  />
                ) : (
                  <div className="flex flex-col items-center justify-center h-full text-zinc-600 gap-2">
                    <Video className="h-8 w-8 opacity-30" />
                    <span className="text-xs">
                      {snapLoading ? "Loading snapshot…" : "No snapshot available"}
                    </span>
                  </div>
                )}
                {/* Camera name overlay */}
                <div className="absolute bottom-0 left-0 right-0 px-3 py-1.5 bg-gradient-to-t from-black/70 to-transparent flex items-end justify-between">
                  <span className="text-[11px] font-medium text-zinc-200 truncate">
                    {getCameraName(selectedEvent.camera_id)}
                  </span>
                  {selectedEvent.triggered_at && (
                    <span className="text-[10px] text-zinc-400 font-telemetry flex-shrink-0 ml-2">
                      {format(new Date(selectedEvent.triggered_at), "yyyy-MM-dd HH:mm:ss")}
                    </span>
                  )}
                </div>
              </div>

              {/* Metadata grid */}
              <div className="flex-shrink-0 divide-y" style={{ borderColor: "var(--console-border)" }}>
                {[
                  ["Event Type", eventTypeLabel(selectedEvent.event_type)],
                  ["Date / Time", selectedEvent.triggered_at
                    ? format(new Date(selectedEvent.triggered_at), "yyyy-MM-dd HH:mm:ss")
                    : "—"],
                  ["Camera", getCameraName(selectedEvent.camera_id)],
                  ["Title", selectedEvent.title || "—"],
                  ["Status", null], // rendered specially
                ].map(([k, v]) => (
                  <div key={k} className="grid grid-cols-[130px_1fr] px-4 py-2 text-sm">
                    <span className="text-[10px] uppercase tracking-wider self-center font-telemetry" style={{ color: "var(--console-muted)" }}>
                      {k}
                    </span>
                    {k === "Status" ? (
                      <span className="flex items-center gap-1.5">
                        {selectedEvent.is_false_alarm ? (
                          <Badge variant="outline" className="text-[10px]">False Alarm</Badge>
                        ) : selectedEvent.acknowledged ? (
                          <Badge className="text-[10px] bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                            <Check className="h-3 w-3 mr-1" />
                            Acknowledged
                          </Badge>
                        ) : (
                          <Badge variant="destructive" className="text-[10px]">
                            <BellOff className="h-3 w-3 mr-1" />
                            Unacknowledged
                          </Badge>
                        )}
                      </span>
                    ) : (
                      <span className="text-xs truncate capitalize self-center" style={{ color: "var(--console-text)" }}>
                        {v}
                      </span>
                    )}
                  </div>
                ))}
                {selectedEvent.description && (
                  <div className="px-4 py-2">
                    <span className="text-[10px] uppercase tracking-wider font-telemetry block mb-1" style={{ color: "var(--console-muted)" }}>
                      Description
                    </span>
                    <p className="text-xs" style={{ color: "var(--console-text)" }}>{selectedEvent.description}</p>
                  </div>
                )}
                {selectedEvent.note && (
                  <div className="px-4 py-2">
                    <span className="text-[10px] uppercase tracking-wider font-telemetry block mb-1" style={{ color: "var(--console-muted)" }}>
                      Note
                    </span>
                    <p className="text-xs" style={{ color: "var(--console-text)" }}>{selectedEvent.note}</p>
                  </div>
                )}
              </div>

              {/* Acknowledge note textarea (only if unacked) */}
              {!selectedEvent.acknowledged && (
                <div className="flex-shrink-0 px-4 py-3 border-t" style={{ borderColor: "var(--console-border)" }}>
                  <Textarea
                    placeholder="Add a note before acknowledging (optional)…"
                    value={ackNote}
                    onChange={(e) => setAckNote(e.target.value)}
                    rows={2}
                    className="text-xs resize-none"
                    style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-text)" }}
                  />
                </div>
              )}

              </div>{/* /scrollable content */}

              {/* Action buttons */}
              <div
                className="flex-shrink-0 flex flex-wrap gap-2 px-4 py-3 border-t"
                style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
              >
                {!selectedEvent.acknowledged && (
                  <Button
                    size="sm"
                    className="h-7 text-xs hover:opacity-90"
                    style={{ background: "var(--console-accent)", color: "var(--console-accent-foreground)" }}
                    onClick={() =>
                      ackMutation.mutate({ id: selectedEvent.id, note: ackNote || null })
                    }
                    disabled={ackMutation.isPending}
                  >
                    <Check className="h-3.5 w-3.5 mr-1" />
                    Acknowledge
                  </Button>
                )}
                {!selectedEvent.acknowledged && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs hover:bg-[var(--console-hover)]"
                    style={{ borderColor: "var(--console-border)", color: "var(--console-text)" }}
                    onClick={() =>
                      falseAlarmMutation.mutate({ id: selectedEvent.id, note: ackNote || null })
                    }
                    disabled={falseAlarmMutation.isPending}
                  >
                    <XCircle className="h-3.5 w-3.5 mr-1" />
                    False Alarm
                  </Button>
                )}
                {selectedEvent.camera_id && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs hover:bg-[var(--console-hover)]"
                    style={{ borderColor: "var(--console-border)", color: "var(--console-text)" }}
                    onClick={() =>
                      navigate(`/playback?camera=${selectedEvent.camera_id}`)
                    }
                  >
                    <PlayCircle className="h-3.5 w-3.5 mr-1" />
                    Jump to Playback
                  </Button>
                )}
                {selectedEvent.camera_id && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs hover:bg-[var(--console-hover)]"
                    style={{ borderColor: "var(--console-border)", color: "var(--console-text)" }}
                    onClick={() => setLiveOpen(true)}
                  >
                    <Eye className="h-3.5 w-3.5 mr-1" />
                    View Live
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 ml-auto"
                  onClick={() =>
                    setConfirmDelete({ mode: "single", id: selectedEvent.id })
                  }
                >
                  <Trash2 className="h-3.5 w-3.5 mr-1" />
                  Delete
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Live-view dialog ──────────────────────────────────────────────────── */}
      <Dialog open={liveOpen} onOpenChange={setLiveOpen}>
        <DialogContent
          className="max-w-3xl"
          style={{ background: "var(--console-panel)", borderColor: "var(--console-border)", color: "var(--console-text)" }}
        >
          <DialogHeader>
            <DialogTitle className="text-sm font-medium" style={{ color: "var(--console-text)" }}>
              Live View — {selectedEvent ? getCameraName(selectedEvent.camera_id) : ""}
            </DialogTitle>
          </DialogHeader>
          {selectedEvent && liveOpen && (
            <div className="aspect-video bg-black rounded overflow-hidden">
              <WebRTCPlayer
                key={selectedEvent.camera_id}
                cameraId={selectedEvent.camera_id}
                streamId={selectedEvent.camera_id}
                autoPlay
                muted
                className="w-full h-full"
              />
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* ── Delete confirmation dialog ────────────────────────────────────────── */}
      <Dialog
        open={!!confirmDelete}
        onOpenChange={(open) => !open && setConfirmDelete(null)}
      >
        <DialogContent
          className="max-w-md"
          style={{ background: "var(--console-panel)", borderColor: "var(--console-border)", color: "var(--console-text)" }}
        >
          <DialogHeader>
            <DialogTitle className="text-sm font-medium" style={{ color: "var(--console-text)" }}>
              Confirm delete
            </DialogTitle>
          </DialogHeader>
          {confirmDelete && (
            <div className="space-y-4 text-sm">
              <p style={{ color: "var(--console-muted)" }}>
                {confirmDelete.mode === "single" &&
                  "This event will be permanently removed. This cannot be undone."}
                {confirmDelete.mode === "bulk" &&
                  `${confirmDelete.count} selected events will be permanently removed.`}
                {confirmDelete.mode === "filtered" &&
                  `${confirmDelete.label} will be permanently removed. This cannot be undone.`}
              </p>
              <div className="flex justify-end gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs hover:bg-[var(--console-hover)]"
                  style={{ borderColor: "var(--console-border)", color: "var(--console-text)" }}
                  onClick={() => setConfirmDelete(null)}
                >
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={runConfirmedDelete}
                  disabled={
                    deleteMutation.isPending || bulkDeleteMutation.isPending
                  }
                >
                  <Trash2 className="h-3.5 w-3.5 mr-1" />
                  Delete
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Events;
