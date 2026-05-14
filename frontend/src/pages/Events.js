// =============================================================================
// Events — Real-time event log with filters, acknowledge, CSV export
// =============================================================================

import React, { useState, useMemo, useEffect, useCallback } from "react";
import {
  useQuery,
  useMutation,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
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
} from "lucide-react";
import {
  getEvents,
  getEventStats,
  getUnacknowledgedCount,
  acknowledgeEvent,
  acknowledgeAllEvents,
  markFalseAlarm,
  exportEventsCSV,
} from "../api/events";
import { getAllCameras } from "../api/cameras";
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
import { toast } from "sonner";
import { format } from "date-fns";

const PAGE_SIZE = 50;

const EVENT_TYPES = [
  { value: "motion_detected", label: "Motion Detected", icon: Activity },
  { value: "video_loss", label: "Video Loss", icon: VideoOff },
  { value: "camera_tamper", label: "Camera Tamper", icon: Shield },
  { value: "camera_offline", label: "Camera Offline", icon: VideoOff },
  { value: "camera_online", label: "Camera Online", icon: Video },
  { value: "recording_error", label: "Recording Error", icon: AlertTriangle },
  { value: "recording_gap", label: "Recording Gap", icon: AlertTriangle },
  { value: "storage_low", label: "Storage Low", icon: AlertTriangle },
  { value: "disk_full", label: "Disk Full", icon: XCircle },
  { value: "system_error", label: "System Error", icon: XCircle },
  { value: "manual", label: "Manual", icon: Bell },
];

const SEVERITY_MAP = {
  info:     { color: "bg-blue-500/15 text-blue-300 border border-blue-500/30",   label: "Info" },
  warning:  { color: "bg-amber-500/15 text-amber-300 border border-amber-500/30", label: "Warning" },
  critical: { color: "bg-rose-500/15 text-rose-300 border border-rose-500/30",   label: "Critical" },
  alarm:    { color: "bg-rose-500/25 text-rose-200 border border-rose-500/50",   label: "Alarm" },
};

