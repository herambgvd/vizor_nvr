// =============================================================================
// Event labels — operator-facing friendly names for event types & severities.
// =============================================================================
// The backend emits raw snake_case event_type codes from many sources (motion,
// camera health, storage, ONVIF, and AI scenarios). Operators must never see
// raw codes like "ppe_violation" or "camera_credentials_invalid". This module
// is the single source of truth for turning a code into a clean label, used by
// the Events page, the live alarm dock, and the linkage rule builder.
// =============================================================================

// Friendly, operator-facing names keyed by raw event_type code.
export const EVENT_TYPE_LABELS = {
  // Motion / camera health
  motion_detected: "Motion Detected",
  video_loss: "Video Loss",
  camera_tamper: "Camera Tamper",
  camera_offline: "Camera Offline",
  camera_online: "Camera Online",
  camera_credentials_invalid: "Camera Sign-in Failed",
  recording_error: "Recording Error",
  recording_gap: "Recording Gap",

  // Storage / disk
  storage_low: "Storage Low",
  storage_error: "Storage Issue",
  storage_critical: "Storage Critical",
  disk_full: "Disk Full",
  disk_warning: "Disk Warning",
  disk_failure: "Disk Failure",

  // Network / system
  bandwidth_alert: "Bandwidth Alert",
  system_error: "System Error",
  cluster_failover: "System Failover",
  cluster_startup: "System Startup",
  manual: "Manual Event",
  test: "Test Event",

  // ONVIF-sourced
  digital_input_change: "Input Triggered",
  line_crossing: "Line Crossing",
  zone_intrusion: "Zone Intrusion",
  audio_alarm: "Audio Alarm",
  face_detected: "Face Detected",
  onvif_metadata: "Camera Event",

  // AI scenarios (FRS / PPE / analytics)
  face_recognized: "Face Recognized",
  person_identified: "Person Identified",
  recognized: "Face Recognized",
  face_unknown: "Unknown Face",
  spoof_detected: "Spoof Attempt",
  ppe_violation: "PPE Violation",
  ppe_compliant: "PPE Compliant",
  violation: "Safety Violation",
  crowd: "Crowd Alert",
  crowd_alert: "Crowd Alert",
  people_status: "Occupancy Update",
  object_detected: "Object Detected",
  loitering: "Loitering",
  intrusion: "Intrusion",
};

// Severity → operator label.
export const SEVERITY_LABELS = {
  info: "Info",
  warning: "Warning",
  critical: "Critical",
  alarm: "Alarm",
};

/**
 * Turn a raw event_type code into a clean operator-facing label.
 * Falls back to Title-Cased words so unknown/new codes still read cleanly
 * (e.g. "new_scenario_x" → "New Scenario X") rather than exposing raw codes.
 */
export function eventTypeLabel(type) {
  if (!type) return "Event";
  if (EVENT_TYPE_LABELS[type]) return EVENT_TYPE_LABELS[type];
  return String(type)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Friendly severity label. */
export function severityLabel(sev) {
  return SEVERITY_LABELS[sev] || "Info";
}
