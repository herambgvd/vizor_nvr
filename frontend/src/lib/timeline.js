// =============================================================================
// Timeline math — pure helpers for the multi-track playback timeline.
// Time is expressed as "seconds since local midnight" of the viewed date.
// A viewport is { start, end } in those seconds. No React here.
// =============================================================================

export const DAY_SECONDS = 86400;
export const MIN_SPAN = 300; // smallest zoom window: 5 minutes

// Backend writes naive UTC timestamps (datetime.utcnow()). Force a Z so the
// browser parses them as UTC; already-zoned strings are trusted as-is.
export function parseUtc(s) {
  if (!s) return new Date(NaN);
  if (/[Z+-]\d{2}:?\d{2}$|Z$/i.test(s)) return new Date(s);
  return new Date(`${s}Z`);
}

// Seconds from local midnight of `dateStr` (YYYY-MM-DD) for a UTC timestamp.
export function dayOffset(isoTime, dateStr) {
  const t = parseUtc(isoTime);
  if (isNaN(t.getTime())) return 0;
  const midnight = new Date(`${dateStr}T00:00:00`);
  return (t.getTime() - midnight.getTime()) / 1000;
}

// Seconds-since-midnight → HH:MM:SS.
export function fmtClock(s) {
  const total = Math.max(0, Math.floor(s));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const p = (n) => String(n).padStart(2, "0");
  return `${p(h)}:${p(m)}:${p(sec)}`;
}

// Clamp a viewport into [0, DAY_SECONDS] and enforce the minimum span.
export function clampView(view) {
  let { start, end } = view;
  if (end - start < MIN_SPAN) {
    const center = (start + end) / 2;
    start = center - MIN_SPAN / 2;
    end = center + MIN_SPAN / 2;
  }
  let span = end - start;
  if (span > DAY_SECONDS) span = DAY_SECONDS;
  if (start < 0) {
    start = 0;
    end = start + span;
  }
  if (end > DAY_SECONDS) {
    end = DAY_SECONDS;
    start = end - span;
  }
  if (start < 0) start = 0;
  return { start, end };
}

export function timeToPct(t, view) {
  const span = view.end - view.start;
  if (span <= 0) return 0;
  return ((t - view.start) / span) * 100;
}

export function pctToTime(pct, view) {
  const span = view.end - view.start;
  return view.start + (pct / 100) * span;
}

// Recording segments → positioned bars (percent), clipped to the viewport.
// Each segment: { id, start_time (ISO), duration (seconds) }.
export function segmentBars(segments, view, dateStr) {
  if (!Array.isArray(segments)) return [];
  const out = [];
  for (const s of segments) {
    const s0 = dayOffset(s.start_time, dateStr);
    const s1 = s0 + (s.duration || 0);
    const clippedStart = Math.max(s0, view.start);
    const clippedEnd = Math.min(s1, view.end);
    if (clippedEnd <= clippedStart) continue;
    const left = timeToPct(clippedStart, view);
    const width = timeToPct(clippedEnd, view) - left;
    out.push({ id: s.id, left, width });
  }
  return out;
}

// Events → positioned ticks (percent); out-of-view events dropped.
// Each event: { id, triggered_at (ISO), severity, event_type }.
export function eventTicks(events, view, dateStr) {
  if (!Array.isArray(events)) return [];
  const out = [];
  for (const e of events) {
    const t = dayOffset(e.triggered_at, dateStr);
    if (t < view.start || t > view.end) continue;
    out.push({
      id: e.id,
      left: timeToPct(t, view),
      severity: e.severity || "info",
      type: e.event_type || "",
    });
  }
  return out;
}

// Zoom the viewport by `factor` (<1 zoom in, >1 zoom out) around an anchor
// time, keeping the anchor at the same relative position.
export function zoomView(view, factor, anchorTime) {
  const span = view.end - view.start;
  const anchorPct = span > 0 ? (anchorTime - view.start) / span : 0.5;
  const newSpan = Math.min(DAY_SECONDS, Math.max(MIN_SPAN, span * factor));
  const start = anchorTime - anchorPct * newSpan;
  return clampView({ start, end: start + newSpan });
}

const STEP_CANDIDATES = [60, 300, 600, 1800, 3600, 7200, 14400];

// Smallest step that keeps the tick count at ~12 or fewer.
export function chooseStep(span) {
  for (const step of STEP_CANDIDATES) {
    if (span / step <= 12) return step;
  }
  return STEP_CANDIDATES[STEP_CANDIDATES.length - 1];
}

// Grid tick marks ({ t, label "HH:MM", left percent }) across the viewport.
export function gridTicks(view) {
  const span = view.end - view.start;
  const step = chooseStep(span);
  const first = Math.ceil(view.start / step) * step;
  const p = (n) => String(n).padStart(2, "0");
  const out = [];
  for (let t = first; t <= view.end; t += step) {
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    out.push({ t, label: `${p(h)}:${p(m)}`, left: timeToPct(t, view) });
  }
  return out;
}
