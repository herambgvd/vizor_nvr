// =============================================================================
// AI · Tour tab (FRS) — cross-camera person timeline ("where/when seen").
// =============================================================================
// Pick a person (searchable via listPersons), then fetch their cross-camera
// timeline (GET /api/ai/frs/tour/timeline/{person_id}) and render it as a
// vertical timeline of sightings: camera / stream name, confidence %, snapshot,
// and time — newest-first.
//
// NVR stays thin — the timeline is assembled by the FRS scenario. This tab only
// resolves the person and renders the JSON the bridge returns.
// =============================================================================

import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Route,
  Search,
  Loader2,
  ImageOff,
  UserCircle2,
  Video,
  X,
  Eye,
  Camera,
  Clock,
} from "lucide-react";
import { format, formatDistanceToNowStrict } from "date-fns";

import { listPersons, personTimeline } from "../../../api/ai";
import { snapshotUrl } from "./frsShared";

const inputStyle = {
  background: "var(--console-raised)",
  border: "1px solid var(--console-border)",
  color: "var(--console-text)",
};

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return format(new Date(iso), "MMM d, HH:mm:ss");
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
  return s.length > 18 ? `${s.slice(0, 8)}…${s.slice(-6)}` : s;
}

// Small stat card matching the console aesthetic.
function StatCard({ icon: Icon, label, value, accent }) {
  return (
    <div
      className="rounded-lg border p-3 flex-1 min-w-[120px]"
      style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}
    >
      <div className="flex items-center justify-between">
        <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          {label}
        </span>
        <Icon className="h-3.5 w-3.5" style={{ color: accent || "var(--console-accent)" }} />
      </div>
      <div className="mt-1.5 font-telemetry text-[18px] font-semibold truncate" style={{ color: "var(--console-text)" }}>
        {value}
      </div>
    </div>
  );
}

// Best-effort snapshot thumbnail (placeholder on miss).
function EntryThumb({ snapshotKey }) {
  const [errored, setErrored] = useState(false);
  const url = snapshotUrl(snapshotKey);
  if (!url || errored) {
    return (
      <div
        className="h-14 w-20 rounded flex items-center justify-center shrink-0"
        style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
      >
        <ImageOff className="h-4 w-4" style={{ color: "var(--console-muted)" }} />
      </div>
    );
  }
  return (
    <img
      src={url}
      alt="snapshot"
      loading="lazy"
      onError={() => setErrored(true)}
      className="h-14 w-20 rounded object-cover shrink-0"
      style={{ border: "1px solid var(--console-border)" }}
    />
  );
}

// ---------------------------------------------------------------------------
// person picker
// ---------------------------------------------------------------------------

