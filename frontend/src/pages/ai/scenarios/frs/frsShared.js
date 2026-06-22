// =============================================================================
// Shared helpers for the FRS workspace tabs (Live / Events / Attendance /
// Reports). Pure functions only — no React, no side effects.
// =============================================================================

import { BACKEND_URL } from "../../../../api/client";

// FRS recognition event types (mirrors the scenario catalog / query service).
export const FRS_EVENT_TYPES = [
  { value: "face_recognized", label: "Recognized" },
  { value: "face_unknown", label: "Unknown" },
  { value: "spoof_detected", label: "Spoof" },
  { value: "face_detected", label: "Detected" },
];

export const FRS_EVENT_LABEL = FRS_EVENT_TYPES.reduce((acc, t) => {
  acc[t.value] = t.label;
  return acc;
}, {});

// Tailwind classes per event type (badge style; matches console accents).
export function eventTypeBadgeClass(type) {
  switch (type) {
    case "face_recognized":
      return "border-emerald-500/40 bg-emerald-500/15 text-emerald-300";
    case "face_unknown":
      return "border-amber-500/40 bg-amber-500/15 text-amber-300";
    case "spoof_detected":
      return "border-rose-500/40 bg-rose-500/15 text-rose-300";
    default:
      return "border-zinc-600/50 bg-zinc-700/30 text-zinc-300";
  }
}

// Confidence → color band. Returns Tailwind classes for a small badge.
export function confidenceBadgeClass(conf) {
  if (conf == null) return "border-zinc-600/50 bg-zinc-700/30 text-zinc-400";
  if (conf >= 0.85) return "border-emerald-500/40 bg-emerald-500/15 text-emerald-300";
  if (conf >= 0.6) return "border-amber-500/40 bg-amber-500/15 text-amber-300";
  return "border-rose-500/40 bg-rose-500/15 text-rose-300";
}

export function fmtConfidence(conf) {
  if (conf == null || Number.isNaN(Number(conf))) return "—";
  return `${Math.round(Number(conf) * 100)}%`;
}

// Resolve a person display name from an event row: prefer the joined
// attributes.person_name / title, fall back to a short person_id, else Unknown.
export function eventPersonName(ev) {
  if (!ev) return "Unknown";
  const attrName = ev.attributes?.person_name || ev.attributes?.name;
  if (attrName) return attrName;
  if (ev.event_type === "face_unknown") return "Unknown";
  if (ev.event_type === "spoof_detected") return "Spoof attempt";
  if (ev.person_id) return `Person ${String(ev.person_id).slice(0, 8)}`;
  return "Unknown";
}

// Build a servable URL for an event snapshot. snapshot_path may be a rooted
// static path ("/thumbnails/..") or a bare storage key.
export function snapshotUrl(snapshotPath) {
  if (!snapshotPath) return null;
  if (/^https?:\/\//i.test(snapshotPath)) return snapshotPath;
  if (snapshotPath.startsWith("/")) return `${BACKEND_URL}${snapshotPath}`;
  return `${BACKEND_URL}/thumbnails/${snapshotPath}`;
}

// Format a bbox object {x,y,w,h} for compact display.
export function fmtBbox(bbox) {
  if (!bbox || typeof bbox !== "object") return "—";
  const { x, y, w, h } = bbox;
  if ([x, y, w, h].some((v) => v == null)) return "—";
  const r = (v) => (Number(v) <= 1 ? Number(v).toFixed(2) : Math.round(Number(v)));
  return `${r(x)},${r(y)} ${r(w)}×${r(h)}`;
}

// Build a camera_id → name map from the scenario-cameras assignment list.
export function cameraNameMap(scenarioCameras) {
  const m = {};
  (scenarioCameras || []).forEach((c) => {
    if (c.camera_id) m[c.camera_id] = c.camera_name || c.camera_id;
  });
  return m;
}