const Events = () => {
  const qc = useQueryClient();

  // Filters
  const [page, setPage] = useState(1);
  const [eventType, setEventType] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [cameraId, setCameraId] = useState("all");
  const [acknowledged, setAcknowledged] = useState("all");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  // Detail dialog
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [ackNote, setAckNote] = useState("");

  // Build query params
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

  // Queries
  const { data, isLoading } = useQuery({
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

  const events = data?.events || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);
  const unackCount = unackData?.count || 0;

  // Mutations
  const ackMutation = useMutation({
    mutationFn: ({ id, note }) => acknowledgeEvent(id, note),
    onSuccess: () => {
      toast.success("Event acknowledged");
      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["events-unack-count"] });
      qc.invalidateQueries({ queryKey: ["event-stats"] });
      setSelectedEvent(null);
      setAckNote("");
    },
  });

  const ackAllMutation = useMutation({
    mutationFn: (params) => acknowledgeAllEvents(params),
    onSuccess: (data) => {
      toast.success(`${data.acknowledged} events acknowledged`);
      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["events-unack-count"] });
      qc.invalidateQueries({ queryKey: ["event-stats"] });
    },
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
  });

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
    } catch {
      toast.error("Export failed");
    }
  }, [eventType, severity, cameraId, startDate, endDate]);

  const getCameraName = useCallback(
    (id) =>
      cameras?.find((c) => c.id === id)?.name || id?.slice(0, 8) || "System",
    [cameras],
  );

  const getEventIcon = (type) => {
    const et = EVENT_TYPES.find((e) => e.value === type);
    return et ? et.icon : Bell;
  };

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Bell className="h-6 w-6" />
          <h1 className="text-2xl font-semibold">Events & Alarms</h1>
          {unackCount > 0 && (
            <Badge variant="destructive">{unackCount} unacknowledged</Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          {unackCount > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => ackAllMutation.mutate({})}
              disabled={ackAllMutation.isPending}
            >
              <CheckCheck className="h-4 w-4 mr-1" />
              Acknowledge All
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={handleExportCSV}>
            <Download className="h-4 w-4 mr-1" />
            Export CSV
          </Button>
        </div>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(SEVERITY_MAP).map(([key, { color, label }]) => (
            <div
              key={key}
              className="rounded-lg border border-border bg-card/50 p-3 flex items-center justify-between"
            >
              <span className="text-sm text-muted-foreground">{label}</span>
              <Badge className={color}>{stats.by_severity?.[key] || 0}</Badge>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-card/40 p-3">
        <Filter className="h-4 w-4 text-muted-foreground mt-5" />

        <div className="w-40">
          <Select
            value={eventType}
            onValueChange={(v) => {
              setEventType(v);
              setPage(1);
            }}
          >
            <SelectTrigger>
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
        </div>

        <div className="w-32">
          <Select
            value={severity}
            onValueChange={(v) => {
              setSeverity(v);
              setPage(1);
            }}
          >
            <SelectTrigger>
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
        </div>

        <div className="w-44">
          <Select
            value={cameraId}
            onValueChange={(v) => {
              setCameraId(v);
              setPage(1);
            }}
          >
            <SelectTrigger>
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
        </div>

        <div className="w-36">
          <Select
            value={acknowledged}
            onValueChange={(v) => {
              setAcknowledged(v);
              setPage(1);
            }}
          >
            <SelectTrigger>
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="false">Unacknowledged</SelectItem>
              <SelectItem value="true">Acknowledged</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <Input
          type="datetime-local"
          className="w-44"
          value={startDate}
          onChange={(e) => {
            setStartDate(e.target.value);
            setPage(1);
          }}
          placeholder="Start date"
        />
        <Input
          type="datetime-local"
          className="w-44"
          value={endDate}
          onChange={(e) => {
            setEndDate(e.target.value);
            setPage(1);
          }}
          placeholder="End date"
        />
      </div>

      {/* Events table */}
      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-card/50 text-zinc-400 uppercase text-[11px] tracking-wider">
              <tr>
                <th className="text-left p-3 font-medium">Time</th>
                <th className="text-left p-3 font-medium">Type</th>
                <th className="text-left p-3 font-medium">Severity</th>
                <th className="text-left p-3 font-medium">Camera</th>
                <th className="text-left p-3 font-medium">Title</th>
                <th className="text-left p-3 font-medium">Status</th>
                <th className="text-right p-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td
                    colSpan={7}
                    className="p-8 text-center text-muted-foreground"
                  >
                    Loading events…
                  </td>
                </tr>
              ) : events.length === 0 ? (
                <tr>
                  <td
                    colSpan={7}
                    className="p-8 text-center text-muted-foreground"
                  >
                    No events found
                  </td>
                </tr>
              ) : (
                events.map((event) => {
                  const Icon = getEventIcon(event.event_type);
                  const sevInfo =
                    SEVERITY_MAP[event.severity] || SEVERITY_MAP.info;
                  return (
                    <tr
                      key={event.id}
                      className={`border-t border-white/5 hover:bg-card/50 cursor-pointer transition-colors ${
                        !event.acknowledged ? "bg-rose-500/[0.04]" : ""
                      }`}
                      onClick={() => setSelectedEvent(event)}
                    >
                      <td className="p-3 whitespace-nowrap text-muted-foreground">
                        {event.triggered_at
                          ? format(
                              new Date(event.triggered_at),
                              "MMM dd HH:mm:ss",
                            )
                          : "—"}
                      </td>
                      <td className="p-3">
                        <div className="flex items-center gap-1.5">
                          <Icon className="h-4 w-4" />
                          <span className="capitalize">
                            {event.event_type.replace(/_/g, " ")}
                          </span>
                        </div>
                      </td>
                      <td className="p-3">
                        <Badge className={sevInfo.color} variant="secondary">
                          {sevInfo.label}
                        </Badge>
                      </td>
                      <td className="p-3">{getCameraName(event.camera_id)}</td>
                      <td className="p-3 max-w-[300px] truncate">
                        {event.title}
                      </td>
                      <td className="p-3">
                        {event.is_false_alarm ? (
                          <Badge variant="outline">False Alarm</Badge>
                        ) : event.acknowledged ? (
                          <Badge
                            variant="secondary"
                            className="bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                          >
                            <Check className="h-3 w-3 mr-1" />
                            Ack
                          </Badge>
                        ) : (
                          <Badge variant="destructive">
                            <BellOff className="h-3 w-3 mr-1" />
                            New
                          </Badge>
                        )}
                      </td>
                      <td className="p-3 text-right">
                        {!event.acknowledged && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              ackMutation.mutate({ id: event.id, note: null });
                            }}
                          >
                            <Check className="h-4 w-4" />
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between border-t p-3">
            <span className="text-sm text-muted-foreground">
              {total} events — page {page} of {totalPages}
            </span>
            <div className="flex gap-1">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Event detail dialog */}
      <Dialog
        open={!!selectedEvent}
        onOpenChange={() => setSelectedEvent(null)}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Event Details</DialogTitle>
          </DialogHeader>
          {selectedEvent && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <span className="text-muted-foreground">Type</span>
                  <p className="font-medium capitalize">
                    {selectedEvent.event_type.replace(/_/g, " ")}
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">Severity</span>
                  <p>
                    <Badge
                      className={
                        SEVERITY_MAP[selectedEvent.severity]?.color ||
                        SEVERITY_MAP.info.color
                      }
                    >
                      {selectedEvent.severity}
                    </Badge>
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">Camera</span>
                  <p className="font-medium">
                    {getCameraName(selectedEvent.camera_id)}
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">Time</span>
                  <p className="font-medium">
                    {selectedEvent.triggered_at
                      ? format(
                          new Date(selectedEvent.triggered_at),
                          "yyyy-MM-dd HH:mm:ss",
                        )
                      : "—"}
                  </p>
                </div>
              </div>

              <div>
                <span className="text-sm text-muted-foreground">Title</span>
                <p className="font-medium">{selectedEvent.title}</p>
              </div>

              {selectedEvent.description && (
                <div>
                  <span className="text-sm text-muted-foreground">
                    Description
                  </span>
                  <p className="text-sm">{selectedEvent.description}</p>
                </div>
              )}

              {selectedEvent.note && (
                <div>
                  <span className="text-sm text-muted-foreground">Note</span>
                  <p className="text-sm">{selectedEvent.note}</p>
                </div>
              )}

              {!selectedEvent.acknowledged && (
                <div className="space-y-2">
                  <Textarea
                    placeholder="Add a note (optional)…"
                    value={ackNote}
                    onChange={(e) => setAckNote(e.target.value)}
                    rows={2}
                  />
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      onClick={() =>
                        ackMutation.mutate({
                          id: selectedEvent.id,
                          note: ackNote || null,
                        })
                      }
                      disabled={ackMutation.isPending}
                    >
                      <Check className="h-4 w-4 mr-1" />
                      Acknowledge
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        falseAlarmMutation.mutate({
                          id: selectedEvent.id,
                          note: ackNote || null,
                        })
                      }
                      disabled={falseAlarmMutation.isPending}
                    >
                      <XCircle className="h-4 w-4 mr-1" />
                      False Alarm
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Events;
