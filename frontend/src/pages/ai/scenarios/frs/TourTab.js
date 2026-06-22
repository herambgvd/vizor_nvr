// =============================================================================
// AI · Tour tab (FRS) — cross-camera person timeline ("where/when seen").
// =============================================================================
// Two-pane layout (mirrors vizor-app's TourPage):
//   LEFT  (col-span-3) — searchable, scrollable enrolled-person list. Each row:
//                        authenticated thumbnail + name + enrollment status +
//                        external id. Active person highlighted.
//   RIGHT (col-span-7) — selected-person header with a 3-stat grid (Sightings /
//                        Cameras / Last seen), then day-grouped sightings:
//                        sticky day header (date + count) + a grid of event
//                        cards (snapshot aspect-square + type/confidence badge +
//                        camera + time).
//
// NVR stays thin — the timeline is assembled by the FRS scenario. This tab only
// resolves the person and renders the JSON the bridge returns.
//
// NOTE: person thumbnails come from the auth-gated photo endpoint, so they are
// fetched as blobs via photoImageUrl and rendered as object URLs (revoked on
// unmount). Timeline snapshots use the static snapshotUrl helper.
// =============================================================================

import React, { useEffect, useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  Route,
  Search,
  Loader2,
  ImageOff,
  UserCircle2,
  Video,
  Eye,
  Camera,
  Clock,
} from "lucide-react";
import { format, formatDistanceToNowStrict } from "date-fns";
import { formatDateTime, formatTime } from "../../../../lib/datetime";

import { listPersons, personTimeline, photoImageUrl } from "../../../../api/ai";
import { snapshotUrl } from "./frsShared";

const inputStyle = {
  background: "var(--console-raised)",
  border: "1px solid var(--console-border)",
  color: "var(--console-text)",
};

const ENROLL_COLOR = {
  enrolled: "var(--console-accent)",
  pending: "#f59e0b",
  failed: "var(--console-rec)",
  unenrolled: "var(--console-muted)",
};

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return formatTime(iso);
  } catch {
    return iso;
  }
}

function fmtAbs(iso) {
  if (!iso) return "—";
  try {
    return formatDateTime(iso, { seconds: false });
  } catch {
    return iso;
  }
}

function fmtConfidence(conf) {
  if (conf == null || Number.isNaN(Number(conf))) return "—";
  return `${Math.round(Number(conf) * 100)}%`;
}

function confColor(conf) {
  if (conf == null) return "var(--console-muted)";
  if (conf >= 0.85) return "var(--console-accent)";
  if (conf >= 0.6) return "#f59e0b";
  return "var(--console-rec)";
}

// YYYY-MM-DD key for day grouping.
function dayKey(iso) {
  if (!iso) return "";
  try {
    return format(new Date(iso), "yyyy-MM-dd");
  } catch {
    return "";
  }
}

// Human day header (e.g. "Mon, Jun 16").
function fmtDay(iso) {
  if (!iso) return "—";
  try {
    return format(new Date(iso), "EEE, MMM d");
  } catch {
    return iso;
  }
}

// Short relative time (e.g. "3h ago").
function fmtRelative(iso) {
  if (!iso) return "—";
  try {
    return `${formatDistanceToNowStrict(new Date(iso))} ago`;
  } catch {
    return iso;
  }
}

// Short form of a camera id for compact display.
function shortCam(id) {
  if (id == null) return "—";
  const s = String(id);
  return s.length > 16 ? `${s.slice(0, 7)}…${s.slice(-5)}` : s;
}

// ---------------------------------------------------------------------------
// authenticated person avatar (person.thumbnail_key is a photo id)
// ---------------------------------------------------------------------------

