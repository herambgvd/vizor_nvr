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
  ImageOff,
  Loader2,
  Info,
  X,
} from "lucide-react";

import { WebRTCPlayer } from "../../../components/nvr/WebRTCPlayer";
import { getScenarioCameras, listFrsLive } from "../../../api/frs";
import { scenarioSnapshotUrl, listScenarioPluginEvents, proxyScenario } from "../../../api/ai";
import {
  eventPersonName,
  eventTypeBadgeClass,
  confidenceBadgeClass,
  fmtConfidence,
} from "../scenarios/frs/frsShared";
import { cn } from "../../../lib/utils";
import { formatTime } from "../../../lib/datetime";

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

// Alarm throttle — bursts of new violations (a whole crew walking past a camera)
// would otherwise stack overlapping beeps. Gate the audible cue to at most once
// per ALARM_THROTTLE_MS regardless of how many fresh events arrive in one poll.
const ALARM_THROTTLE_MS = 1500;
let _lastAlarmAt = 0;
function playAlertBeepThrottled() {
  const now = Date.now();
  if (now - _lastAlarmAt < ALARM_THROTTLE_MS) return;
  _lastAlarmAt = now;
  playAlertBeep();
}

// Spoken voice announcement on a violation (client wants a voice saying e.g.
// "helmet not detected" instead of a plain beep). Uses the browser's built-in
// SpeechSynthesis — no audio files to manage, and the phrase is event-specific.
// Throttled with the same gate as the beep so a burst doesn't talk over itself.
let _lastSpeakAt = 0;
function speakPhrase(phrase) {
  if (!phrase) return;
  const synth = window.speechSynthesis;
  if (!synth) return false;
  const now = Date.now();
  if (now - _lastSpeakAt < ALARM_THROTTLE_MS) return true;
  _lastSpeakAt = now;
  try {
    synth.cancel(); // drop any queued utterance so we stay current
    const u = new SpeechSynthesisUtterance(phrase);
    u.rate = 1.0;
    u.pitch = 1.0;
    u.volume = 1.0;
    synth.speak(u);
    return true;
  } catch {
    return false;
  }
}

// Build the per-event spoken phrase. PPE names the missing items; other scenarios
// get a sensible default.
function violationPhrase(ev, slug) {
  if (slug === "ppe") {
    const missing = Array.isArray(ev?.missing_items) ? ev.missing_items : [];
    if (missing.length) {
      const items = missing.map((m) => String(m).replace(/_/g, " ")).join(" and ");
      return `${items} not detected`;
    }
    return "P P E not detected";
  }
  if (slug === "anpr") return "Blacklisted vehicle detected";
  if (slug === "frs") {
    if (ev?.event_type === "spoof_detected") return "Spoof detected";
    return "Unknown person detected";
  }
  return "Alert";
}

// FRS spoken announcement per the client's three cases:
//   recognized + within validity      -> "Authorized <name>, <group>"
//   recognized but expired / inactive  -> "Not Authorized. <reason>"
//   unknown / unregistered             -> "Unregistered person detected at <camera>"
function frsAnnouncePhrase(ev, cameraName) {
  const attrs = ev?.attributes || {};
  const authorized = ev?.authorized ?? attrs.authorized;
  const reason = ev?.auth_reason ?? attrs.auth_reason;
  const group = ev?.group_name ?? attrs.group_name;
  const cam = cameraName || ev?.camera_id || "camera";
  if (ev?.event_type === "spoof_detected") return "Spoof detected";
  if (ev?.event_type === "face_recognized") {
    const name = ev?.person_name || "person";
    if (authorized) {
      return group ? `Authorized ${name}, ${group}` : `Authorized ${name}`;
    }
    return reason ? `Not Authorized. ${reason}` : "Not Authorized";
  }
  // face_unknown / face_detected
  return `Unregistered person detected at ${cam}`;
}

// FRS speaks on EVERY fresh recognition (authorized + not), not only violations.
function isFrsAnnounceEvent(ev) {
  return ["face_recognized", "face_unknown", "spoof_detected"].includes(ev?.event_type);
}

// Does this fresh event warrant the loud alarm? Violation-ish across scenarios:
// PPE missing PPE, FRS unknown/spoof, ANPR blacklist hit. Anything else is a
// routine detection → soft chirp.
function isViolationEvent(ev) {
  const t = ev?.event_type;
  return (
    t === "ppe_missing" ||
    t === "face_unknown" ||
    t === "spoof_detected" ||
    t === "blacklist_hit"
  );
}

