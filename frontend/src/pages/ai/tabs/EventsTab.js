// =============================================================================
// AI · Events tab — scenario-generic event log.
//
// Manifest-driven and works for ANY scenario. The event-type filter options are
// derived from scenario.event_types; the read endpoint + table columns are
// chosen by a per-slug column-config (COLUMN_CONFIGS), defaulting to a generic
// set. Snapshots load through the scenario snapshot proxy with auth.
//
// Endpoint mapping (read side):
//   frs  → plugin /events via listFrsEvents (rich person joins)
//   ppe  → plugin /events via the generic proxy
//   anpr → plugin /plates via the generic proxy (plate reads ARE the events)
//   any other → unified NVR event store filtered by source_service (slug)
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
  ScanFace,
  Bell,
  Loader2,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { formatDateTime } from "../../../lib/datetime";

import { listFrsEvents, getScenarioCameras } from "../../../api/frs";
import {
  listScenarioEvents,
  listScenarioPluginEvents,
  deleteScenarioPluginEvent,
  bulkDeleteScenarioPluginEvents,
  scenarioEventEndpoint,
  scenarioSnapshotUrl,
  photoImageUrl,
  deleteFrsEvent,
  bulkDeleteFrsEvents,
  submitFrsFeedback,
} from "../../../api/ai";
import { acknowledgeEvent, deleteEvent, bulkDeleteEvents } from "../../../api/events";
import { useConfirm } from "../../../components/ui/confirm";
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
    return formatDateTime(iso);
  } catch {
    return iso;
  }
}

// Friendly, operator-facing labels for non-FRS event types.
const EVENT_LABEL_OVERRIDES = {
  ppe_missing: "PPE Missing",
  ppe_removed: "PPE Restored",
  ppe_compliant: "Compliant",
  plate_read: "Plate Read",
  whitelist_hit: "Whitelist Hit",
  blacklist_hit: "Blacklist Hit",
};

// Pretty-label any scenario event_type slug (works for FRS, PPE, ANPR, future).
const prettyEventLabel = (slug) =>
  FRS_EVENT_LABEL[slug] ||
  EVENT_LABEL_OVERRIDES[slug] ||
  String(slug || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

// Non-FRS badge tint by event type.
function genericTypeBadgeClass(type) {
  switch (type) {
    case "ppe_compliant":
    case "whitelist_hit":
      return "border-emerald-500/40 bg-emerald-500/15 text-emerald-300";
    case "ppe_missing":
    case "blacklist_hit":
      return "border-rose-500/40 bg-rose-500/15 text-rose-300";
    case "ppe_removed":
      return "border-amber-500/40 bg-amber-500/15 text-amber-300";
    default:
      return "border-zinc-600/50 bg-zinc-700/30 text-zinc-300";
  }
}

function SnapshotThumb({ ev, slug }) {
  const [errored, setErrored] = useState(false);
  const [blobUrl, setBlobUrl] = useState(null);
  // Prefer the cropped detected face for the FRS table thumbnail; fall back to
  // the full-frame snapshot. Non-FRS scenarios only have snapshot_path.
  const path = ev.attributes?.face_snapshot || ev.snapshot_path;
  // Plugin-served snapshots ("/snapshot?...") are service-token gated, so a bare
  // <img> can't load them — fetch through the scenario proxy with auth + object
  // URL. Legacy rooted/static paths fall back to the direct URL builder.
  const isPluginSnap = typeof path === "string" && path.startsWith("/snapshot");

  useEffect(() => {
    if (!isPluginSnap || !slug || !path) return undefined;
    let active = true;
    let obj = null;
    scenarioSnapshotUrl(slug, path).then((u) => {
      if (!active) { if (u) URL.revokeObjectURL(u); return; }
      obj = u;
      setBlobUrl(u);
    });
    return () => { active = false; if (obj) URL.revokeObjectURL(obj); };
  }, [isPluginSnap, slug, path]);

  const url = isPluginSnap ? blobUrl : snapshotUrl(path);

  if (!path || errored || (isPluginSnap && !blobUrl)) {
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

// Authenticated <img> for any plugin-relative snapshot path or person photo.
// `fetcher` returns an object URL (revoked on unmount).
function AuthImage({ fetcher, deps, className, fallback }) {
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
  return <img src={url} alt="" className={className} style={{ objectFit: "cover" }} />;
}

// Small chips list for an array of items (e.g. missing PPE).
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

// List-hit badge for ANPR plate reads (whitelist green / blacklist red).
function ListHitBadge({ hit, label }) {
  if (!hit) return <span className="text-zinc-600 text-xs">—</span>;
  const isBlack = hit === "blacklist";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium",
        isBlack
          ? "border-rose-500/40 bg-rose-500/15 text-rose-300"
          : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
      )}
      title={label || hit}
    >
      {isBlack ? "Blacklist" : "Whitelist"}
    </span>
  );
}

