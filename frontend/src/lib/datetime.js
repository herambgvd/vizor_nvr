// Central date/time formatting that honors the operator-configured display
// timezone (Settings → Time & NTP). Every screen should format timestamps
// through these helpers instead of calling toLocale*/new Date directly, so a
// timezone change applies everywhere.
//
// The timezone is set once, app-wide, by useBranding (from /settings/public/
// branding). Until it loads we fall back to the browser's local zone.

let _displayTz = null; // null -> use the browser's local zone

export function setDisplayTimezone(tz) {
  _displayTz = tz && tz !== "UTC" ? tz : tz === "UTC" ? "UTC" : null;
}

export function getDisplayTimezone() {
  return _displayTz;
}

// Resolve options.timeZone, validating against the runtime so a bad tz never
// throws (falls back to local).
function tzOpt(extra = {}) {
  const tz = _displayTz;
  if (!tz) return extra;
  try {
    // Will throw if the runtime doesn't know this zone.
    new Intl.DateTimeFormat("en-GB", { timeZone: tz });
    return { ...extra, timeZone: tz };
  } catch {
    return extra;
  }
}

function toDate(value) {
  if (value == null || value === "") return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

// Full date + time, e.g. "21 Jun 2026, 00:14:37".
export function formatDateTime(value, { seconds = true } = {}) {
  const d = toDate(value);
  if (!d) return "—";
  return d.toLocaleString("en-GB", tzOpt({
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
    hour12: false,
  }));
}

// Time only, e.g. "00:14:37".
export function formatTime(value, { seconds = true } = {}) {
  const d = toDate(value);
  if (!d) return "—";
  return d.toLocaleTimeString("en-GB", tzOpt({
    hour: "2-digit", minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
    hour12: false,
  }));
}

// Date only, e.g. "21 Jun 2026".
export function formatDate(value) {
  const d = toDate(value);
  if (!d) return "—";
  return d.toLocaleDateString("en-GB", tzOpt({
    day: "2-digit", month: "short", year: "numeric",
  }));
}

// Short, e.g. "21/06, 00:14".
export function formatShort(value) {
  const d = toDate(value);
  if (!d) return "—";
  return d.toLocaleString("en-GB", tzOpt({
    day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }));
}