// Friendly fallback label for an arbitrary event_type ("ppe_missing" → "ppe missing").
function friendlyEventType(type) {
  if (!type) return "Detection";
  return String(type).replace(/_/g, " ");
}

function OverlayIcon({ type }) {
  if (type === "spoof_detected") return <ShieldAlert className="h-3 w-3" />;
  if (type === "face_unknown") return <UserX className="h-3 w-3" />;
  if (type === "face_recognized") return <UserCheck className="h-3 w-3" />;
  // Unknown / non-FRS event types — neutral dot so any scenario renders cleanly.
  return <span className="inline-block h-2 w-2 rounded-full bg-current opacity-80" />;
}

// Per-scenario display label for a live-event row. FRS keeps its proven
// person-name resolution; other scenarios surface their own primary field.
// Small authorized / not-authorized / unregistered chip for the FRS live feed.
function FrsAuthBadge({ ev }) {
  const attrs = ev?.attributes || {};
  const authorized = ev?.authorized ?? attrs.authorized;
  let text = "unregistered", color = "#fbbf24";
  if (ev?.event_type === "face_recognized") {
    if (authorized) { text = "authorized"; color = "#34d399"; }
    else { text = "not authorized"; color = "#f87171"; }
  } else if (ev?.event_type === "spoof_detected") {
    text = "spoof"; color = "#f87171";
  }
  return (
    <span className="font-telemetry text-[8px] uppercase tracking-widest px-1 py-0.5 rounded shrink-0"
      style={{ color, border: `1px solid ${color}55`, background: `${color}14` }}>
      {text}
    </span>
  );
}

function liveEventLabel(ev, slug) {
  if (!ev) return "Detection";
  if (slug === "frs") return eventPersonName(ev);
  if (slug === "anpr") return ev.plate || ev.label || friendlyEventType(ev.event_type);
  // PPE: name the actual PPE state — missing items, or "Compliant" — not the raw
  // "ppe missing" slug.
  if (slug === "ppe") {
    const missing = Array.isArray(ev.missing_items) ? ev.missing_items : [];
    if (ev.event_type === "ppe_compliant") return "Compliant";
    if (missing.length) return `No ${missing.join(", ")}`;
    return "PPE Missing";
  }
  return ev.label || friendlyEventType(ev.event_type);
}

function fmtFeedTime(iso) {
  if (!iso) return "—";
  try { return formatTime(iso); } catch { return iso; }
}

// Live-feed thumbnail — auth blob fetch of the event's snapshot. FRS prefers
// its face crop (attributes.face_snapshot); other scenarios use snapshot_path.
// Falls back to a scenario icon placeholder when no snapshot is available.
function FeedThumb({ ev, slug }) {
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

// Auth-blob snapshot image for the modal — fetches the bytes through the proxy
// (so the bearer token is applied) and shows a spinner / ImageOff fallback.
function ModalImage({ slug, path, className }) {
  const [url, setUrl] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    setUrl(null); setErr(false);
    if (!path || !slug || !path.startsWith("/snapshot")) { setErr(true); return undefined; }
    let active = true; let obj = null;
    scenarioSnapshotUrl(slug, path).then((u) => {
      if (!active) { if (u) URL.revokeObjectURL(u); return; }
      if (u) { obj = u; setUrl(u); } else setErr(true);
    }).catch(() => active && setErr(true));
    return () => { active = false; if (obj) URL.revokeObjectURL(obj); };
  }, [slug, path]);
  if (err) {
    return (
      <div className={cn(className, "flex items-center justify-center")} style={{ background: "var(--console-raised)" }}>
        <ImageOff className="h-5 w-5 text-zinc-600" />
      </div>
    );
  }
  if (!url) {
    return (
      <div className={cn(className, "flex items-center justify-center")} style={{ background: "var(--console-raised)" }}>
        <Loader2 className="h-4 w-4 animate-spin text-zinc-500" />
      </div>
    );
  }
  return <img src={url} alt="" className={className} style={{ objectFit: "contain" }} />;
}