const PersonPicker = ({ onPick }) => {
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data, isFetching } = useQuery({
    queryKey: ["frs-persons", "tour", debounced],
    queryFn: () => listPersons({ limit: 20, search: debounced || undefined }),
    enabled: open,
  });
  const items = data?.items || [];

  return (
    <div className="relative w-[320px] max-w-full">
      <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5" style={{ color: "var(--console-muted)" }} />
      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        onFocus={() => setOpen(true)}
        placeholder="Search person by name / id"
        className="rounded pl-7 pr-2.5 py-1.5 font-telemetry text-[12px] outline-none w-full"
        style={inputStyle}
      />
      {open && (
        <div
          className="absolute z-30 mt-1 w-full rounded max-h-72 overflow-auto"
          style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
        >
          {isFetching ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="h-4 w-4 animate-spin" style={{ color: "var(--console-muted)" }} />
            </div>
          ) : items.length === 0 ? (
            <div className="px-3 py-4 font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
              No persons
            </div>
          ) : (
            items.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  onPick(p);
                  setOpen(false);
                  setSearch("");
                }}
                className="w-full text-left flex items-center gap-2 px-3 py-2 transition-colors hover:bg-white/[0.03]"
              >
                <UserCircle2 className="h-4 w-4 shrink-0" style={{ color: "var(--console-accent)" }} />
                <span className="font-telemetry text-[12px] truncate" style={{ color: "var(--console-text)" }}>
                  {p.full_name}
                </span>
                {p.external_id && (
                  <span className="font-telemetry text-[10px] uppercase tracking-widest ml-auto truncate" style={{ color: "var(--console-muted)" }}>
                    {p.external_id}
                  </span>
                )}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// timeline
// ---------------------------------------------------------------------------

const Timeline = ({ personId }) => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["frs-tour-timeline", personId],
    queryFn: () => personTimeline(personId),
    enabled: !!personId,
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

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--console-muted)" }} />
      </div>
    );
  }
  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 rounded" style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}>
        <ImageOff className="h-6 w-6" style={{ color: "var(--console-rec)" }} />
        <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-rec)" }}>
          Failed to load timeline
        </span>
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 rounded" style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}>
        <Route className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
        <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          No sightings recorded
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* stats summary */}
      <div className="flex flex-wrap gap-3">
        <StatCard icon={Eye} label="Total sightings" value={stats.total} accent="var(--console-accent)" />
        <StatCard icon={Camera} label="Cameras" value={stats.cameras} accent="var(--console-accent)" />
        <StatCard icon={Clock} label="Last seen" value={fmtRelative(stats.lastSeen)} accent="var(--console-muted)" />
      </div>

      {/* day-grouped timeline */}
      <div className="flex flex-col gap-5">
        {grouped.map(([day, dayEntries]) => (
          <div key={day || "unknown"}>
            <div
              className="sticky top-0 z-10 flex items-center justify-between px-1 py-1.5 mb-2 border-b"
              style={{ background: "var(--console-bg, #000)", borderColor: "var(--console-border)" }}
            >
              <span className="font-telemetry text-[11px] uppercase tracking-widest font-semibold" style={{ color: "var(--console-text)" }}>
                {fmtDay(dayEntries[0]?.when)}
              </span>
              <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                {dayEntries.length} sighting{dayEntries.length !== 1 ? "s" : ""}
              </span>
            </div>

            <div className="relative pl-5">
              {/* spine */}
              <div className="absolute left-[7px] top-1 bottom-1 w-px" style={{ background: "var(--console-border)" }} />
              <div className="flex flex-col gap-3">
                {dayEntries.map((e, i) => (
                  <div key={`${e.snapshotKey || e.cameraId}-${i}`} className="relative flex items-start gap-3">
                    {/* node */}
                    <span
                      className="absolute -left-5 top-5 h-2.5 w-2.5 rounded-full"
                      style={{ background: confColor(e.confidence), boxShadow: "0 0 0 3px var(--console-bg, #000)" }}
                    />
                    <div
                      className="flex items-center gap-3 flex-1 rounded p-3"
                      style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
                    >
                      <EntryThumb snapshotKey={e.snapshotKey} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <Video className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--console-accent)" }} />
                          <span className="font-telemetry text-[12px] font-semibold truncate" style={{ color: "var(--console-text)" }}>
                            {shortCam(e.cameraId)}
                          </span>
                        </div>
                        <div className="font-telemetry text-[10px] uppercase tracking-widest mt-1" style={{ color: "var(--console-muted)" }}>
                          {fmtTime(e.when)}
                          {e.eventType ? ` · ${String(e.eventType).replace(/_/g, " ")}` : ""}
                        </div>
                      </div>
                      <span
                        className="font-telemetry text-[11px] uppercase tracking-widest px-2 py-1 rounded border shrink-0"
                        style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: confColor(e.confidence) }}
                      >
                        {fmtConfidence(e.confidence)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ))}
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
    <div className="p-6 flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Route className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
        <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          Person Tour
        </span>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <PersonPicker onPick={setPerson} />
        {person && (
          <div
            className="inline-flex items-center gap-2 rounded px-3 py-1.5"
            style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
          >
            <UserCircle2 className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
            <span className="font-telemetry text-[12px] font-semibold" style={{ color: "var(--console-text)" }}>
              {person.full_name}
            </span>
            <button type="button" onClick={() => setPerson(null)} className="h-5 w-5 inline-flex items-center justify-center rounded hover:opacity-70" style={{ color: "var(--console-muted)" }}>
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>

      {person ? (
        <Timeline personId={person.id} />
      ) : (
        <div className="flex flex-col items-center justify-center gap-2 py-16 rounded" style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}>
          <Route className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
          <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            Pick a person to trace where & when they were seen
          </span>
        </div>
      )}
    </div>
  );
};

export default TourTab;