const PersonAvatar = ({ photoId, className }) => {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    if (!photoId) {
      setUrl(null);
      return undefined;
    }
    let active = true;
    let objUrl = null;
    photoImageUrl(photoId).then((u) => {
      if (!active) {
        if (u) URL.revokeObjectURL(u);
        return;
      }
      objUrl = u;
      setUrl(u);
    });
    return () => {
      active = false;
      if (objUrl) URL.revokeObjectURL(objUrl);
    };
  }, [photoId]);

  if (!url) {
    return (
      <div className={className} style={{ background: "var(--console-raised)", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <UserCircle2 className="h-5 w-5" style={{ color: "var(--console-muted)" }} />
      </div>
    );
  }
  return <img src={url} alt="" className={className} style={{ objectFit: "cover" }} />;
};

// ---------------------------------------------------------------------------
// left sidebar — person row
// ---------------------------------------------------------------------------

const PersonRow = ({ person, active, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className="w-full text-left flex items-center gap-2.5 p-2 rounded transition-colors"
    style={{
      background: active ? "var(--console-raised)" : "transparent",
      border: `1px solid ${active ? "var(--console-accent)" : "transparent"}`,
    }}
  >
    <PersonAvatar photoId={person.thumbnail_key} className="h-10 w-10 rounded shrink-0" />
    <div className="flex-1 min-w-0">
      <div className="font-telemetry text-[12px] font-semibold truncate" style={{ color: "var(--console-text)" }}>
        {person.full_name}
      </div>
      <div className="flex items-center gap-1.5 mt-0.5">
        <span
          className="h-2 w-2 rounded-full shrink-0"
          style={{ background: ENROLL_COLOR[person.enrollment_status] || "var(--console-muted)" }}
        />
        <span className="font-telemetry text-[9px] uppercase tracking-widest truncate" style={{ color: "var(--console-muted)" }}>
          {person.enrollment_status || "unenrolled"}
          {person.external_id ? ` · ${person.external_id}` : ""}
        </span>
      </div>
    </div>
  </button>
);

// ---------------------------------------------------------------------------
// left sidebar — person list
// ---------------------------------------------------------------------------

const PersonList = ({ selectedId, onSelect }) => {
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data, isLoading } = useQuery({
    queryKey: ["frs-persons", "tour", debounced],
    queryFn: () => listPersons({ limit: 100, search: debounced || undefined }),
    placeholderData: keepPreviousData,
  });
  const items = data?.items || [];
  const total = data?.total ?? items.length;

  return (
    <div
      className="lg:col-span-3 rounded-lg flex flex-col min-h-0 overflow-hidden"
      style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
    >
      {/* header + search */}
      <div className="p-2 shrink-0 space-y-2" style={{ borderBottom: "1px solid var(--console-border)" }}>
        <div className="flex items-center gap-2 px-1">
          <UserCircle2 className="h-3.5 w-3.5" style={{ color: "var(--console-accent)" }} />
          <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            Persons · {total}
          </span>
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5" style={{ color: "var(--console-muted)" }} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search person by name"
            className="rounded pl-7 pr-2.5 py-1.5 font-telemetry text-[12px] outline-none w-full"
            style={inputStyle}
          />
        </div>
      </div>

      {/* scrollable list */}
      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-1">
        {isLoading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-4 w-4 animate-spin" style={{ color: "var(--console-muted)" }} />
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-10">
            <UserCircle2 className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
            <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
              No persons found
            </span>
          </div>
        ) : (
          items.map((p) => (
            <PersonRow key={p.id} person={p} active={selectedId === p.id} onClick={() => onSelect(p)} />
          ))
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// right pane — small stat
// ---------------------------------------------------------------------------

const Stat = ({ icon: Icon, label, value, accent }) => (
  <div className="rounded p-2" style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}>
    <div className="flex items-center justify-between">
      <span className="font-telemetry text-[9px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
        {label}
      </span>
      <Icon className="h-3 w-3" style={{ color: accent || "var(--console-accent)" }} />
    </div>
    <div className="mt-1 font-telemetry text-[15px] font-semibold truncate" style={{ color: "var(--console-text)" }}>
      {value}
    </div>
  </div>
);

// ---------------------------------------------------------------------------
// right pane — event card
// ---------------------------------------------------------------------------

const EventCard = ({ entry }) => {
  const [errored, setErrored] = useState(false);
  const url = snapshotUrl(entry.snapshotKey);
  const showImg = url && !errored;
  return (
    <div
      className="rounded overflow-hidden flex flex-col"
      style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
    >
      <div className="aspect-square relative" style={{ background: "var(--console-raised)" }}>
        {showImg ? (
          <img
            src={url}
            alt="snapshot"
            loading="lazy"
            onError={() => setErrored(true)}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <ImageOff className="h-5 w-5" style={{ color: "var(--console-muted)" }} />
          </div>
        )}
        <span
          className="absolute top-1 left-1 font-telemetry text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded"
          style={{ background: "rgba(0,0,0,0.65)", color: confColor(entry.confidence) }}
        >
          {entry.eventType ? String(entry.eventType).replace(/_/g, " ") : fmtConfidence(entry.confidence)}
        </span>
      </div>
      <div className="px-2 py-1.5 flex flex-col gap-0.5 min-w-0">
        <div className="flex items-center gap-1 min-w-0">
          <Video className="h-3 w-3 shrink-0" style={{ color: "var(--console-accent)" }} />
          <span className="font-telemetry text-[10px] font-semibold truncate" style={{ color: "var(--console-text)" }}>
            {shortCam(entry.cameraId)}
          </span>
        </div>
        <div className="flex items-center justify-between font-telemetry text-[9px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          <span>{fmtTime(entry.when)}</span>
          <span style={{ color: confColor(entry.confidence) }}>{fmtConfidence(entry.confidence)}</span>
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// right pane — timeline
// ---------------------------------------------------------------------------

const TimelinePane = ({ person }) => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["frs-tour-timeline", person?.id],
    queryFn: () => personTimeline(person.id),
    enabled: !!person,
  });

  const entries = data?.entries || [];

  // Normalize entry fields (documented shape + legacy fallbacks). Hooks must run
  // before any early return, so they live up here unconditionally.
  const normalized = useMemo(
    () =>
      entries.map((e) => ({
        cameraId: e.camera_id ?? e.stream_id ?? null,
        when: e.triggered_at || e.timestamp || null,
        confidence: e.confidence,
        eventType: e.event_type || null,
        snapshotKey: e.snapshot_path || e.snapshot_key || null,
      })),
    [entries],
  );

  const stats = useMemo(() => {
    const cams = new Set();
    let last = null;
    for (const e of normalized) {
      if (e.cameraId != null) cams.add(String(e.cameraId));
      if (e.when) {
        const t = new Date(e.when).getTime();
        if (!Number.isNaN(t) && (last == null || t > last)) last = t;
      }
    }
    return {
      total: normalized.length,
      cameras: cams.size,
      lastSeen: last != null ? new Date(last).toISOString() : null,
    };
  }, [normalized]);

  const grouped = useMemo(() => {
    const m = new Map();
    for (const e of normalized) {
      const k = dayKey(e.when);
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(e);
    }
    for (const arr of m.values()) {
      arr.sort((a, b) => {
        const ta = a.when ? new Date(a.when).getTime() : 0;
        const tb = b.when ? new Date(b.when).getTime() : 0;
        return tb - ta;
      });
    }
    return Array.from(m.entries()).sort((a, b) => (a[0] < b[0] ? 1 : -1));
  }, [normalized]);

  if (!person) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-2 p-6">
        <Route className="h-7 w-7" style={{ color: "var(--console-muted)" }} />
        <span className="font-telemetry text-[11px] uppercase tracking-widest text-center" style={{ color: "var(--console-muted)" }}>
          Pick a person to trace where &amp; when they were seen
        </span>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* selected-person header + stats */}
      <div className="px-4 py-3 shrink-0" style={{ borderBottom: "1px solid var(--console-border)" }}>
        <div className="flex items-center gap-2.5 min-w-0">
          <PersonAvatar photoId={person.thumbnail_key} className="h-9 w-9 rounded shrink-0" />
          <div className="min-w-0">
            <div className="font-telemetry text-[14px] font-semibold truncate" style={{ color: "var(--console-text)" }}>
              {person.full_name}
            </div>
            {person.external_id && (
              <div className="font-telemetry text-[10px] uppercase tracking-widest truncate" style={{ color: "var(--console-muted)" }}>
                {person.external_id}
              </div>
            )}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 mt-3">
          <Stat icon={Eye} label="Sightings" value={stats.total} accent="var(--console-accent)" />
          <Stat icon={Camera} label="Cameras" value={stats.cameras} accent="var(--console-accent)" />
          <Stat icon={Clock} label="Last seen" value={stats.lastSeen ? fmtRelative(stats.lastSeen) : "—"} accent="var(--console-muted)" />
        </div>
      </div>

      {/* scrollable day-grouped sightings */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-5">
        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--console-muted)" }} />
          </div>
        ) : isError ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16 rounded" style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}>
            <ImageOff className="h-6 w-6" style={{ color: "var(--console-rec)" }} />
            <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-rec)" }}>
              Failed to load timeline
            </span>
          </div>
        ) : entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16 rounded" style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}>
            <Route className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
            <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
              No sightings recorded
            </span>
          </div>
        ) : (
          grouped.map(([day, dayEntries]) => (
            <div key={day || "unknown"}>
              <div
                className="sticky top-0 z-10 flex items-center justify-between px-1 py-1.5 mb-2"
                style={{ background: "var(--console-panel)", borderBottom: "1px solid var(--console-border)" }}
              >
                <span className="font-telemetry text-[11px] uppercase tracking-widest font-semibold" style={{ color: "var(--console-text)" }}>
                  {fmtDay(dayEntries[0]?.when)}
                </span>
                <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                  {dayEntries.length} sighting{dayEntries.length !== 1 ? "s" : ""}
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
                {dayEntries.map((e, i) => (
                  <EventCard key={`${e.snapshotKey || e.cameraId}-${i}`} entry={e} />
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// tab
// ---------------------------------------------------------------------------

const TourTab = () => {
  const [person, setPerson] = useState(null);

  return (
    <div className="p-6 flex flex-col gap-4 h-full min-h-0">
      {/* header */}
      <div className="flex items-center gap-2 shrink-0">
        <Route className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
        <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          Person Tour
        </span>
      </div>

      {/* split: left person list · right timeline */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-10 gap-4 min-h-0 overflow-hidden">
        <PersonList selectedId={person?.id} onSelect={setPerson} />
        <div
          className="lg:col-span-7 rounded-lg flex flex-col min-h-0 overflow-hidden"
          style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
        >
          <TimelinePane person={person} />
        </div>
      </div>
    </div>
  );
};

export default TourTab;