// Generic live-event detail modal — shared across every scenario, so it stays
// lightweight: full annotated frame + person close-up crop (snapshot_path +
// "&crop=1") + the scenario's primary label + confidence / time / camera. FRS
// keeps its own rich modal elsewhere; this only backs the Live feed.
function LiveEventModal({ event, slug, camName, onClose }) {
  if (!event) return null;
  const ev = event;
  const path = ev.attributes?.face_snapshot || ev.snapshot_path;
  const cropPath = ev.snapshot_path
    ? `${ev.snapshot_path}${ev.snapshot_path.includes("?") ? "&" : "?"}crop=1`
    : null;
  const confPct = typeof ev.confidence === "number" ? `${(ev.confidence * 100).toFixed(1)}%` : "—";
  const missing = Array.isArray(ev.missing_items) ? ev.missing_items : [];
  const present = Array.isArray(ev.present_items) ? ev.present_items : [];
  const prettyItem = (it) => String(it).replace(/_/g, " ");
  const rows = [
    // PPE: the chips above already state the PPE status, so skip a redundant
    // "Label: ppe missing" row. Other scenarios show the person/plate label.
    ...(slug === "ppe" ? [] : [["Label", liveEventLabel(ev, slug)]]),
    ["Time", fmtFeedTime(ev.triggered_at)],
    ["Camera", camName || ev.camera_id || "—"],
    ["Confidence", confPct],
  ];

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
          <div className="md:col-span-3 flex flex-col gap-3">
            <div>
              <div className="font-telemetry text-[9px] uppercase tracking-widest mb-1.5" style={{ color: "var(--console-muted)" }}>Snapshot</div>
              <ModalImage slug={slug} path={path} className="w-full rounded border aspect-video" />
            </div>
            {cropPath && (
              <div className="rounded border overflow-hidden" style={{ borderColor: "var(--console-border)" }}>
                <div className="px-3 py-1.5 font-telemetry text-[9px] uppercase tracking-widest" style={{ color: "var(--console-muted)", borderBottom: "1px solid var(--console-border)", background: "var(--console-raised)" }}>
                  Person close-up
                </div>
                <ModalImage slug={slug} path={cropPath} className="w-full max-h-[320px]" />
              </div>
            )}
          </div>
          <div className="md:col-span-2 flex flex-col gap-3">
            {(missing.length > 0 || present.length > 0) && (
              <div className="flex items-center gap-2 flex-wrap">
                {missing.map((it) => (
                  <span key={`m-${it}`} className="text-[11px] px-2 py-0.5 rounded border bg-red-500/10 text-red-400 border-red-500/30">{`No ${prettyItem(it)}`}</span>
                ))}
                {present.map((it) => (
                  <span key={`p-${it}`} className="text-[11px] px-2 py-0.5 rounded border bg-emerald-500/10 text-emerald-400 border-emerald-500/30">{prettyItem(it)}</span>
                ))}
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
          </div>
        </div>
      </div>
    </div>
  );
}

// Worker-logs diagnostics modal — polls the plugin's /live/logs for this camera
// every 2s so an operator can watch the pipeline live (stream up/down, workers in
// view, violations, errors) and spot a real-time issue without shell access.
const LOG_LEVEL_COLOR = {
  error: "#f87171",
  warn: "#fbbf24",
  info: "var(--console-muted)",
};

function WorkerLogsModal({ slug, cameraId, cameraName, onClose }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const bodyRef = useRef(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const d = await proxyScenario(slug, "/live/logs", {
          params: { camera_id: cameraId },
          timeout: 8000,
        });
        if (alive) { setData(d); setErr(null); }
      } catch (e) {
        if (alive) setErr(e?.response?.status === 404 ? "Diagnostics not available for this scenario." : "Failed to load worker logs.");
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, [slug, cameraId]);

  // Auto-scroll to newest line.
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [data]);

  const stats = data?.stats || {};
  const running = data?.running;
  const logs = data?.logs || [];

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.7)" }} onClick={onClose}>
      <div className="w-full max-w-2xl max-h-[85vh] rounded-lg flex flex-col" style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 shrink-0" style={{ borderBottom: "1px solid var(--console-border)" }}>
          <div className="flex items-center gap-2">
            <span className="font-telemetry text-[12px] font-semibold uppercase tracking-widest" style={{ color: "var(--console-text)" }}>Worker logs</span>
            <span className="text-[11px] font-telemetry" style={{ color: "var(--console-muted)" }}>· {cameraName}</span>
            <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded"
              style={{ color: running ? "#34d399" : "#f87171", background: "var(--console-raised)" }}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: running ? "#34d399" : "#f87171" }} />
              {running ? "running" : "stopped"}
            </span>
          </div>
          <button type="button" onClick={onClose} className="h-7 w-7 inline-flex items-center justify-center rounded hover:opacity-70" style={{ color: "var(--console-muted)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* live stats row */}
        <div className="grid grid-cols-4 gap-2 px-4 py-3 shrink-0" style={{ borderBottom: "1px solid var(--console-border)" }}>
          {[
            ["Workers in view", stats.persons_last ?? "—"],
            ["Violations", stats.violations_total ?? "—"],
            ["Analyze FPS", stats.fps ?? "—"],
            ["Frames", stats.frames ?? "—"],
          ].map(([k, v]) => (
            <div key={k}>
              <div className="font-telemetry text-[9px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>{k}</div>
              <div className="font-telemetry text-[15px] font-semibold" style={{ color: "var(--console-text)" }}>{v}</div>
            </div>
          ))}
        </div>

        {/* log stream */}
        <div ref={bodyRef} className="flex-1 min-h-0 overflow-y-auto px-4 py-3 font-mono text-[11px] leading-relaxed">
          {err && <div style={{ color: "#f87171" }}>{err}</div>}
          {!err && logs.length === 0 && <div style={{ color: "var(--console-muted)" }}>Waiting for activity…</div>}
          {logs.map((l, i) => (
            <div key={i} className="flex gap-2 py-0.5">
              <span style={{ color: "var(--console-faint, #555)" }}>{fmtFeedTime(l.ts)}</span>
              <span style={{ color: LOG_LEVEL_COLOR[l.level] || "var(--console-muted)" }}>{l.msg}</span>
            </div>
          ))}
        </div>
        <div className="px-4 py-2 shrink-0 font-telemetry text-[10px]" style={{ borderTop: "1px solid var(--console-border)", color: "var(--console-muted)" }}>
          Live · refreshes every 2s {stats.last_frame_secs_ago != null ? `· last frame ${stats.last_frame_secs_ago}s ago` : ""}
        </div>
      </div>
    </div>
  );
}

