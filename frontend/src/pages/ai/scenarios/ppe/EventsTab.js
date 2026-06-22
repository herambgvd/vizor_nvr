// =============================================================================
// AI · PPE · Events tab — compliance event log.
//
// Scoped to PPE only. Reads the PPE plugin event store (listScenarioPluginEvents
// → /events) and shows the compliance columns: time / camera / event / worker /
// missing PPE / confidence / snapshot. Rows open a detail modal with the
// missing + present item lists. Ack + delete route to the PPE plugin store.
// =============================================================================

import React, { useEffect, useMemo, useState } from "react";
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
  Bell,
  Loader2,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { formatDateTime } from "../../../../lib/datetime";

import { getScenarioCameras } from "../../../../api/frs";
import {
  listScenarioPluginEvents,
  deleteScenarioPluginEvent,
  bulkDeleteScenarioPluginEvents,
  scenarioSnapshotUrl,
} from "../../../../api/ai";
import { acknowledgeEvent } from "../../../../api/events";
import { useConfirm } from "../../../../components/ui/confirm";
import { Button } from "../../../../components/ui/button";
import { Input } from "../../../../components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../../../components/ui/select";
import { cn } from "../../../../lib/utils";
import {
  confidenceBadgeClass,
  fmtConfidence,
  fmtBbox,
  snapshotUrl,
  cameraNameMap,
} from "../frs/frsShared";

const PAGE_SIZE = 25;
const ALL = "__all__";
const SLUG = "ppe";

// Operators only care about two states: PPE Missing (a violation) or Compliant.
// ppe_removed (worn earlier, then taken off) is still "not wearing PPE now", so
// it's shown as PPE Missing — no confusing third state.
const PPE_EVENT_LABEL = {
  ppe_missing: "PPE Missing",
  ppe_removed: "PPE Missing",
  ppe_compliant: "Compliant",
};

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return formatDateTime(iso);
  } catch {
    return iso;
  }
}

const prettyEventLabel = (slug) =>
  PPE_EVENT_LABEL[slug] ||
  String(slug || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

function typeBadgeClass(type) {
  switch (type) {
    case "ppe_compliant":
      return "border-emerald-500/40 bg-emerald-500/15 text-emerald-300";
    case "ppe_missing":
    case "ppe_removed":
      return "border-rose-500/40 bg-rose-500/15 text-rose-300";
    default:
      return "border-zinc-600/50 bg-zinc-700/30 text-zinc-300";
  }
}

function SnapshotThumb({ ev }) {
  const [errored, setErrored] = useState(false);
  const [blobUrl, setBlobUrl] = useState(null);
  const path = ev.snapshot_path;
  const isPluginSnap = typeof path === "string" && path.startsWith("/snapshot");

  useEffect(() => {
    if (!isPluginSnap || !path) return undefined;
    let active = true;
    let obj = null;
    scenarioSnapshotUrl(SLUG, path).then((u) => {
      if (!active) { if (u) URL.revokeObjectURL(u); return; }
      obj = u;
      setBlobUrl(u);
    });
    return () => { active = false; if (obj) URL.revokeObjectURL(obj); };
  }, [isPluginSnap, path]);

  const url = isPluginSnap ? blobUrl : snapshotUrl(path);

  if (!path || errored || (isPluginSnap && !blobUrl)) {
    return (
      <div className="h-10 w-16 rounded flex items-center justify-center border" style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}>
        <ImageOff className="h-4 w-4 text-zinc-600" />
      </div>
    );
  }
  return (
    <img src={url} alt="snapshot" loading="lazy" onError={() => setErrored(true)} className="h-10 w-16 rounded object-cover border" style={{ borderColor: "var(--console-border)" }} />
  );
}

