// =============================================================================
// AI · Events tab — recognition event log for this scenario.
//
// Filterable, paginated table over GET /api/ai/frs/events. Columns: time,
// camera, type, person + confidence, snapshot thumb, bbox. Acknowledge reuses
// the unified NVR events ack endpoint (POST /api/events/{id}/acknowledge).
// =============================================================================

import React, { useMemo, useState } from "react";
import {
  useQuery,
  useMutation,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Filter,
  ImageOff,
  ScanFace,
  Loader2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { format } from "date-fns";

import { listFrsEvents, getScenarioCameras } from "../../../api/frs";
import { acknowledgeEvent } from "../../../api/events";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../../components/ui/select";
import { cn } from "../../../lib/utils";
import {
  FRS_EVENT_TYPES,
  eventPersonName,
  eventTypeBadgeClass,
  confidenceBadgeClass,
  fmtConfidence,
  fmtBbox,
  snapshotUrl,
  cameraNameMap,
  FRS_EVENT_LABEL,
} from "./frsShared";

const PAGE_SIZE = 25;
const ALL = "__all__";

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return format(new Date(iso), "MMM d, HH:mm:ss");
  } catch {
    return iso;
  }
}

function SnapshotThumb({ ev }) {
  const [errored, setErrored] = useState(false);
  const url = snapshotUrl(ev.snapshot_path);
  if (!url || errored) {
    return (
      <div
        className="h-10 w-16 rounded flex items-center justify-center border"
        style={{
          borderColor: "var(--console-border)",
          background: "var(--console-raised)",
        }}
      >
        <ImageOff className="h-4 w-4 text-zinc-600" />
      </div>
    );
  }
  return (
    <img
      src={url}
      alt="snapshot"
      loading="lazy"
      onError={() => setErrored(true)}
      className="h-10 w-16 rounded object-cover border"
      style={{ borderColor: "var(--console-border)" }}
    />
  );
}