// ── Per-scenario column configuration ──────────────────────────────────────
// Each config has: empty (icon + title + hint), and columns[] where each column
// is { key, header, headerAlign?, cell(ev, ctx) }. ctx = { slug, camMap }.
// A "select" checkbox column and an "actions" column are added by the table
// shell, so configs only declare the data columns.

const TypeChip = (ev, useFrsBadge) => (
  <span
    className={cn(
      "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium",
      useFrsBadge ? eventTypeBadgeClass(ev.event_type) : genericTypeBadgeClass(ev.event_type),
    )}
  >
    {prettyEventLabel(ev.event_type)}
  </span>
);

const ConfBadge = (ev) => (
  <span
    className={cn(
      "rounded border px-1.5 text-[10px] font-telemetry",
      confidenceBadgeClass(ev.confidence),
    )}
  >
    {fmtConfidence(ev.confidence)}
  </span>
);

const COLUMN_CONFIGS = {
  frs: {
    empty: {
      icon: ScanFace,
      title: "No recognition events",
      hint: "Events appear here as faces are recognized.",
    },
    columns: [
      { key: "time", header: "Time", cell: (ev) => (
        <span className="text-xs text-zinc-300 font-telemetry whitespace-nowrap">{fmtTime(ev.triggered_at)}</span>
      ) },
      { key: "camera", header: "Camera", cell: (ev, ctx) => (
        <span className="text-xs text-zinc-300">{ctx.camMap[ev.camera_id] || ev.camera_id || "—"}</span>
      ) },
      { key: "type", header: "Type", cell: (ev) => TypeChip(ev, true) },
      { key: "person", header: "Person / Conf.", cell: (ev) => (
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-200 truncate max-w-[140px]">{eventPersonName(ev)}</span>
          {ConfBadge(ev)}
        </div>
      ) },
      { key: "face", header: "Face", cell: (ev, ctx) => <SnapshotThumb ev={ev} slug={ctx.slug} /> },
      { key: "match", header: "Match", cell: (ev) => (
        ev.attributes?.matched_photo_id ? (
          <AuthImage
            fetcher={() => photoImageUrl(ev.attributes.matched_photo_id)}
            deps={[ev.attributes.matched_photo_id]}
            className="h-10 w-10 rounded border"
            fallback={<div className="h-10 w-10 rounded border flex items-center justify-center" style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}><ScanFace className="h-3.5 w-3.5 text-zinc-600" /></div>}
          />
        ) : <span className="text-zinc-600 text-xs">—</span>
      ) },
      { key: "bbox", header: "BBox", cell: (ev) => (
        <span className="text-[11px] text-zinc-400 font-telemetry whitespace-nowrap">{fmtBbox(ev.bbox)}</span>
      ) },
    ],
  },

  ppe: {
    empty: {
      icon: Bell,
      title: "No compliance events",
      hint: "Events appear here as workers are checked for required PPE.",
    },
    columns: [
      { key: "time", header: "Time", cell: (ev) => (
        <span className="text-xs text-zinc-300 font-telemetry whitespace-nowrap">{fmtTime(ev.triggered_at)}</span>
      ) },
      { key: "camera", header: "Camera", cell: (ev, ctx) => (
        <span className="text-xs text-zinc-300">{ctx.camMap[ev.camera_id] || ev.camera_id || "—"}</span>
      ) },
      { key: "type", header: "Event", cell: (ev) => TypeChip(ev, false) },
      { key: "worker", header: "Worker", cell: (ev) => (
        <span className="text-xs text-zinc-300 font-telemetry">
          {ev.worker_track_id != null ? `#${ev.worker_track_id}` : "—"}
        </span>
      ) },
      { key: "missing", header: "Missing PPE", cell: (ev) => (
        <ChipList items={ev.missing_items} tone="danger" />
      ) },
      { key: "conf", header: "Conf.", cell: (ev) => ConfBadge(ev) },
      { key: "snapshot", header: "Snapshot", cell: (ev, ctx) => <SnapshotThumb ev={ev} slug={ctx.slug} /> },
      { key: "bbox", header: "BBox", cell: (ev) => (
        <span className="text-[11px] text-zinc-400 font-telemetry whitespace-nowrap">{fmtBbox(ev.bbox)}</span>
      ) },
    ],
  },

  anpr: {
    empty: {
      icon: Bell,
      title: "No plate reads yet",
      hint: "Plate reads appear here as vehicles pass the camera.",
    },
    columns: [
      { key: "time", header: "Time", cell: (ev) => (
        <span className="text-xs text-zinc-300 font-telemetry whitespace-nowrap">{fmtTime(ev.triggered_at)}</span>
      ) },
      { key: "camera", header: "Camera", cell: (ev, ctx) => (
        <span className="text-xs text-zinc-300">{ctx.camMap[ev.camera_id] || ev.camera_id || "—"}</span>
      ) },
      { key: "plate", header: "Plate", cell: (ev) => (
        <span className="font-mono text-[15px] font-semibold tracking-wider text-zinc-100">
          {ev.plate || "—"}
        </span>
      ) },
      { key: "vehicle", header: "Vehicle", cell: (ev) => (
        <span className="text-xs text-zinc-300 capitalize">{ev.vehicle_type || "—"}</span>
      ) },
      { key: "direction", header: "Direction", cell: (ev) => (
        <span className="text-xs text-zinc-300 capitalize">{ev.direction || "—"}</span>
      ) },
      { key: "speed", header: "Speed", cell: (ev) => (
        <span className="text-xs text-zinc-300 font-telemetry whitespace-nowrap">
          {ev.speed_kmh != null ? `${Math.round(ev.speed_kmh)} km/h` : "—"}
        </span>
      ) },
      { key: "list", header: "List", cell: (ev) => (
        <ListHitBadge hit={ev.list_hit} label={ev.list_label} />
      ) },
      { key: "conf", header: "Conf.", cell: (ev) => ConfBadge(ev) },
      { key: "snapshot", header: "Snapshot", cell: (ev, ctx) => <SnapshotThumb ev={ev} slug={ctx.slug} /> },
    ],
  },
};