function AuthImage({ fetcher, deps, className, fallback, fit = "cover" }) {
  const [url, setUrl] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let active = true;
    let obj = null;
    setUrl(null); setErr(false);
    if (!fetcher) { setErr(true); return undefined; }
    fetcher().then((u) => {
      if (!active) { if (u) URL.revokeObjectURL(u); return; }
      if (u) { obj = u; setUrl(u); } else setErr(true);
    }).catch(() => active && setErr(true));
    return () => { active = false; if (obj) URL.revokeObjectURL(obj); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  if (err) return fallback || null;
  if (!url) {
    return (
      <div className={`${className} flex items-center justify-center`} style={{ background: "var(--console-raised)" }}>
        <Loader2 className="h-4 w-4 animate-spin text-zinc-500" />
      </div>
    );
  }
  return <img src={url} alt="" className={className} style={{ objectFit: fit }} />;
}

function ChipList({ items, tone }) {
  if (!Array.isArray(items) || items.length === 0) {
    return <span className="text-zinc-600 text-xs">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((it) => (
        <span
          key={it}
          className={cn(
            "rounded border px-1.5 py-0.5 text-[10px] font-telemetry uppercase tracking-wide",
            tone === "danger"
              ? "border-rose-500/40 bg-rose-500/15 text-rose-300"
              : "border-zinc-600/50 bg-zinc-700/30 text-zinc-300",
          )}
        >
          {String(it).replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}

const ConfBadge = (ev) => (
  <span className={cn("rounded border px-1.5 text-[10px] font-telemetry", confidenceBadgeClass(ev.confidence))}>
    {fmtConfidence(ev.confidence)}
  </span>
);

// Item chips for the detail modal — missing items render as red "No {item}"
// violation chips, present items as emerald compliant chips (vizor-app palette).
function ItemChip({ label, tone }) {
  const cls =
    tone === "danger"
      ? "bg-red-500/10 text-red-400 border-red-500/30"
      : "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
  return (
    <span className={cn("text-[11px] px-2 py-0.5 rounded border", cls)}>{label}</span>
  );
}

function EventDetailModal({ event, camMap, onClose }) {
  if (!event) return null;
  const ev = event;
  const confPct = typeof ev.confidence === "number" ? `${(ev.confidence * 100).toFixed(1)}%` : "—";
  const isViolation = ev.event_type === "ppe_missing" || ev.event_type === "ppe_removed";
  const missing = Array.isArray(ev.missing_items) ? ev.missing_items : [];
  const present = Array.isArray(ev.present_items) ? ev.present_items : [];
  const prettyItem = (it) => String(it).replace(/_/g, " ");
  // Person crop = the SAME snapshot path with &crop=1 appended (backend already
  // renders the tight person crop for that key). scenarioSnapshotUrl forwards the
  // full query string through the proxy, so the crop arrives authenticated.
  const cropPath = ev.snapshot_path
    ? `${ev.snapshot_path}${ev.snapshot_path.includes("?") ? "&" : "?"}crop=1`
    : null;
  // The chips above already state the PPE status (No helmet / vest worn …), so no
  // redundant "Type: ppe missing" row.
  const rows = [
    ["Time", fmtTime(ev.triggered_at)],
    ["Camera", camMap[ev.camera_id] || ev.camera_id || "—"],
    ev.worker_track_id != null ? ["Worker", `#${ev.worker_track_id}`] : null,
    ["Confidence", confPct],
    ev.id != null ? ["Event ID", String(ev.id)] : null,
  ].filter(Boolean);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.7)" }} onClick={onClose}>
      <div className="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-lg flex flex-col" style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 sticky top-0 z-10" style={{ borderBottom: "1px solid var(--console-border)", background: "var(--console-panel)" }}>
          <span className="font-telemetry text-[12px] font-semibold uppercase tracking-widest" style={{ color: "var(--console-text)" }}>Event details</span>
          <button type="button" onClick={onClose} className="h-7 w-7 inline-flex items-center justify-center rounded hover:opacity-70" style={{ color: "var(--console-muted)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4 p-4">
          {/* LEFT (3 cols): full annotated frame + person close-up crop below it. */}
          <div className="md:col-span-3 flex flex-col gap-3">
            <div>
              <div className="font-telemetry text-[9px] uppercase tracking-widest mb-1.5" style={{ color: "var(--console-muted)" }}>Snapshot</div>
              <AuthImage
                fetcher={ev.snapshot_path ? () => scenarioSnapshotUrl(SLUG, ev.snapshot_path) : null}
                deps={[ev.id, ev.snapshot_path]}
                className="w-full rounded border aspect-video"
                fit="contain"
                fallback={<div className="w-full aspect-video rounded border flex items-center justify-center" style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}><ImageOff className="h-5 w-5 text-zinc-600" /></div>}
              />
            </div>
            <div className="rounded border overflow-hidden" style={{ borderColor: "var(--console-border)" }}>
              <div className="px-3 py-1.5 font-telemetry text-[9px] uppercase tracking-widest" style={{ color: "var(--console-muted)", borderBottom: "1px solid var(--console-border)", background: "var(--console-raised)" }}>
                Person close-up
              </div>
              <AuthImage
                fetcher={cropPath ? () => scenarioSnapshotUrl(SLUG, cropPath) : null}
                deps={[ev.id, cropPath]}
                className="w-full max-h-[320px]"
                fit="contain"
                fallback={<div className="w-full h-32 flex items-center justify-center" style={{ background: "var(--console-raised)" }}><ImageOff className="h-5 w-5 text-zinc-600" /></div>}
              />
            </div>
          </div>
          {/* RIGHT (2 cols): badge row + item chips + metadata rows. */}
          <div className="md:col-span-2 flex flex-col gap-3">
            <div className="flex items-center gap-2 flex-wrap">
              {isViolation ? (
                <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/30">Violation</span>
              ) : (
                <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">Compliant</span>
              )}
              {missing.map((it) => (
                <ItemChip key={`m-${it}`} label={`No ${prettyItem(it)}`} tone="danger" />
              ))}
              {present.map((it) => (
                <ItemChip key={`p-${it}`} label={prettyItem(it)} tone="ok" />
              ))}
            </div>
            <div className="flex flex-col gap-1.5">
              {rows.map(([k, v]) => (
                <div key={k} className="flex items-start gap-2">
                  <div className="w-24 shrink-0 font-telemetry text-[9px] uppercase tracking-widest pt-0.5" style={{ color: "var(--console-muted)" }}>{k}</div>
                  <div className="flex-1 min-w-0 font-telemetry text-[11px] break-all" style={{ color: "var(--console-text)" }}>{v}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function EventsTab({ scenario }) {
  const scenarioId = scenario?.id;
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [detailEvent, setDetailEvent] = useState(null);

  // Operator-facing filter: just Missing vs Compliant. ppe_removed is folded into
  // "PPE Missing" (same label) so we don't list it as a separate confusing option.
  const eventTypeOptions = [
    { value: "ppe_missing", label: "PPE Missing" },
    { value: "ppe_compliant", label: "Compliant" },
  ];

  const [page, setPage] = useState(0);
  const [cameraId, setCameraId] = useState(ALL);
  const [eventType, setEventType] = useState(ALL);
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
    if (since) p.since = new Date(since).toISOString();
    if (until) p.until = new Date(until).toISOString();
    return p;
  }, [page, cameraId, eventType, since, until]);

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["scenario-events", SLUG, params],
    queryFn: () => listScenarioPluginEvents(SLUG, params),
    placeholderData: keepPreviousData,
  });

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const ackMutation = useMutation({
    mutationFn: (eventId) => acknowledgeEvent(eventId),
    onSuccess: () => {
      toast.success("Event acknowledged");
      qc.invalidateQueries({ queryKey: ["scenario-events", SLUG] });
    },
    onError: () => toast.error("Couldn't acknowledge event"),
  });

  const [selected, setSelected] = useState(() => new Set());
  const refreshEvents = () => qc.invalidateQueries({ queryKey: ["scenario-events", SLUG] });

  const toggleSel = (id) =>
    setSelected((prev) => {
      const n = new Set(prev);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  const allOnPageSelected = items.length > 0 && items.every((e) => selected.has(e.id));
  const toggleSelAll = () =>
    setSelected((prev) => {
      const n = new Set(prev);
      if (allOnPageSelected) items.forEach((e) => n.delete(e.id));
      else items.forEach((e) => n.add(e.id));
      return n;
    });

  const delMutation = useMutation({
    mutationFn: (eventId) => deleteScenarioPluginEvent(SLUG, eventId),
    onSuccess: () => { toast.success("Event deleted"); refreshEvents(); },
    onError: () => toast.error("Couldn't delete event"),
  });
  const bulkDelMutation = useMutation({
    mutationFn: (ids) => bulkDeleteScenarioPluginEvents(SLUG, { ids }),
    onSuccess: (r) => {
      toast.success(`Deleted ${r?.deleted ?? r?.count ?? "selected"} events`);
      setSelected(new Set());
      refreshEvents();
    },
    onError: () => toast.error("Bulk delete failed"),
  });

  const resetFilters = () => {
    setCameraId(ALL);
    setEventType(ALL);
    setSince("");
    setUntil("");
    setPage(0);
  };

  const onFilterChange = (setter) => (val) => {
    setter(val);
    setPage(0);
  };

  const hasFilters = cameraId !== ALL || eventType !== ALL || since || until;

  return (
    <div className="p-4 space-y-3 h-full flex flex-col min-h-0">
      <div className="flex flex-wrap items-end gap-2 rounded-lg border p-3 shrink-0" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
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
                <SelectItem key={c.camera_id} value={c.camera_id}>{c.camera_name || c.camera_id}</SelectItem>
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
              {eventTypeOptions.map((t) => (
                <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">From</label>
          <Input type="datetime-local" className="h-8 text-xs" value={since} onChange={(e) => { setSince(e.target.value); setPage(0); }} />
        </div>
        <div>
          <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">To</label>
          <Input type="datetime-local" className="h-8 text-xs" value={until} onChange={(e) => { setUntil(e.target.value); setPage(0); }} />
        </div>

        {hasFilters ? (
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={resetFilters}>
            <X className="h-3.5 w-3.5 mr-1" /> Clear
          </Button>
        ) : null}

        {selected.size > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-xs text-rose-400 hover:text-rose-300"
            disabled={bulkDelMutation.isPending}
            onClick={async () => {
              if (await confirm({
                title: `Delete ${selected.size} event(s)?`,
                description: "This permanently removes the selected events and their snapshots.",
                confirmText: "Delete",
                danger: true,
              })) {
                bulkDelMutation.mutate(Array.from(selected));
              }
            }}
          >
            {bulkDelMutation.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Trash2 className="h-3.5 w-3.5 mr-1" />}
            Delete {selected.size}
          </Button>
        )}

        <div className="ml-auto text-[11px] text-zinc-500 font-telemetry self-center">
          {total} event{total === 1 ? "" : "s"}
          {isFetching && <Loader2 className="inline h-3 w-3 ml-2 animate-spin text-zinc-400" />}
        </div>
      </div>

      <div className="rounded-lg border overflow-auto flex-1 min-h-0" style={{ borderColor: "var(--console-border)" }}>
        <table className="w-full text-left">
          <thead className="sticky top-0 z-10">
            <tr className="text-[10px] uppercase tracking-wider text-zinc-500 font-telemetry" style={{ background: "var(--console-raised)" }}>
              <th className="px-3 py-2 w-8">
                <input type="checkbox" checked={allOnPageSelected} onChange={toggleSelAll} className="cursor-pointer" style={{ accentColor: "var(--console-accent)" }} />
              </th>
              <th className="px-3 py-2 font-medium">Time</th>
              <th className="px-3 py-2 font-medium">Camera</th>
              <th className="px-3 py-2 font-medium">Event</th>
              <th className="px-3 py-2 font-medium">Worker</th>
              <th className="px-3 py-2 font-medium">Missing PPE</th>
              <th className="px-3 py-2 font-medium">Conf.</th>
              <th className="px-3 py-2 font-medium">Snapshot</th>
              <th className="px-3 py-2 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <tr key={i} className="border-t" style={{ borderColor: "var(--console-border)" }}>
                  <td colSpan={9} className="px-3 py-3">
                    <div className="h-5 rounded animate-pulse bg-zinc-800/60" />
                  </td>
                </tr>
              ))
            ) : isError ? (
              <tr>
                <td colSpan={9} className="px-3 py-12 text-center text-sm text-rose-400">Couldn't load events.</td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-3 py-16 text-center">
                  <Bell className="h-9 w-9 mx-auto text-zinc-600 mb-2" />
                  <p className="text-sm text-zinc-300">No compliance events</p>
                  <p className="text-xs text-zinc-500 mt-1">
                    {hasFilters ? "Try widening your filters." : "Events appear here as workers are checked for required PPE."}
                  </p>
                </td>
              </tr>
            ) : (
              items.map((ev) => (
                <tr key={ev.id} onClick={() => setDetailEvent(ev)} className="border-t hover:bg-white/[0.04] transition-colors cursor-pointer" style={{ borderColor: "var(--console-border)" }}>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.has(ev.id)} onChange={() => toggleSel(ev.id)} className="cursor-pointer" style={{ accentColor: "var(--console-accent)" }} />
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-xs text-zinc-300 font-telemetry whitespace-nowrap">{fmtTime(ev.triggered_at)}</span>
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-xs text-zinc-300">{camMap[ev.camera_id] || ev.camera_id || "—"}</span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium", typeBadgeClass(ev.event_type))}>
                      {prettyEventLabel(ev.event_type)}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-xs text-zinc-300 font-telemetry">{ev.worker_track_id != null ? `#${ev.worker_track_id}` : "—"}</span>
                  </td>
                  <td className="px-3 py-2"><ChipList items={ev.missing_items} tone="danger" /></td>
                  <td className="px-3 py-2">{ConfBadge(ev)}</td>
                  <td className="px-3 py-2"><SnapshotThumb ev={ev} /></td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <Button variant="ghost" size="sm" className="h-7 text-xs" disabled={ackMutation.isPending} onClick={(e) => { e.stopPropagation(); ackMutation.mutate(ev.id); }}>
                      <Check className="h-3.5 w-3.5 mr-1" /> Ack
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs text-rose-400 hover:text-rose-300"
                      disabled={delMutation.isPending}
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (await confirm({ title: "Delete this event?", confirmText: "Delete", danger: true })) {
                          delMutation.mutate(ev.id);
                        }
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-2">
          <span className="text-[11px] text-zinc-500 font-telemetry">Page {page + 1} / {totalPages}</span>
          <Button variant="outline" size="sm" className="h-8" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" className="h-8" disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      {detailEvent && (
        <EventDetailModal event={detailEvent} camMap={camMap} onClose={() => setDetailEvent(null)} />
      )}
    </div>
  );
}
