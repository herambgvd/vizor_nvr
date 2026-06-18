// =============================================================================
// AI · Live tab — video-wall of cameras assigned to this scenario, each with
// the NVR's WebRTCPlayer (go2rtc, low-latency).
//
// For FRS, recent recognition events are polled every 3s from the FRS plugin's
// /live endpoint and overlaid per-camera as person-name + confidence badges.
// Other scenarios (suspect-search, PPE, …) render the same camera wall without
// the recognition overlay (they have no live per-person feed), so the Live tab
// is consistent across every scenario.
// =============================================================================

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ScanFace,
  VideoOff,
  UserCheck,
  ShieldAlert,
  UserX,
  Volume2,
  VolumeX,
} from "lucide-react";

import { WebRTCPlayer } from "../../../components/nvr/WebRTCPlayer";
import { getScenarioCameras, listFrsLive } from "../../../api/frs";
import { scenarioSnapshotUrl } from "../../../api/ai";
import {
  eventPersonName,
  eventTypeBadgeClass,
  confidenceBadgeClass,
  fmtConfidence,
} from "./frsShared";
import { cn } from "../../../lib/utils";

const LIVE_POLL_MS = 3000;
// How many recent recognitions to surface per camera overlay.
const MAX_OVERLAY_PER_CAM = 4;
// How long a freshly-seen event keeps its "new" pulse animation (ms).
const NEW_EVENT_HIGHLIGHT_MS = 2500;

// ---------------------------------------------------------------------------
// Lightweight Web Audio alert cues. A single AudioContext is created lazily on
// first use (after a user gesture / first event) and reused. Everything is
// wrapped so autoplay-policy or unsupported-browser failures never bubble up.
// ---------------------------------------------------------------------------
let _audioCtx = null;
function _getAudioCtx() {
  if (typeof window === "undefined") return null;
  if (!_audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    _audioCtx = new Ctx();
  }
  if (_audioCtx.state === "suspended") _audioCtx.resume().catch(() => {});
  return _audioCtx;
}

// Sharp alert — used for new unknown / spoof events the operator must notice.
function playAlertBeep() {
  try {
    const ctx = _getAudioCtx();
    if (!ctx) return;
    const t0 = ctx.currentTime;
    for (const [freq, at] of [[1000, t0], [700, t0 + 0.14]]) {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = "square";
      o.frequency.value = freq;
      g.gain.setValueAtTime(0.0001, at);
      g.gain.exponentialRampToValueAtTime(0.5, at + 0.005);
      g.gain.exponentialRampToValueAtTime(0.0001, at + 0.12);
      o.connect(g).connect(ctx.destination);
      o.start(at);
      o.stop(at + 0.13);
    }
  } catch {
    /* autoplay policy / unsupported — ignore */
  }
}

// Soft chirp — informational cue for a new recognized face.
function playSoftBeep() {
  try {
    const ctx = _getAudioCtx();
    if (!ctx) return;
    const at = ctx.currentTime;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = "sine";
    o.frequency.value = 880;
    g.gain.setValueAtTime(0.0001, at);
    g.gain.exponentialRampToValueAtTime(0.12, at + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, at + 0.1);
    o.connect(g).connect(ctx.destination);
    o.start(at);
    o.stop(at + 0.12);
  } catch {
    /* ignore */
  }
}

function OverlayIcon({ type }) {
  if (type === "spoof_detected") return <ShieldAlert className="h-3 w-3" />;
  if (type === "face_unknown") return <UserX className="h-3 w-3" />;
  return <UserCheck className="h-3 w-3" />;
}

function fmtFeedTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleTimeString(); } catch { return iso; }
}

// Live-feed face thumbnail — auth blob fetch of the event's face crop.
function FeedFace({ ev, slug }) {
  const [url, setUrl] = useState(null);
  const path = ev.attributes?.face_snapshot || ev.snapshot_path;
  useEffect(() => {
    if (!path || !slug || !path.startsWith("/snapshot")) { setUrl(null); return undefined; }
    let active = true; let obj = null;
    scenarioSnapshotUrl(slug, path).then((u) => {
      if (!active) { if (u) URL.revokeObjectURL(u); return; }
      obj = u; setUrl(u);
    });
    return () => { active = false; if (obj) URL.revokeObjectURL(obj); };
  }, [path, slug]);
  if (!url) {
    return (
      <div className="h-9 w-9 rounded shrink-0 flex items-center justify-center" style={{ background: "var(--console-raised)" }}>
        <ScanFace className="h-3.5 w-3.5" style={{ color: "var(--console-muted)" }} />
      </div>
    );
  }
  return <img src={url} alt="" className="h-9 w-9 rounded shrink-0 object-cover" />;
}