function CameraTile({ cam, events, newEventIds, slug }) {
  // The bottom per-person recognition overlay is FRS-specific (shows enrolled
  // person names). Other scenarios (PPE/ANPR) have no per-person name to show on
  // the tile — their detections live in the Live-events feed + Events tab — so we
  // don't render the overlay (it was showing a meaningless "Unknown" badge).
  const recent = slug === "frs" ? (events || []).slice(0, MAX_OVERLAY_PER_CAM) : [];
  const [showLogs, setShowLogs] = useState(false);

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
        <div className="flex items-center gap-2 pointer-events-auto">
          {cam.stream_state === "error" && (
            <span className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-rose-300">
              <VideoOff className="h-3 w-3" /> AI down
            </span>
          )}
          {/* Worker-logs diagnostics — opens a live log panel for this camera. */}
          <button
            type="button"
            onClick={() => setShowLogs(true)}
            title="Worker logs"
            className="h-6 w-6 inline-flex items-center justify-center rounded-full bg-black/40 hover:bg-black/70 text-white/85 transition-colors"
          >
            <Info className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {showLogs && (
        <WorkerLogsModal
          slug={slug}
          cameraId={cam.camera_id}
          cameraName={cam.camera_name || cam.camera_id}
          onClose={() => setShowLogs(false)}
        />
      )}

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

  // Face-overlay-on-tile is FRS-specific (face boxes/names). Other scenarios
  // share the same live-events FEED but not the FRS tile overlay.
  const slug = scenario?.slug || "";
  const isFrs = slug === "frs";

  // Clicking a feed row opens a generic detail modal for that event.
  const [detailEvent, setDetailEvent] = useState(null);
  const camNameById = useMemo(() => {
    const m = {};
    cameras.forEach((c) => { m[c.camera_id] = c.camera_name || c.camera_id; });
    return m;
  }, [cameras]);

  // Poll recent events for the live feed — for EVERY scenario, not just FRS.
  // FRS keeps its proven /live path; other plugins read via their own
  // events/plates endpoint. Both are normalised to { items: [...] }.
  const { data: live } = useQuery({
    queryKey: ["ai", "live", slug, cameraIds],
    queryFn: async () => {
      if (isFrs) return listFrsLive({ camera_id: cameraIds, limit: 100 });
      const r = await listScenarioPluginEvents(slug, { camera_id: cameraIds, limit: 100 });
      return { items: r?.items || [] };
    },
    enabled: !!slug && cameraIds.length > 0,
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

    // Audio cue — only for genuinely new events, only when not muted. A
    // violation-ish event SPEAKS an event-specific phrase (e.g. "helmet not
    // detected") via the browser voice; falls back to the loud beep if speech
    // synthesis isn't available. Throttled to once per 1.5s so a burst doesn't
    // talk over itself. Routine detections → soft chirp.
    if (!mutedRef.current) {
      if (isFrs) {
        // FRS announces every fresh recognition (authorized / not-authorized /
        // unregistered) with a spoken phrase; soft chirp if nothing announceable.
        const ann = fresh.find(isFrsAnnounceEvent);
        if (ann) {
          const spoke = speakPhrase(frsAnnouncePhrase(ann, camNameById[ann.camera_id]));
          if (!spoke) playAlertBeepThrottled();
        } else {
          playSoftBeep();
        }
      } else {
        const violation = fresh.find(isViolationEvent);
        if (violation) {
          const spoke = speakPhrase(violationPhrase(violation, slug));
          if (!spoke) playAlertBeepThrottled();
        } else {
          playSoftBeep();
        }
      }
    }

    return () => clearTimeout(timer);
  }, [live, isFrs, slug, camNameById]);

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

      {/* Header row — audio mute toggle for live-event alerts (all scenarios). */}
      <div className="flex items-center justify-end mb-3">
          <button
            type="button"
            onClick={() => setMuted((m) => !m)}
            aria-pressed={muted}
            title={muted ? "Unmute detection alerts" : "Mute detection alerts"}
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

      <div className="flex gap-4">
        {/* Camera wall */}
        <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {enabledCameras.map((cam) => (
            <CameraTile
              key={cam.id || cam.camera_id}
              cam={cam}
              slug={slug}
              events={eventsByCamera[cam.camera_id]}
              newEventIds={isFrs ? newEventIds : undefined}
            />
          ))}
        </div>

        {/* Live-events feed (right) — shows detections in real time so the
            operator can see the scenario is working. Rendered for ALL scenarios. */}
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
                  <button
                    key={ev.id}
                    type="button"
                    onClick={() => setDetailEvent(ev)}
                    className={cn(
                      "w-full text-left flex items-center gap-2.5 px-3 py-2 border-b hover:bg-white/[0.04] transition-colors",
                      newEventIds?.has(ev.id) && "ring-1 ring-inset ring-[var(--console-accent)] animate-[liveBadgeIn_300ms_ease-out]",
                    )}
                    style={{
                      borderColor: "var(--console-border)",
                      background: newEventIds?.has(ev.id) ? "rgba(45,212,191,0.06)" : "transparent",
                    }}
                  >
                    <FeedThumb ev={ev} slug={slug} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <OverlayIcon type={ev.event_type} />
                        <span className="font-telemetry text-[12px] truncate" style={{ color: "var(--console-text)" }}>
                          {liveEventLabel(ev, slug)}
                        </span>
                        {isFrs && <FrsAuthBadge ev={ev} />}
                      </div>
                      <div className="font-telemetry text-[9px] uppercase tracking-widest truncate" style={{ color: "var(--console-muted)" }}>
                        {(camNameById[ev.camera_id] || ev.camera_id || "—")} · {fmtFeedTime(ev.triggered_at)}
                      </div>
                    </div>
                    <span className={cn("rounded border px-1 text-[10px] font-telemetry shrink-0", confidenceBadgeClass(ev.confidence))}>
                      {fmtConfidence(ev.confidence)}
                    </span>
                  </button>
                ))
              )}
            </div>
        </div>
      </div>

      {detailEvent && (
        <LiveEventModal
          event={detailEvent}
          slug={slug}
          camName={camNameById[detailEvent.camera_id]}
          onClose={() => setDetailEvent(null)}
        />
      )}
    </div>
  );
}