export default function EventsTab({ scenario }) {
  const scenarioId = scenario?.id;
  const qc = useQueryClient();

  const [page, setPage] = useState(0);
  const [cameraId, setCameraId] = useState(ALL);
  const [eventType, setEventType] = useState(ALL);
  const [personId, setPersonId] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");

  const { data: cameras = [] } = useQuery({
    queryKey: ["frs", "scenario-cameras", scenarioId],
    queryFn: () => getScenarioCameras(scenarioId),
    enabled: !!scenarioId,
  });
  const camMap = useMemo(() => cameraNameMap(cameras), [cameras]);

  const params = useMemo(() => {
    const p = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
    if (cameraId !== ALL) p.camera_id = cameraId;
    if (eventType !== ALL) p.event_type = eventType;
    if (personId.trim()) p.person_id = personId.trim();
    if (since) p.since = new Date(since).toISOString();
    if (until) p.until = new Date(until).toISOString();
    return p;
  }, [page, cameraId, eventType, personId, since, until]);

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["frs", "events", params],
    queryFn: () => listFrsEvents(params),
    placeholderData: keepPreviousData,
  });

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const ackMutation = useMutation({
    mutationFn: (eventId) => acknowledgeEvent(eventId),
    onSuccess: () => {
      toast.success("Event acknowledged");
      qc.invalidateQueries({ queryKey: ["frs", "events"] });
    },
    onError: () => toast.error("Couldn't acknowledge event"),
  });

  const resetFilters = () => {
    setCameraId(ALL);
    setEventType(ALL);
    setPersonId("");
    setSince("");
    setUntil("");
    setPage(0);
  };

  const onFilterChange = (setter) => (val) => {
    setter(val);
    setPage(0);
  };

  const hasFilters =
    cameraId !== ALL ||
    eventType !== ALL ||
    personId.trim() ||
    since ||
    until;

  return (
    <div className="p-4 space-y-3">
      {/* Filter bar */}
      <div
        className="flex flex-wrap items-end gap-2 rounded-lg border p-3"
        style={{
          borderColor: "var(--console-border)",
          background: "var(--console-panel)",
        }}
      >
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-zinc-500 font-telemetry mr-1">
          <Filter className="h-3.5 w-3.5" /> Filters
        </div>

        <div className="w-44">
          <Select value={cameraId} onValueChange={onFilterChange(setCameraId)}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Camera" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All cameras</SelectItem>
              {cameras.map((c) => (
                <SelectItem key={c.camera_id} value={c.camera_id}>
                  {c.camera_name || c.camera_id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-40">
          <Select value={eventType} onValueChange={onFilterChange(setEventType)}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All types</SelectItem>
              {FRS_EVENT_TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-44">
          <Input
            className="h-8 text-xs"
            placeholder="Person ID"
            value={personId}
            onChange={(e) => {
              setPersonId(e.target.value);
              setPage(0);
            }}
          />
        </div>

        <div>
          <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">
            From
          </label>
          <Input
            type="datetime-local"
            className="h-8 text-xs"
            value={since}
            onChange={(e) => {
              setSince(e.target.value);
              setPage(0);
            }}
          />
        </div>
        <div>
          <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">
            To
          </label>
          <Input
            type="datetime-local"
            className="h-8 text-xs"
            value={until}
            onChange={(e) => {
              setUntil(e.target.value);
              setPage(0);
            }}
          />
        </div>

        {hasFilters ? (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-xs"
            onClick={resetFilters}
          >
            <X className="h-3.5 w-3.5 mr-1" /> Clear
          </Button>
        ) : null}

        <div className="ml-auto text-[11px] text-zinc-500 font-telemetry self-center">
          {total} event{total === 1 ? "" : "s"}
          {isFetching && (
            <Loader2 className="inline h-3 w-3 ml-2 animate-spin text-zinc-400" />
          )}
        </div>
      </div>

      {/* Table */}
      <div
        className="rounded-lg border overflow-hidden"
        style={{ borderColor: "var(--console-border)" }}
      >
        <table className="w-full text-left">
          <thead>
            <tr
              className="text-[10px] uppercase tracking-wider text-zinc-500 font-telemetry"
              style={{ background: "var(--console-raised)" }}
            >
              <th className="px-3 py-2 font-medium">Time</th>
              <th className="px-3 py-2 font-medium">Camera</th>
              <th className="px-3 py-2 font-medium">Type</th>
              <th className="px-3 py-2 font-medium">Person / Conf.</th>
              <th className="px-3 py-2 font-medium">Snapshot</th>
              <th className="px-3 py-2 font-medium">BBox</th>
              <th className="px-3 py-2 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <tr key={i} className="border-t" style={{ borderColor: "var(--console-border)" }}>
                  <td colSpan={7} className="px-3 py-3">
                    <div className="h-5 rounded animate-pulse bg-zinc-800/60" />
                  </td>
                </tr>
              ))
            ) : isError ? (
              <tr>
                <td colSpan={7} className="px-3 py-12 text-center text-sm text-rose-400">
                  Couldn't load events.
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-16 text-center">
                  <ScanFace className="h-9 w-9 mx-auto text-zinc-600 mb-2" />
                  <p className="text-sm text-zinc-300">No recognition events</p>
                  <p className="text-xs text-zinc-500 mt-1">
                    {hasFilters
                      ? "Try widening your filters."
                      : "Events appear here as faces are recognized."}
                  </p>
                </td>
              </tr>
            ) : (
              items.map((ev) => (
                <tr
                  key={ev.id}
                  className="border-t hover:bg-white/[0.02] transition-colors"
                  style={{ borderColor: "var(--console-border)" }}
                >
                  <td className="px-3 py-2 text-xs text-zinc-300 font-telemetry whitespace-nowrap">
                    {fmtTime(ev.triggered_at)}
                  </td>
                  <td className="px-3 py-2 text-xs text-zinc-300 max-w-[160px] truncate">
                    {camMap[ev.camera_id] || ev.camera_id || "—"}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium",
                        eventTypeBadgeClass(ev.event_type),
                      )}
                    >
                      {FRS_EVENT_LABEL[ev.event_type] || ev.event_type}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-zinc-200 truncate max-w-[140px]">
                        {eventPersonName(ev)}
                      </span>
                      <span
                        className={cn(
                          "rounded border px-1.5 text-[10px] font-telemetry",
                          confidenceBadgeClass(ev.confidence),
                        )}
                      >
                        {fmtConfidence(ev.confidence)}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <SnapshotThumb ev={ev} />
                  </td>
                  <td className="px-3 py-2 text-[11px] text-zinc-400 font-telemetry whitespace-nowrap">
                    {fmtBbox(ev.bbox)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs"
                      disabled={ackMutation.isPending}
                      onClick={() => ackMutation.mutate(ev.id)}
                    >
                      <Check className="h-3.5 w-3.5 mr-1" /> Ack
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-2">
          <span className="text-[11px] text-zinc-500 font-telemetry">
            Page {page + 1} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            disabled={page + 1 >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