function CameraTile({ cam, events, newEventIds }) {
  const recent = (events || []).slice(0, MAX_OVERLAY_PER_CAM);

  return (
    <div
      className="relative aspect-video rounded-lg overflow-hidden border"
      style={{
        borderColor: "var(--console-border)",
        background: "var(--console-raised)",
      }}
    >
      <WebRTCPlayer
        streamId={cam.camera_id}
        cameraId={cam.camera_id}
        autoPlay
        muted
        className="rounded-none"
      />

      {/* ROI overlay — the configured region of interest (normalised points). */}
      {Array.isArray(cam.config?.roi) && cam.config.roi.length > 1 && (
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none z-20"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
        >
          <polygon
            points={cam.config.roi.map((p) => `${p[0] * 100},${p[1] * 100}`).join(" ")}
            fill="rgba(45,212,191,0.15)"
            stroke="var(--console-accent)"
            strokeWidth="0.4"
          />
        </svg>
      )}

      {/* Camera label — top */}
      <div className="absolute top-0 left-0 right-0 flex items-center justify-between gap-2 p-2 bg-gradient-to-b from-black/70 to-transparent pointer-events-none z-30">
        <span className="text-xs font-telemetry tracking-wider text-white/90 truncate">
          {cam.camera_name || cam.camera_id}
        </span>
        {cam.stream_state === "error" && (
          <span className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-rose-300">
            <VideoOff className="h-3 w-3" /> AI down
          </span>
        )}
      </div>

      {/* Recognition overlay — bottom, newest first */}
      {recent.length > 0 && (
        <div className="absolute bottom-0 left-0 right-0 flex flex-col gap-1 p-2 bg-gradient-to-t from-black/80 to-transparent pointer-events-none z-30">
          {recent.map((ev) => (
            <div
              key={ev.id}
              className={cn(
                "flex items-center gap-1.5 self-start max-w-full rounded-md border px-2 py-0.5 text-[11px] font-medium backdrop-blur-sm",
                eventTypeBadgeClass(ev.event_type),
                newEventIds?.has(ev.id) &&
                  "ring-1 ring-[var(--console-accent)] animate-[liveBadgeIn_300ms_ease-out]",
              )}
            >
              <OverlayIcon type={ev.event_type} />
              <span className="truncate">{eventPersonName(ev)}</span>
              <span
                className={cn(
                  "ml-auto rounded border px-1 text-[10px] font-telemetry",
                  confidenceBadgeClass(ev.confidence),
                )}
              >
                {fmtConfidence(ev.confidence)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function LiveTab({ scenario }) {
  const scenarioId = scenario?.id;

  const {
    data: cameras = [],
    isLoading: camsLoading,
    isError: camsError,
  } = useQuery({
    queryKey: ["frs", "scenario-cameras", scenarioId],
    queryFn: () => getScenarioCameras(scenarioId),
    enabled: !!scenarioId,
  });

  const enabledCameras = useMemo(
    () => cameras.filter((c) => c.enabled !== false),
    [cameras],
  );

  const cameraIds = useMemo(
    () => enabledCameras.map((c) => c.camera_id),
    [enabledCameras],
  );

  // Recognition overlay is FRS-only — other scenarios have no live per-person
  // feed, so skip the poll and render a plain camera wall.
  const isFrs = (scenario?.slug || "") === "frs";

  // Poll recent recognition events; group by camera for overlays.
  const { data: live } = useQuery({
    queryKey: ["frs", "live", cameraIds],
    queryFn: () => listFrsLive({ camera_id: cameraIds, limit: 100 }),
    enabled: isFrs && cameraIds.length > 0,
    refetchInterval: LIVE_POLL_MS,
    refetchIntervalInBackground: false,
  });

  const eventsByCamera = useMemo(() => {
    const map = {};
    (live?.items || []).forEach((ev) => {
      if (!ev.camera_id) return;
      (map[ev.camera_id] = map[ev.camera_id] || []).push(ev);
    });
    return map;
  }, [live]);

  // --- Engagement: new-event detection (pulse + audio cue) -----------------
  // Mute toggle for the audio cue (defaults on for FRS). Persisted lightly so
  // the operator's choice survives tab switches within the session.
  const [muted, setMuted] = useState(false);
  // Set of event ids currently flagged "new" (drives the badge pulse).
  const [newEventIds, setNewEventIds] = useState(() => new Set());
  // Ids seen in the previous poll — anything not here is genuinely new.
  const seenIdsRef = useRef(null);
  const mutedRef = useRef(muted);
  useEffect(() => {
    mutedRef.current = muted;
  }, [muted]);

  useEffect(() => {
    if (!isFrs) return;
    const items = live?.items || [];
    const currentIds = new Set(items.map((ev) => ev.id));

    // First successful poll just seeds the baseline — nothing is "new" yet,
    // so we don't flash/beep the entire backlog on mount.
    if (seenIdsRef.current === null) {
      seenIdsRef.current = currentIds;
      return;
    }

    const prev = seenIdsRef.current;
    const fresh = items.filter((ev) => ev.id != null && !prev.has(ev.id));
    seenIdsRef.current = currentIds;
    if (fresh.length === 0) return;

    // Pulse animation for the freshly-seen ids; cleared after a short window.
    setNewEventIds((cur) => {
      const next = new Set(cur);
      fresh.forEach((ev) => next.add(ev.id));
      return next;
    });
    const freshIds = fresh.map((ev) => ev.id);
    const timer = setTimeout(() => {
      setNewEventIds((cur) => {
        const next = new Set(cur);
        freshIds.forEach((id) => next.delete(id));
        return next;
      });
    }, NEW_EVENT_HIGHLIGHT_MS);

    // Audio cue — only for genuinely new events, only when not muted.
    if (!mutedRef.current) {
      const hasAlert = fresh.some(
        (ev) =>
          ev.event_type === "face_unknown" || ev.event_type === "spoof_detected",
      );
      const hasRecognized = fresh.some(
        (ev) => ev.event_type === "face_recognized",
      );
      if (hasAlert) playAlertBeep();
      else if (hasRecognized) playSoftBeep();
    }

    return () => clearTimeout(timer);
  }, [live, isFrs]);

  if (camsLoading) {
    return (
      <div className="p-4 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="aspect-video rounded-lg border animate-pulse"
            style={{
              borderColor: "var(--console-border)",
              background: "var(--console-raised)",
            }}
          />
        ))}
      </div>
    );
  }

  if (camsError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <VideoOff className="h-10 w-10 text-rose-400 mb-3" />
        <p className="text-sm text-zinc-300">Couldn't load assigned cameras.</p>
      </div>
    );
  }

  if (enabledCameras.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <ScanFace className="h-10 w-10 text-zinc-500 mb-3" />
        <p className="text-sm font-medium text-zinc-200">No cameras assigned</p>
        <p className="text-xs text-zinc-500 mt-1 max-w-sm">
          Assign cameras to this scenario from the Cameras tab to see the live
          camera wall here.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4">
      {/* Keyframes for the "new event" badge fade-in (scoped, no external CSS). */}
      <style>{`
        @keyframes liveBadgeIn {
          from { opacity: 0; transform: translateY(2px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      {/* FRS-only header row — audio mute toggle for recognition alerts. */}
      {isFrs && (
        <div className="flex items-center justify-end mb-3">
          <button
            type="button"
            onClick={() => setMuted((m) => !m)}
            aria-pressed={muted}
            title={muted ? "Unmute recognition alerts" : "Mute recognition alerts"}
            className="flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-telemetry tracking-wider uppercase transition-colors"
            style={{
              borderColor: "var(--console-border)",
              background: "var(--console-panel)",
              color: muted ? "var(--console-muted)" : "var(--console-accent)",
            }}
          >
            {muted ? (
              <VolumeX className="h-3.5 w-3.5" />
            ) : (
              <Volume2 className="h-3.5 w-3.5" />
            )}
            {muted ? "Muted" : "Alerts"}
          </button>
        </div>
      )}

      <div className="flex gap-4">
        {/* Camera wall */}
        <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {enabledCameras.map((cam) => (
            <CameraTile
              key={cam.id || cam.camera_id}
              cam={cam}
              events={eventsByCamera[cam.camera_id]}
              newEventIds={isFrs ? newEventIds : undefined}
            />
          ))}
        </div>

        {/* FRS live-events feed (right) — shows detections in real time so the
            operator can see recognition is happening. */}
        {isFrs && (
          <div
            className="w-[300px] shrink-0 hidden lg:flex flex-col rounded-lg border overflow-hidden self-start"
            style={{ borderColor: "var(--console-border)", background: "var(--console-panel)", maxHeight: "calc(100vh - 240px)" }}
          >
            <div className="px-3 py-2.5 flex items-center justify-between shrink-0" style={{ borderBottom: "1px solid var(--console-border)" }}>
              <span className="font-telemetry text-[10px] uppercase tracking-widest flex items-center gap-1.5" style={{ color: "var(--console-muted)" }}>
                <ScanFace className="h-3.5 w-3.5" style={{ color: "var(--console-accent)" }} /> Live events
              </span>
              <span className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
                {(live?.items || []).length}
              </span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {(live?.items || []).length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-2 py-12 px-4 text-center">
                  <ScanFace className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
                  <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                    Waiting for detections…
                  </span>
                </div>
              ) : (
                (live.items || []).map((ev) => (
                  <div
                    key={ev.id}
                    className={cn(
                      "flex items-center gap-2.5 px-3 py-2 border-b",
                      newEventIds?.has(ev.id) && "animate-[liveBadgeIn_300ms_ease-out]",
                    )}
                    style={{
                      borderColor: "var(--console-border)",
                      background: newEventIds?.has(ev.id) ? "rgba(45,212,191,0.06)" : "transparent",
                    }}
                  >
                    <FeedFace ev={ev} slug={scenario?.slug} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <OverlayIcon type={ev.event_type} />
                        <span className="font-telemetry text-[12px] truncate" style={{ color: "var(--console-text)" }}>
                          {eventPersonName(ev)}
                        </span>
                      </div>
                      <div className="font-telemetry text-[9px] uppercase tracking-widest truncate" style={{ color: "var(--console-muted)" }}>
                        {fmtFeedTime(ev.triggered_at)}
                      </div>
                    </div>
                    <span className={cn("rounded border px-1 text-[10px] font-telemetry shrink-0", confidenceBadgeClass(ev.confidence))}>
                      {fmtConfidence(ev.confidence)}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