// Generic fallback for any scenario without a dedicated config.
const DEFAULT_COLUMN_CONFIG = {
  empty: {
    icon: Bell,
    title: "No events yet",
    hint: "Events appear here as this feature processes video.",
  },
  columns: [
    { key: "time", header: "Time", cell: (ev) => (
      <span className="text-xs text-zinc-300 font-telemetry whitespace-nowrap">{fmtTime(ev.triggered_at)}</span>
    ) },
    { key: "camera", header: "Camera", cell: (ev, ctx) => (
      <span className="text-xs text-zinc-300">{ctx.camMap[ev.camera_id] || ev.camera_id || "—"}</span>
    ) },
    { key: "type", header: "Type", cell: (ev) => TypeChip(ev, false) },
    { key: "conf", header: "Conf.", cell: (ev) => ConfBadge(ev) },
    { key: "snapshot", header: "Snapshot", cell: (ev, ctx) => <SnapshotThumb ev={ev} slug={ctx.slug} /> },
    { key: "bbox", header: "BBox", cell: (ev) => (
      <span className="text-[11px] text-zinc-400 font-telemetry whitespace-nowrap">{fmtBbox(ev.bbox)}</span>
    ) },
  ],
};

// Full-detail modal opened by clicking an event row.
function EventDetailModal({ event, slug, camMap, onClose }) {
  const isFrs = slug === "frs";
  const [verdict, setVerdict] = useState(null);
  const submitVerdict = async (isCorrect) => {
    setVerdict(isCorrect);
    try {
      await submitFrsFeedback({ event_id: event.id, is_correct: isCorrect,
        matched_person_id: event.person_id });
      toast.success(isCorrect ? "Marked correct" : "Marked wrong");
    } catch {
      toast.error("Feedback failed");
      setVerdict(null);
    }
  };
  if (!event) return null;
  const ev = event;
  const at = ev.attributes || {};
  const faceSnap = at.face_snapshot;
  const matchedPhotoId = at.matched_photo_id;
  const confPct = typeof ev.confidence === "number" ? `${(ev.confidence * 100).toFixed(1)}%` : "—";

  // Detail rows adapt to the scenario. FRS keeps its rich person/demographic
  // set; PPE/ANPR show their own meaningful fields.
  let rows;
  if (isFrs) {
    const gender = at.gender;
    const ageRange = at.age_range;
    const liveness = typeof at.liveness_score === "number" ? `${(at.liveness_score * 100).toFixed(0)}%` : null;
    rows = [
      ["Time", fmtTime(ev.triggered_at)],
      ["Type", prettyEventLabel(ev.event_type)],
      ["Camera", camMap[ev.camera_id] || ev.camera_id || "—"],
      ["Person", eventPersonName(ev)],
      ev.person_id ? ["Person ID", ev.person_id] : null,
      ["Confidence", confPct],
      gender ? ["Gender", `${gender}${typeof at.gender_confidence === "number" ? ` (${(at.gender_confidence * 100).toFixed(0)}%)` : ""}`] : null,
      ageRange ? ["Age", ageRange] : null,
      liveness ? ["Liveness", liveness] : null,
      ev.track_id ? ["Track", ev.track_id] : null,
      ["BBox", fmtBbox(ev.bbox)],
    ].filter(Boolean);
  } else if (slug === "anpr") {
    rows = [
      ["Time", fmtTime(ev.triggered_at)],
      ["Type", prettyEventLabel(ev.event_type)],
      ["Camera", camMap[ev.camera_id] || ev.camera_id || "—"],
      ["Plate", ev.plate || "—"],
      ev.vehicle_type ? ["Vehicle", ev.vehicle_type] : null,
      ev.direction ? ["Direction", ev.direction] : null,
      ev.speed_kmh != null ? ["Speed", `${Math.round(ev.speed_kmh)} km/h`] : null,
      ev.list_hit ? ["Watchlist", `${ev.list_hit}${ev.list_label ? ` · ${ev.list_label}` : ""}`] : null,
      ["Confidence", confPct],
      ev.n_frames != null ? ["Frames", ev.n_frames] : null,
      ["BBox", fmtBbox(ev.bbox)],
    ].filter(Boolean);
  } else if (slug === "ppe") {
    rows = [
      ["Time", fmtTime(ev.triggered_at)],
      ["Type", prettyEventLabel(ev.event_type)],
      ["Camera", camMap[ev.camera_id] || ev.camera_id || "—"],
      ev.worker_track_id != null ? ["Worker", `#${ev.worker_track_id}`] : null,
      Array.isArray(ev.missing_items) && ev.missing_items.length ? ["Missing", ev.missing_items.join(", ")] : null,
      Array.isArray(ev.present_items) && ev.present_items.length ? ["Present", ev.present_items.join(", ")] : null,
      ["Confidence", confPct],
      ["BBox", fmtBbox(ev.bbox)],
    ].filter(Boolean);
  } else {
    rows = [
      ["Time", fmtTime(ev.triggered_at)],
      ["Type", prettyEventLabel(ev.event_type)],
      ["Camera", camMap[ev.camera_id] || ev.camera_id || "—"],
      ["Confidence", confPct],
      ["BBox", fmtBbox(ev.bbox)],
    ];
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.7)" }} onClick={onClose}>
      <div className="w-full max-w-3xl rounded-lg flex flex-col" style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: "1px solid var(--console-border)" }}>
          <span className="font-telemetry text-[12px] font-semibold uppercase tracking-widest" style={{ color: "var(--console-text)" }}>Event details</span>
          <button type="button" onClick={onClose} className="h-7 w-7 inline-flex items-center justify-center rounded hover:opacity-70" style={{ color: "var(--console-muted)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4 p-4">
          {/* Full frame */}
          <div className="md:col-span-3">
            <div className="font-telemetry text-[9px] uppercase tracking-widest mb-1.5" style={{ color: "var(--console-muted)" }}>Snapshot</div>
            <AuthImage
              fetcher={ev.snapshot_path ? () => scenarioSnapshotUrl(slug, ev.snapshot_path) : null}
              deps={[ev.id, ev.snapshot_path]}
              className="w-full rounded border aspect-video"
              fallback={<div className="w-full aspect-video rounded border flex items-center justify-center" style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}><ImageOff className="h-5 w-5 text-zinc-600" /></div>}
            />
          </div>
          {/* Face + matched POI (FRS) + meta */}
          <div className="md:col-span-2 flex flex-col gap-3">
            {isFrs && (
              <div className="flex gap-3">
                <div className="flex-1">
                  <div className="font-telemetry text-[9px] uppercase tracking-widest mb-1.5" style={{ color: "var(--console-muted)" }}>Detected face</div>
                  <AuthImage
                    fetcher={faceSnap ? () => scenarioSnapshotUrl(slug, faceSnap) : null}
                    deps={[ev.id, faceSnap]}
                    className="w-full rounded border aspect-square"
                    fallback={<div className="w-full aspect-square rounded border flex items-center justify-center" style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}><ScanFace className="h-5 w-5 text-zinc-600" /></div>}
                  />
                </div>
                {matchedPhotoId && (
                  <div className="flex-1">
                    <div className="font-telemetry text-[9px] uppercase tracking-widest mb-1.5" style={{ color: "var(--console-accent)" }}>Matched POI</div>
                    <AuthImage
                      fetcher={() => photoImageUrl(matchedPhotoId)}
                      deps={[matchedPhotoId]}
                      className="w-full rounded border aspect-square"
                      fallback={<div className="w-full aspect-square rounded border flex items-center justify-center" style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}><ScanFace className="h-5 w-5 text-zinc-600" /></div>}
                    />
                  </div>
                )}
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              {rows.map(([k, v]) => (
                <div key={k} className="flex items-start gap-2">
                  <div className="w-24 shrink-0 font-telemetry text-[9px] uppercase tracking-widest pt-0.5" style={{ color: "var(--console-muted)" }}>{k}</div>
                  <div className="flex-1 min-w-0 font-telemetry text-[11px] break-all" style={{ color: "var(--console-text)" }}>{v}</div>
                </div>
              ))}
            </div>
            {/* Operator feedback — FRS only (was the recognition right?). */}
            {isFrs && ev.person_id && (
              <div className="flex items-center gap-2 pt-1">
                <button type="button" onClick={() => submitVerdict(true)}
                  className="flex-1 inline-flex items-center justify-center gap-1 font-telemetry text-[10px] uppercase tracking-widest px-2 py-1.5 rounded border"
                  style={{ background: verdict === true ? "rgba(16,185,129,0.15)" : "var(--console-raised)",
                           borderColor: verdict === true ? "var(--console-online)" : "var(--console-border)",
                           color: verdict === true ? "var(--console-online)" : "var(--console-muted)" }}>
                  <Check className="h-3 w-3" /> Correct
                </button>
                <button type="button" onClick={() => submitVerdict(false)}
                  className="flex-1 inline-flex items-center justify-center gap-1 font-telemetry text-[10px] uppercase tracking-widest px-2 py-1.5 rounded border"
                  style={{ background: verdict === false ? "rgba(239,68,68,0.15)" : "var(--console-raised)",
                           borderColor: verdict === false ? "var(--console-rec)" : "var(--console-border)",
                           color: verdict === false ? "var(--console-rec)" : "var(--console-muted)" }}>
                  <X className="h-3 w-3" /> Wrong
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function EventsTab({ scenario }) {
  const slug = scenario?.slug || "frs";
  const scenarioId = scenario?.id;
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [detailEvent, setDetailEvent] = useState(null);

  const isFrs = slug === "frs";
  // Plugin scenarios that own their event store + expose a delete endpoint.
  const isPluginOwned = slug === "ppe" || slug === "anpr";
  const columnConfig = COLUMN_CONFIGS[slug] || DEFAULT_COLUMN_CONFIG;
  const dataColCount = columnConfig.columns.length;
  // +2 for the select checkbox and the actions column.
  const totalColSpan = dataColCount + 2;

  // Event-type filter options come from the scenario's manifest (event_types),
  // so PPE shows ppe_missing/… and ANPR shows plate_read/… — not the FRS list.
  const eventTypeOptions = (
    Array.isArray(scenario?.event_types) && scenario.event_types.length
      ? scenario.event_types
      : FRS_EVENT_TYPES.map((t) => t.value)
  ).map((v) => ({ value: v, label: prettyEventLabel(v) }));

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

  // ANPR's read endpoint is /plates (not /events); it has no person_id filter.
  const isAnpr = slug === "anpr";
  const params = useMemo(() => {
    const p = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
    if (cameraId !== ALL) p.camera_id = cameraId;
    if (eventType !== ALL) p.event_type = eventType;
    // FRS reuses the text box for person_id; ANPR reuses it for a plate search.
    if (isFrs && personId.trim()) p.person_id = personId.trim();
    if (isAnpr && personId.trim()) p.plate = personId.trim();
    if (since) p.since = new Date(since).toISOString();
    if (until) p.until = new Date(until).toISOString();
    return p;
  }, [page, cameraId, eventType, personId, since, until, isFrs, isAnpr]);

  // FRS has a rich query endpoint (person joins etc); PPE/ANPR read their own
  // plugin store via the proxy; any other scenario reads the unified NVR store.
  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["scenario-events", slug, params],
    queryFn: () =>
      isFrs
        ? listFrsEvents(params)
        : isPluginOwned
          ? listScenarioPluginEvents(slug, params)
          : listScenarioEvents(slug, params),
    placeholderData: keepPreviousData,
  });

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const ackMutation = useMutation({
    mutationFn: (eventId) => acknowledgeEvent(eventId),
    onSuccess: () => {
      toast.success("Event acknowledged");
      qc.invalidateQueries({ queryKey: ["scenario-events", slug] });
      qc.invalidateQueries({ queryKey: ["frs", "events"] });
    },
    onError: () => toast.error("Couldn't acknowledge event"),
  });

  // ── Selection + delete ─────────────────────────────────────────────────────
  const [selected, setSelected] = useState(() => new Set());
  const refreshEvents = () =>
    qc.invalidateQueries({ queryKey: ["scenario-events", slug] });

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

  // Delete routes to the right store: FRS + PPE + ANPR own their events in the
  // plugin DB; any other scenario lives in the unified NVR event store.
  const delMutation = useMutation({
    mutationFn: (eventId) =>
      isFrs
        ? deleteFrsEvent(eventId)
        : isPluginOwned
          ? deleteScenarioPluginEvent(slug, eventId)
          : deleteEvent(eventId),
    onSuccess: () => { toast.success("Event deleted"); refreshEvents(); },
    onError: () => toast.error("Couldn't delete event"),
  });
  const bulkDelMutation = useMutation({
    mutationFn: (ids) =>
      isFrs
        ? bulkDeleteFrsEvents({ ids })
        : isPluginOwned
          ? bulkDeleteScenarioPluginEvents(slug, { ids })
          : bulkDeleteEvents({ event_ids: ids }),
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
    ((isFrs || isAnpr) && personId.trim()) ||
    since ||
    until;

  const EmptyIcon = columnConfig.empty.icon;
  const countNoun = isAnpr ? "read" : "event";

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
              {eventTypeOptions.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* FRS: filter by person. ANPR: filter by plate text. */}
        {isFrs && (
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
        )}
        {isAnpr && (
          <div className="w-44">
            <Input
              className="h-8 text-xs"
              placeholder="Plate contains…"
              value={personId}
              onChange={(e) => {
                setPersonId(e.target.value);
                setPage(0);
              }}
            />
          </div>
        )}

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

        {selected.size > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-xs text-rose-400 hover:text-rose-300"
            disabled={bulkDelMutation.isPending}
            onClick={async () => {
              if (await confirm({
                title: `Delete ${selected.size} ${countNoun}(s)?`,
                description: `This permanently removes the selected ${countNoun}s and their snapshots.`,
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
          {total} {countNoun}{total === 1 ? "" : "s"}
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
              <th className="px-3 py-2 w-8">
                <input type="checkbox" checked={allOnPageSelected} onChange={toggleSelAll}
                  className="cursor-pointer" style={{ accentColor: "var(--console-accent)" }} />
              </th>
              {columnConfig.columns.map((col) => (
                <th key={col.key} className="px-3 py-2 font-medium">{col.header}</th>
              ))}
              <th className="px-3 py-2 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <tr key={i} className="border-t" style={{ borderColor: "var(--console-border)" }}>
                  <td colSpan={totalColSpan} className="px-3 py-3">
                    <div className="h-5 rounded animate-pulse bg-zinc-800/60" />
                  </td>
                </tr>
              ))
            ) : isError ? (
              <tr>
                <td colSpan={totalColSpan} className="px-3 py-12 text-center text-sm text-rose-400">
                  Couldn't load {countNoun}s.
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={totalColSpan} className="px-3 py-16 text-center">
                  <EmptyIcon className="h-9 w-9 mx-auto text-zinc-600 mb-2" />
                  <p className="text-sm text-zinc-300">{columnConfig.empty.title}</p>
                  <p className="text-xs text-zinc-500 mt-1">
                    {hasFilters ? "Try widening your filters." : columnConfig.empty.hint}
                  </p>
                </td>
              </tr>
            ) : (
              items.map((ev) => (
                <tr
                  key={ev.id}
                  onClick={() => setDetailEvent(ev)}
                  className="border-t hover:bg-white/[0.04] transition-colors cursor-pointer"
                  style={{ borderColor: "var(--console-border)" }}
                >
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.has(ev.id)} onChange={() => toggleSel(ev.id)}
                      className="cursor-pointer" style={{ accentColor: "var(--console-accent)" }} />
                  </td>
                  {columnConfig.columns.map((col) => (
                    <td key={col.key} className="px-3 py-2">
                      {col.cell(ev, { slug, camMap })}
                    </td>
                  ))}
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {!isAnpr && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs"
                        disabled={ackMutation.isPending}
                        onClick={(e) => { e.stopPropagation(); ackMutation.mutate(ev.id); }}
                      >
                        <Check className="h-3.5 w-3.5 mr-1" /> Ack
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs text-rose-400 hover:text-rose-300"
                      disabled={delMutation.isPending}
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (await confirm({ title: `Delete this ${countNoun}?`, confirmText: "Delete", danger: true })) {
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

      {detailEvent && (
        <EventDetailModal
          event={detailEvent}
          slug={slug}
          camMap={camMap}
          onClose={() => setDetailEvent(null)}
        />
      )}
    </div>
  );
}
