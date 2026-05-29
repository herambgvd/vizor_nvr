# NVR UX Plan 2 — Playback Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-track slider in the Playback page with a zoomable, multi-track scrubbing timeline (one track per camera, recording bars + event ticks, draggable playhead, range export) inside the control-room shell.

**Architecture:** A new pure-JS module `lib/timeline.js` holds all viewport/time/pixel math (TDD-tested, timezone-independent). The existing `CameraCell` synchronized video player is extracted into its own component and reused unchanged. New presentational components `TimelineTrack` (one camera row) and `MultiTimeline` (ruler + stacked tracks + playhead + zoom + seek) compose into a new `PlaybackConsole` page. The shell `CameraTree` becomes the source of the playback review set via a new `playbackCameras` UI pref. Old `MultiPlayback` is retired once `PlaybackConsole` is routed in.

**Tech Stack:** React 18, @tanstack/react-query, react-router-dom v6, date-fns, lucide-react, Tailwind + console theme tokens, Jest (via `npx craco test`). Recordings/events API clients already exist (`src/api/recordings.js`, `src/api/events.js`).

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/src/lib/timeline.js` (create) | Pure helpers: `parseUtc`, `dayOffset`, `fmtClock`, `clampView`, `timeToPct`, `pctToTime`, `segmentBars`, `eventTicks`, `zoomView`, `chooseStep`, `gridTicks`. No React. |
| `frontend/src/lib/timeline.test.js` (create) | Jest tests for every helper. |
| `frontend/src/components/playback/CameraCell.js` (create) | The synchronized recording `<video>` cell, extracted verbatim from `MultiPlayback.js` and re-pointed at `lib/timeline`. Exposes `play/pause/playbackRate/getCurrentDayOffset/seekTo` via ref. |
| `frontend/src/components/playback/TimelineTrack.js` (create) | One camera's timeline row: background track + recording bars + event ticks. Pure presentational. |
| `frontend/src/components/playback/MultiTimeline.js` (create) | Ruler (grid ticks), stacked `TimelineTrack` rows, draggable playhead, click/drag-to-seek, zoom (buttons + wheel), in/out range selection. |
| `frontend/src/pages/PlaybackConsole.js` (create) | New Playback page: composes `CameraCell` grid + `MultiTimeline` + transport/date/speed/export. Reads review set from `playbackCameras` pref; seeds from `?camera=`. |
| `frontend/src/hooks/useUiPrefs.js` (modify) | Add `playbackCameras: []` to `DEFAULTS`. |
| `frontend/src/components/shell/ControlRoomLayout.js` (modify) | Route-aware tree activation: on `/playback` toggle a camera in `playbackCameras`; on `/` keep `fillFirstEmpty`. |
| `frontend/src/App.js` (modify) | Lazy-import `PlaybackConsole`; route `/playback` and `/playback/multi` to it; drop `MultiPlayback`. |
| `frontend/src/pages/MultiPlayback.js` (delete in Task 8) | Superseded by `PlaybackConsole`. |

---

## Task 1: Timeline math helpers (`lib/timeline.js`)

**Files:**
- Create: `frontend/src/lib/timeline.js`
- Test: `frontend/src/lib/timeline.test.js`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/timeline.test.js`:

```js
import {
  DAY_SECONDS,
  MIN_SPAN,
  parseUtc,
  dayOffset,
  fmtClock,
  clampView,
  timeToPct,
  pctToTime,
  segmentBars,
  eventTicks,
  zoomView,
  chooseStep,
  gridTicks,
} from "./timeline";

const DATE = "2026-05-29";
const view = { start: 0, end: DAY_SECONDS };

test("parseUtc appends Z to naive timestamps", () => {
  expect(parseUtc("2026-05-29T01:00:00").getTime()).toBe(
    new Date("2026-05-29T01:00:00Z").getTime(),
  );
});

test("dayOffset advances one hour for a one-hour-later timestamp", () => {
  const a = dayOffset("2026-05-29T04:00:00", DATE);
  const b = dayOffset("2026-05-29T05:00:00", DATE);
  expect(b - a).toBe(3600);
});

test("fmtClock formats seconds-since-midnight as HH:MM:SS", () => {
  expect(fmtClock(3661)).toBe("01:01:01");
  expect(fmtClock(0)).toBe("00:00:00");
});

test("clampView enforces the minimum span", () => {
  const v = clampView({ start: 1000, end: 1100 });
  expect(v.end - v.start).toBeCloseTo(MIN_SPAN);
});

test("clampView keeps the window inside the day", () => {
  const v = clampView({ start: 86000, end: 90000 });
  expect(v.end).toBe(DAY_SECONDS);
  expect(v.start).toBeCloseTo(DAY_SECONDS - 4000);
});

test("timeToPct/pctToTime are inverse", () => {
  expect(timeToPct(0, view)).toBe(0);
  expect(timeToPct(DAY_SECONDS, view)).toBe(100);
  expect(pctToTime(timeToPct(3600, view), view)).toBeCloseTo(3600);
});

test("segmentBars positions and clips a recording segment", () => {
  const off = dayOffset("2026-05-29T10:00:00", DATE);
  const segs = [{ id: "a", start_time: "2026-05-29T10:00:00", duration: 3600 }];
  const bars = segmentBars(segs, view, DATE);
  expect(bars).toHaveLength(1);
  expect(bars[0].id).toBe("a");
  expect(bars[0].left).toBeCloseTo(timeToPct(off, view));
  expect(bars[0].width).toBeCloseTo(
    timeToPct(off + 3600, view) - timeToPct(off, view),
  );
  // A window after the segment ends yields no bar.
  expect(segmentBars(segs, { start: off + 7200, end: off + 10000 }, DATE)).toHaveLength(0);
});

test("eventTicks positions in-view events and drops out-of-view ones", () => {
  const off = dayOffset("2026-05-29T10:00:00", DATE);
  const events = [
    { id: "e1", triggered_at: "2026-05-29T10:00:00", severity: "alarm", event_type: "motion_detected" },
  ];
  const ticks = eventTicks(events, view, DATE);
  expect(ticks).toHaveLength(1);
  expect(ticks[0].severity).toBe("alarm");
  expect(ticks[0].left).toBeCloseTo(timeToPct(off, view));
  expect(eventTicks(events, { start: off + 10, end: off + 20 }, DATE)).toHaveLength(0);
});

test("zoomView zooms in around an anchor and clamps to MIN_SPAN", () => {
  const z = zoomView(view, 0.5, 43200);
  expect(z.end - z.start).toBeCloseTo(43200);
  expect((z.start + z.end) / 2).toBeCloseTo(43200);
  const zin = zoomView(view, 0.0001, 43200);
  expect(zin.end - zin.start).toBeCloseTo(MIN_SPAN);
});

test("chooseStep picks a readable tick step for the span", () => {
  expect(chooseStep(DAY_SECONDS)).toBe(7200);
  expect(chooseStep(3600)).toBe(300);
  expect(chooseStep(MIN_SPAN)).toBe(60);
});

test("gridTicks spans the viewport with HH:MM labels", () => {
  const ticks = gridTicks(view);
  expect(ticks[0]).toMatchObject({ t: 0, label: "00:00" });
  expect(ticks.some((x) => x.label === "12:00")).toBe(true);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && CI=true npx craco test src/lib/timeline.test.js --watchAll=false`
Expected: FAIL — `Cannot find module './timeline'`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/timeline.js`:

```js
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && CI=true npx craco test src/lib/timeline.test.js --watchAll=false`
Expected: PASS — 12 tests passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/timeline.js frontend/src/lib/timeline.test.js
git commit -m "feat(playback): add tested timeline math helpers"
```

---

## Task 2: Extract `CameraCell` into its own component

The synchronized recording player currently lives inline in `MultiPlayback.js` (lines 64–262). Extract it verbatim into a reusable component and re-point its time math at `lib/timeline`. `MultiPlayback` keeps working by importing it.

**Files:**
- Create: `frontend/src/components/playback/CameraCell.js`
- Modify: `frontend/src/pages/MultiPlayback.js`

- [ ] **Step 1: Create the extracted component**

Create `frontend/src/components/playback/CameraCell.js`:

```js
// =============================================================================
// CameraCell — one synchronized recording player.
// Fetches a camera's segments for a date, plays them back-to-back, and exposes
// play/pause/playbackRate/getCurrentDayOffset/seekTo via ref so a parent can
// scrub many cameras on one shared timeline.
// =============================================================================

import React, {
  useRef, useState, useCallback, useEffect, useImperativeHandle,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { Video, X } from "lucide-react";
import { cn } from "../../lib/utils";
import { dayOffset } from "../../lib/timeline";
import { parseUtc } from "../../lib/timeline";
import api, { BACKEND_URL } from "../../api/client";

const CameraCell = React.forwardRef(function CameraCell(
  { camera, date, className },
  ref
) {
  const videoRef = useRef(null);
  const segmentsRef = useRef([]);
  const currentSegIdxRef = useRef(0);
  const pendingSeekRef = useRef(null);
  const [currentSegIdx, setCurrentSegIdx] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [noRecording, setNoRecording] = useState(false);
  const [totalSegments, setTotalSegments] = useState(0);

  const { data: recordings } = useQuery({
    queryKey: ["multi-recordings", camera?.id, date],
    queryFn: () =>
      api.get("/recordings", {
        params: {
          camera_id: camera.id,
          start_after: `${date}T00:00:00`,
          end_before: `${date}T23:59:59`,
          limit: 500,
        },
      }).then((r) => r.data),
    enabled: !!camera,
    staleTime: 30_000,
  });

  const getDayOffset = useCallback(
    (isoTime) => dayOffset(isoTime, date),
    [date]
  );

  useEffect(() => {
    if (!recordings) return;
    const sorted = [...recordings].sort(
      (a, b) => parseUtc(a.start_time) - parseUtc(b.start_time)
    );
    segmentsRef.current = sorted;
    setTotalSegments(sorted.length);
    setNoRecording(sorted.length === 0);
    currentSegIdxRef.current = 0;
    setCurrentSegIdx(0);
    setLoaded(false);
  }, [recordings]);

  useEffect(() => {
    const seg = segmentsRef.current[currentSegIdx];
    if (!seg || !videoRef.current) return;

    const token = localStorage.getItem("nvr_token") || "";
    videoRef.current.src = `${BACKEND_URL}/api/recordings/${seg.id}/download?token=${token}`;
    videoRef.current.load();

    const pending = pendingSeekRef.current;
    if (pending != null) {
      pendingSeekRef.current = null;
      const applySeek = () => {
        if (videoRef.current) videoRef.current.currentTime = pending;
      };
      videoRef.current.addEventListener("loadedmetadata", applySeek, { once: true });
    }
  }, [currentSegIdx, totalSegments]);

  const handleEnded = useCallback(() => {
    const next = currentSegIdxRef.current + 1;
    if (next < segmentsRef.current.length) {
      currentSegIdxRef.current = next;
      setCurrentSegIdx(next);
      setTimeout(() => videoRef.current?.play().catch(() => {}), 50);
    }
  }, []);

  useImperativeHandle(ref, () => ({
    play: () => videoRef.current?.play().catch(() => {}),
    pause: () => videoRef.current?.pause(),
    get playbackRate() { return videoRef.current?.playbackRate || 1; },
    set playbackRate(v) { if (videoRef.current) videoRef.current.playbackRate = v; },

    getCurrentDayOffset: () => {
      const seg = segmentsRef.current[currentSegIdxRef.current];
      if (!seg || !videoRef.current) return 0;
      return getDayOffset(seg.start_time) + (videoRef.current.currentTime || 0);
    },

    seekTo: (dayOffsetSec) => {
      const segs = segmentsRef.current;
      if (!segs.length || !videoRef.current) return;

      let targetIdx = segs.findIndex((s) => {
        const start = getDayOffset(s.start_time);
        const end = start + (s.duration || 0);
        return dayOffsetSec >= start && dayOffsetSec <= end;
      });

      if (targetIdx === -1) {
        targetIdx = segs.findIndex((s) => getDayOffset(s.start_time) > dayOffsetSec);
        if (targetIdx === -1) return;
      }

      const offsetInSeg = Math.max(
        0,
        dayOffsetSec - getDayOffset(segs[targetIdx].start_time)
      );

      if (targetIdx !== currentSegIdxRef.current) {
        pendingSeekRef.current = offsetInSeg;
        currentSegIdxRef.current = targetIdx;
        setCurrentSegIdx(targetIdx);
      } else {
        videoRef.current.currentTime = offsetInSeg;
      }
    },
  }), [getDayOffset]);

  return (
    <div
      className={cn(
        "relative bg-black rounded-md overflow-hidden w-full h-full min-h-0",
        className
      )}
    >
      {camera ? (
        <>
          <video
            ref={videoRef}
            className="w-full h-full object-contain"
            muted
            playsInline
            onCanPlay={() => setLoaded(true)}
            onError={() => setNoRecording(true)}
            onEnded={handleEnded}
          />

          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent px-2 py-1.5 flex items-center gap-2">
            <span className="text-white text-xs font-medium truncate">
              {camera.name}
            </span>
            {camera.status === "online" && (
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 flex-shrink-0" />
            )}
            {totalSegments > 1 && (
              <span className="ml-auto text-white/50 text-[10px]">
                {currentSegIdx + 1}/{totalSegments}
              </span>
            )}
          </div>

          {!loaded && !noRecording && (
            <div className="absolute inset-0 flex items-center justify-center text-white/40">
              <Video className="h-8 w-8 animate-pulse" />
            </div>
          )}

          {noRecording && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-white/40 gap-2">
              <X className="h-8 w-8" />
              <span className="text-xs">No recording</span>
            </div>
          )}
        </>
      ) : (
        <div className="flex items-center justify-center h-full text-white/20">
          <Video className="h-10 w-10" />
        </div>
      )}
    </div>
  );
});

export default CameraCell;
```

- [ ] **Step 2: Update `MultiPlayback.js` to import the extracted cell**

In `frontend/src/pages/MultiPlayback.js`:

1. Delete the inline `CameraCell` definition (the whole `const CameraCell = React.forwardRef(...)` block, lines 64–262).
2. Delete the local `parseUtc` function (lines 33–38).
3. Add these imports near the other imports (after line 27):

```js
import CameraCell from "../components/playback/CameraCell";
import { parseUtc } from "../lib/timeline";
```

(Keep `parseUtc` imported because `TimelineScrubber`'s `segRanges` still uses it.)

- [ ] **Step 3: Parse-check both files**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development node -e "require('@babel/core').transformFileSync('src/components/playback/CameraCell.js',{presets:['react-app']})" && node -e "require('@babel/core').transformFileSync('src/pages/MultiPlayback.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/playback/CameraCell.js frontend/src/pages/MultiPlayback.js
git commit -m "refactor(playback): extract CameraCell into its own component"
```

---

## Task 3: `TimelineTrack` component (one camera row)

**Files:**
- Create: `frontend/src/components/playback/TimelineTrack.js`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/playback/TimelineTrack.js`:

```js
// =============================================================================
// TimelineTrack — one camera's row in the multi-track timeline.
// Renders the background lane, recording bars, and event ticks for a single
// camera within the current viewport. Pure presentational.
// =============================================================================

import React, { useMemo } from "react";
import { segmentBars, eventTicks } from "../../lib/timeline";

const SEVERITY_COLOR = {
  alarm: "var(--console-rec)",
  critical: "var(--console-rec)",
  warning: "var(--console-alarm)",
  info: "var(--console-accent-blue)",
};

export default function TimelineTrack({
  camera,
  segments = [],
  events = [],
  view,
  date,
}) {
  const bars = useMemo(
    () => segmentBars(segments, view, date),
    [segments, view, date]
  );
  const ticks = useMemo(
    () => eventTicks(events, view, date),
    [events, view, date]
  );

  return (
    <div className="flex items-stretch h-9 border-b" style={{ borderColor: "var(--console-border)" }}>
      {/* Camera label gutter */}
      <div
        className="w-32 flex-shrink-0 flex items-center px-2 text-[11px] truncate border-r"
        style={{ borderColor: "var(--console-border)", color: "var(--console-muted)" }}
        title={camera?.name}
      >
        {camera?.name || "—"}
      </div>

      {/* Lane */}
      <div className="relative flex-1 min-w-0" style={{ background: "var(--console-panel)" }}>
        {/* Recording bars */}
        {bars.map((b) => (
          <span
            key={b.id}
            className="absolute top-1.5 bottom-1.5 rounded-sm"
            style={{
              left: `${b.left}%`,
              width: `${Math.max(0.2, b.width)}%`,
              background: "var(--console-accent)",
              opacity: 0.8,
            }}
          />
        ))}

        {/* Event ticks */}
        {ticks.map((t) => (
          <span
            key={t.id}
            className="absolute top-0 bottom-0 w-0.5"
            style={{ left: `${t.left}%`, background: SEVERITY_COLOR[t.severity] || SEVERITY_COLOR.info }}
            title={t.type}
          />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Parse-check**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development node -e "require('@babel/core').transformFileSync('src/components/playback/TimelineTrack.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/playback/TimelineTrack.js
git commit -m "feat(playback): add per-camera timeline track"
```

---

## Task 4: `MultiTimeline` component (ruler + tracks + playhead + zoom + seek)

**Files:**
- Create: `frontend/src/components/playback/MultiTimeline.js`

This component owns the interactive surface. The parent owns `view`, `currentTime`, and range state and passes setters down.

- [ ] **Step 1: Write the component**

Create `frontend/src/components/playback/MultiTimeline.js`:

```js
// =============================================================================
// MultiTimeline — the interactive multi-track timeline surface.
//   • Top ruler with adaptive grid ticks.
//   • One TimelineTrack per camera (recording bars + event ticks).
//   • Draggable playhead; click/drag anywhere on the lane area seeks.
//   • Zoom in/out/reset buttons + Ctrl/Cmd-wheel to zoom around the cursor.
//   • Optional in/out range shading for export selection.
// Coordinates: the lane area starts after a fixed 8rem (128px) label gutter,
// matching TimelineTrack's w-32 gutter.
// =============================================================================

import React, { useRef, useCallback } from "react";
import { ZoomIn, ZoomOut, Minimize } from "lucide-react";
import {
  DAY_SECONDS,
  gridTicks,
  timeToPct,
  pctToTime,
  zoomView,
  clampView,
} from "../../lib/timeline";
import TimelineTrack from "./TimelineTrack";

const GUTTER_PX = 128; // matches TimelineTrack label gutter (w-32)

export default function MultiTimeline({
  cameras = [],
  segmentsByCam = {},
  eventsByCam = {},
  date,
  view,
  currentTime,
  range = null, // { in: seconds, out: seconds } | null
  onSeek,
  onViewChange,
}) {
  const laneRef = useRef(null);

  // Pointer X (px from lane origin) → seconds, honoring the label gutter.
  const pointerToTime = useCallback(
    (clientX) => {
      const el = laneRef.current;
      if (!el) return view.start;
      const rect = el.getBoundingClientRect();
      const laneLeft = rect.left + GUTTER_PX;
      const laneWidth = rect.width - GUTTER_PX;
      if (laneWidth <= 0) return view.start;
      const x = Math.min(Math.max(0, clientX - laneLeft), laneWidth);
      return pctToTime((x / laneWidth) * 100, view);
    },
    [view]
  );

  const onPointerDown = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    onSeek?.(Math.floor(pointerToTime(e.clientX)));
  };
  const onPointerMove = (e) => {
    if (e.buttons !== 1) return;
    onSeek?.(Math.floor(pointerToTime(e.clientX)));
  };

  const onWheel = (e) => {
    if (!(e.ctrlKey || e.metaKey)) return; // plain scroll left to the page
    e.preventDefault();
    const anchor = pointerToTime(e.clientX);
    const factor = e.deltaY > 0 ? 1.25 : 0.8;
    onViewChange?.(zoomView(view, factor, anchor));
  };

  const center = (view.start + view.end) / 2;
  const ticks = gridTicks(view);
  const playheadPct = timeToPct(currentTime, view);

  const rangeStyle =
    range && range.in != null && range.out != null
      ? {
          left: `${timeToPct(Math.min(range.in, range.out), view)}%`,
          width: `${Math.abs(timeToPct(range.out, view) - timeToPct(range.in, view))}%`,
        }
      : null;

  return (
    <div className="select-none" style={{ background: "var(--console-bg)" }}>
      {/* Zoom controls + ruler */}
      <div className="flex items-stretch h-7 border-b" style={{ borderColor: "var(--console-border)" }}>
        <div className="w-32 flex-shrink-0 flex items-center gap-1 px-1 border-r" style={{ borderColor: "var(--console-border)" }}>
          <button title="Zoom in" className="p-1 rounded hover:bg-white/5" onClick={() => onViewChange?.(zoomView(view, 0.5, center))}>
            <ZoomIn className="h-3.5 w-3.5" style={{ color: "var(--console-muted)" }} />
          </button>
          <button title="Zoom out" className="p-1 rounded hover:bg-white/5" onClick={() => onViewChange?.(zoomView(view, 2, center))}>
            <ZoomOut className="h-3.5 w-3.5" style={{ color: "var(--console-muted)" }} />
          </button>
          <button title="Reset zoom" className="p-1 rounded hover:bg-white/5" onClick={() => onViewChange?.(clampView({ start: 0, end: DAY_SECONDS }))}>
            <Minimize className="h-3.5 w-3.5" style={{ color: "var(--console-muted)" }} />
          </button>
        </div>
        <div className="relative flex-1 min-w-0">
          {ticks.map((t) => (
            <span
              key={t.t}
              className="absolute top-0 bottom-0 flex items-center text-[10px] font-telemetry"
              style={{ left: `${t.left}%`, color: "var(--console-muted)", transform: "translateX(2px)" }}
            >
              {t.label}
            </span>
          ))}
        </div>
      </div>

      {/* Interactive lane stack */}
      <div
        ref={laneRef}
        className="relative cursor-crosshair"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onWheel={onWheel}
      >
        {cameras.map((cam) => (
          <TimelineTrack
            key={cam.id}
            camera={cam}
            segments={segmentsByCam[cam.id] || []}
            events={eventsByCam[cam.id] || []}
            view={view}
            date={date}
          />
        ))}

        {/* Gutter-offset overlay layer for range + playhead */}
        <div className="pointer-events-none absolute top-0 bottom-0 right-0" style={{ left: `${GUTTER_PX}px` }}>
          {rangeStyle && (
            <span className="absolute top-0 bottom-0" style={{ ...rangeStyle, background: "var(--console-accent-blue)", opacity: 0.15 }} />
          )}
          <span
            className="absolute top-0 bottom-0 w-0.5"
            style={{ left: `${playheadPct}%`, background: "var(--console-alarm)", boxShadow: "0 0 4px var(--console-alarm)" }}
          />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Parse-check**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development node -e "require('@babel/core').transformFileSync('src/components/playback/MultiTimeline.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/playback/MultiTimeline.js
git commit -m "feat(playback): add interactive multi-track timeline surface"
```

---

## Task 5: Tree-driven playback review set

Add a `playbackCameras` UI pref and make the shell tree toggle it when on `/playback`.

**Files:**
- Modify: `frontend/src/hooks/useUiPrefs.js`
- Modify: `frontend/src/components/shell/ControlRoomLayout.js`

- [ ] **Step 1: Add the pref default**

In `frontend/src/hooks/useUiPrefs.js`, change the `DEFAULTS` object so it reads:

```js
const DEFAULTS = {
  railCollapsed: false,
  treeCollapsed: false,
  dockOpen: true,
  wallLayout: 4,
  // wallTiles: array of cameraId|null, indexed by slot
  wallTiles: [],
  // playbackCameras: array of cameraId in the playback review set
  playbackCameras: [],
};
```

- [ ] **Step 2: Route-aware tree activation in the shell**

In `frontend/src/components/shell/ControlRoomLayout.js`:

1. After the existing `fillFirstEmpty` function (ends at line 37), add a toggle handler:

```js
  const togglePlaybackCamera = (cam) => {
    const set = Array.isArray(prefs.playbackCameras) ? prefs.playbackCameras.slice() : [];
    const idx = set.indexOf(cam.id);
    if (idx === -1) set.push(cam.id);
    else set.splice(idx, 1);
    setPrefs({ playbackCameras: set });
  };

  const onTreeActivate = location.pathname.startsWith("/playback")
    ? togglePlaybackCamera
    : fillFirstEmpty;
```

2. Change the `CameraTree` usage (line 50) from:

```js
                    <CameraTree onActivate={fillFirstEmpty} />
```

to:

```js
                    <CameraTree onActivate={onTreeActivate} />
```

- [ ] **Step 3: Parse-check**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development node -e "require('@babel/core').transformFileSync('src/hooks/useUiPrefs.js',{presets:['react-app']})" && node -e "require('@babel/core').transformFileSync('src/components/shell/ControlRoomLayout.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/hooks/useUiPrefs.js frontend/src/components/shell/ControlRoomLayout.js
git commit -m "feat(playback): drive playback review set from the shell camera tree"
```

---

## Task 6: `PlaybackConsole` page (compose grid + timeline + transport)

**Files:**
- Create: `frontend/src/pages/PlaybackConsole.js`

This page reads the review set from `playbackCameras` (seeded from `?camera=` on first load), renders the `CameraCell` grid, fetches per-camera segments + events, and wires `MultiTimeline` + transport (play/pause, ±10s/±60s, frame step, speed 0.25–8×, date jump).

- [ ] **Step 1: Write the page**

Create `frontend/src/pages/PlaybackConsole.js`:

```js
// =============================================================================
// PlaybackConsole — timeline-centric multi-camera review.
// Review set comes from the shell CameraTree (playbackCameras pref); seeded
// from ?camera=<id> on first load. Replaces the slider-based MultiPlayback.
// =============================================================================

import React, { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  Play, Pause, FastForward, Rewind, SkipBack, SkipForward,
  ChevronLeft, ChevronRight, Calendar, Video, Download,
} from "lucide-react";
import { format, subDays } from "date-fns";
import { useUiPrefs } from "../hooks";
import { useCamerasQuery } from "../hooks";
import { getRecordings, exportClip } from "../api/recordings";
import { getEvents } from "../api/events";
import { DAY_SECONDS, clampView, fmtClock } from "../lib/timeline";
import CameraCell from "../components/playback/CameraCell";
import MultiTimeline from "../components/playback/MultiTimeline";
import { toast } from "sonner";

const SPEEDS = [0.25, 0.5, 1, 2, 4, 8];
const FRAME = 1 / 15; // single frame step (~15fps wall tiles)

function gridCols(n) {
  if (n <= 1) return "grid-cols-1";
  if (n <= 4) return "grid-cols-2";
  if (n <= 9) return "grid-cols-3";
  return "grid-cols-4";
}

export default function PlaybackConsole() {
  const [prefs, setPrefs] = useUiPrefs();
  const { data: cameras = [] } = useCamerasQuery();
  const [searchParams] = useSearchParams();
  const cellRefs = useRef({});
  const syncIntervalRef = useRef(null);

  // Seed selection from ?camera=<id> once if the review set is empty.
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current) return;
    const seed = searchParams.get("camera");
    if (seed && (!prefs.playbackCameras || prefs.playbackCameras.length === 0)) {
      setPrefs({ playbackCameras: [seed] });
    }
    seededRef.current = true;
  }, [searchParams, prefs.playbackCameras, setPrefs]);

  const selectedIds = useMemo(
    () => (Array.isArray(prefs.playbackCameras) ? prefs.playbackCameras : []),
    [prefs.playbackCameras]
  );
  const selectedCameras = useMemo(
    () => cameras.filter((c) => selectedIds.includes(c.id)),
    [cameras, selectedIds]
  );

  const [date, setDate] = useState(format(new Date(), "yyyy-MM-dd"));
  const [playing, setPlaying] = useState(false);
  const [speedIdx, setSpeedIdx] = useState(2);
  const [currentTime, setCurrentTime] = useState(0);
  const [view, setView] = useState({ start: 0, end: DAY_SECONDS });
  const [range, setRange] = useState({ in: null, out: null });
  const speed = SPEEDS[speedIdx];

  // Per-camera segments for the timeline tracks.
  const segmentQueries = useQueries({
    queries: selectedIds.map((id) => ({
      queryKey: ["pb-segments", id, date],
      queryFn: () =>
        getRecordings({
          camera_id: id,
          start_after: `${date}T00:00:00`,
          end_before: `${date}T23:59:59`,
          limit: 500,
        }),
      staleTime: 30_000,
    })),
  });
  const segmentsByCam = useMemo(() => {
    const m = {};
    selectedIds.forEach((id, i) => { m[id] = segmentQueries[i]?.data || []; });
    return m;
  }, [selectedIds, segmentQueries]);

  // Per-camera events (ticks).
  const eventQueries = useQueries({
    queries: selectedIds.map((id) => ({
      queryKey: ["pb-events", id, date],
      queryFn: () =>
        getEvents({
          camera_id: id,
          start_date: `${date}T00:00:00`,
          end_date: `${date}T23:59:59`,
          limit: 1000,
        }),
      staleTime: 30_000,
    })),
  });
  const eventsByCam = useMemo(() => {
    const m = {};
    selectedIds.forEach((id, i) => { m[id] = eventQueries[i]?.data?.events || []; });
    return m;
  }, [selectedIds, eventQueries]);

  const allCells = () => Object.values(cellRefs.current).filter(Boolean);

  const play = useCallback(() => {
    allCells().forEach((c) => { c.playbackRate = speed; c.play(); });
    setPlaying(true);
  }, [speed]); // eslint-disable-line
  const pause = useCallback(() => {
    allCells().forEach((c) => c.pause());
    setPlaying(false);
  }, []); // eslint-disable-line
  const togglePlay = useCallback(() => { playing ? pause() : play(); }, [playing, play, pause]);

  const seekAll = useCallback((t) => {
    const clamped = Math.max(0, Math.min(DAY_SECONDS, t));
    setCurrentTime(clamped);
    allCells().forEach((c) => c.seekTo(clamped));
  }, []); // eslint-disable-line

  // Heartbeat: keep playhead synced to the first cell.
  useEffect(() => {
    if (selectedCameras.length === 0) return undefined;
    syncIntervalRef.current = setInterval(() => {
      const cells = allCells();
      if (cells[0]) setCurrentTime(Math.floor(cells[0].getCurrentDayOffset()));
    }, 500);
    return () => clearInterval(syncIntervalRef.current);
  }, [selectedCameras.length]);

  // Apply speed mid-playback.
  useEffect(() => { allCells().forEach((c) => { c.playbackRate = speed; }); }, [speed]); // eslint-disable-line

  // Reset on date/selection change.
  useEffect(() => { pause(); setCurrentTime(0); setView({ start: 0, end: DAY_SECONDS }); }, [date, selectedIds]); // eslint-disable-line

  // Keyboard shortcuts.
  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "INPUT") return;
      switch (e.key) {
        case " ": e.preventDefault(); togglePlay(); break;
        case "ArrowLeft": e.preventDefault(); seekAll(currentTime - 10); break;
        case "ArrowRight": e.preventDefault(); seekAll(currentTime + 10); break;
        case ",": seekAll(currentTime - FRAME); break;
        case ".": seekAll(currentTime + FRAME); break;
        case "[": setSpeedIdx((i) => Math.max(0, i - 1)); break;
        case "]": setSpeedIdx((i) => Math.min(SPEEDS.length - 1, i + 1)); break;
        default: break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [togglePlay, seekAll, currentTime]);

  const removeCamera = (id) => {
    setPrefs({ playbackCameras: selectedIds.filter((x) => x !== id) });
  };

  const shiftDate = (days) => {
    const d = subDays(new Date(`${date}T00:00:00`), days);
    setDate(format(d, "yyyy-MM-dd"));
  };

  const doExport = async () => {
    if (range.in == null || range.out == null) {
      toast.error("Mark an In and Out point first");
      return;
    }
    const lo = Math.min(range.in, range.out);
    const hi = Math.max(range.in, range.out);
    const start = `${date}T${fmtClock(lo)}`;
    const end = `${date}T${fmtClock(hi)}`;
    try {
      await Promise.all(
        selectedIds.map((id) =>
          exportClip({ camera_id: id, start_time: start, end_time: end, format: "mp4" })
        )
      );
      toast.success(`Export queued for ${selectedIds.length} camera(s)`);
    } catch {
      toast.error("Export failed to queue");
    }
  };

  if (selectedCameras.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3" style={{ color: "var(--console-muted)" }}>
        <Video className="h-12 w-12 opacity-30" />
        <p className="text-sm">Double-click cameras in the tree to review them here.</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col" style={{ background: "var(--console-bg)" }}>
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-2 h-9 border-b console-panel" style={{ borderColor: "var(--console-border)" }}>
        <button className="p-1 rounded hover:bg-white/5" title="Previous day" onClick={() => shiftDate(1)}>
          <ChevronLeft className="h-4 w-4" style={{ color: "var(--console-muted)" }} />
        </button>
        <span className="inline-flex items-center gap-1 text-xs font-telemetry" style={{ color: "var(--console-text)" }}>
          <Calendar className="h-3.5 w-3.5" /> {date}
        </span>
        <input
          type="date"
          value={date}
          max={format(new Date(), "yyyy-MM-dd")}
          onChange={(e) => setDate(e.target.value)}
          className="bg-transparent text-xs px-1 py-0.5 rounded border"
          style={{ borderColor: "var(--console-border)", color: "var(--console-text)" }}
        />
        <button className="p-1 rounded hover:bg-white/5" title="Next day" onClick={() => shiftDate(-1)}>
          <ChevronRight className="h-4 w-4" style={{ color: "var(--console-muted)" }} />
        </button>
        <span className="ml-auto text-xs font-telemetry" style={{ color: "var(--console-muted)" }}>
          {fmtClock(currentTime)}
        </span>
      </div>

      {/* Video grid */}
      <div className="flex-1 min-h-0 p-1">
        <div className={`grid gap-1 h-full ${gridCols(selectedCameras.length)}`}>
          {selectedCameras.map((cam) => (
            <div key={cam.id} className="relative group min-h-0 min-w-0 h-full">
              <CameraCell ref={(el) => { cellRefs.current[cam.id] = el; }} camera={cam} date={date} />
              <button
                className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 text-white text-xs bg-black/50 rounded px-1"
                onClick={() => removeCamera(cam.id)}
                title="Remove from review"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Timeline */}
      <MultiTimeline
        cameras={selectedCameras}
        segmentsByCam={segmentsByCam}
        eventsByCam={eventsByCam}
        date={date}
        view={view}
        currentTime={currentTime}
        range={range}
        onSeek={seekAll}
        onViewChange={(v) => setView(clampView(v))}
      />

      {/* Transport */}
      <div className="flex items-center gap-1 px-2 h-10 border-t console-panel" style={{ borderColor: "var(--console-border)" }}>
        <button className="p-1.5 rounded hover:bg-white/5" title="Back 60s" onClick={() => seekAll(currentTime - 60)}><SkipBack className="h-4 w-4" style={{ color: "var(--console-muted)" }} /></button>
        <button className="p-1.5 rounded hover:bg-white/5" title="Back 10s (←)" onClick={() => seekAll(currentTime - 10)}><Rewind className="h-4 w-4" style={{ color: "var(--console-muted)" }} /></button>
        <button className="p-1.5 rounded hover:bg-white/5" title="Prev frame (,)" onClick={() => seekAll(currentTime - FRAME)}>«</button>
        <button className="p-2 rounded-full" style={{ background: "var(--console-accent)", color: "#06231f" }} onClick={togglePlay}>
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        </button>
        <button className="p-1.5 rounded hover:bg-white/5" title="Next frame (.)" onClick={() => seekAll(currentTime + FRAME)}>»</button>
        <button className="p-1.5 rounded hover:bg-white/5" title="Forward 10s (→)" onClick={() => seekAll(currentTime + 10)}><FastForward className="h-4 w-4" style={{ color: "var(--console-muted)" }} /></button>
        <button className="p-1.5 rounded hover:bg-white/5" title="Forward 60s" onClick={() => seekAll(currentTime + 60)}><SkipForward className="h-4 w-4" style={{ color: "var(--console-muted)" }} /></button>

        <div className="flex items-center gap-0.5 ml-2">
          {SPEEDS.map((s, i) => (
            <button
              key={s}
              onClick={() => setSpeedIdx(i)}
              className="h-6 px-1.5 text-[11px] rounded font-telemetry"
              style={{
                background: speedIdx === i ? "var(--console-accent)" : "transparent",
                color: speedIdx === i ? "#06231f" : "var(--console-muted)",
              }}
            >
              {s}×
            </button>
          ))}
        </div>

        {/* Range + export */}
        <div className="ml-auto flex items-center gap-1">
          <button className="h-6 px-2 text-[11px] rounded border font-telemetry" style={{ borderColor: "var(--console-border)", color: "var(--console-muted)" }} onClick={() => setRange((r) => ({ ...r, in: currentTime }))}>
            Mark In {range.in != null ? fmtClock(range.in) : ""}
          </button>
          <button className="h-6 px-2 text-[11px] rounded border font-telemetry" style={{ borderColor: "var(--console-border)", color: "var(--console-muted)" }} onClick={() => setRange((r) => ({ ...r, out: currentTime }))}>
            Mark Out {range.out != null ? fmtClock(range.out) : ""}
          </button>
          <button className="h-6 px-2 text-[11px] rounded inline-flex items-center gap-1" style={{ background: "var(--console-accent-blue)", color: "#fff" }} onClick={doExport}>
            <Download className="h-3.5 w-3.5" /> Export
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Parse-check**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development node -e "require('@babel/core').transformFileSync('src/pages/PlaybackConsole.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 3: Verify hook/exports exist (no new code, just confirm)**

Run:
```bash
cd frontend && grep -n "useCamerasQuery" src/hooks/index.js && grep -n "export const exportClip" src/api/recordings.js && grep -n "export const getEvents" src/api/events.js
```
Expected: each grep prints a matching line. (If `useCamerasQuery` is not re-exported from `src/hooks/index.js`, import it from its source module instead and note the path in the commit.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/PlaybackConsole.js
git commit -m "feat(playback): add timeline-centric PlaybackConsole page"
```

---

## Task 7: Route `PlaybackConsole` into the app

**Files:**
- Modify: `frontend/src/App.js`

- [ ] **Step 1: Swap the lazy import**

In `frontend/src/App.js`, change the playback lazy import (line 58) from:

```js
const MultiPlayback = lazy(() => import("./pages/MultiPlayback"));
```

to:

```js
const PlaybackConsole = lazy(() => import("./pages/PlaybackConsole"));
```

- [ ] **Step 2: Point both playback routes at it**

In `frontend/src/App.js`, change line 150 from:

```js
        <Route path="playback" element={<MultiPlayback />} />
```

to:

```js
        <Route path="playback" element={<PlaybackConsole />} />
```

and change line 172 from:

```js
        <Route path="playback/multi" element={<MultiPlayback />} />
```

to:

```js
        <Route path="playback/multi" element={<PlaybackConsole />} />
```

- [ ] **Step 3: Parse-check**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development node -e "require('@babel/core').transformFileSync('src/App.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.js
git commit -m "feat(playback): route /playback to the new PlaybackConsole"
```

---

## Task 8: Retire the old `MultiPlayback` page

Now unrouted. Remove it (the reusable `CameraCell` already lives in `components/playback/`).

**Files:**
- Delete: `frontend/src/pages/MultiPlayback.js`

- [ ] **Step 1: Confirm it is unreferenced**

Run:
```bash
cd frontend && grep -rn "pages/MultiPlayback" src || echo NO_REFERENCES
```
Expected: `NO_REFERENCES`.

- [ ] **Step 2: Delete the file**

Run:
```bash
cd /Users/snowden/office/side_project/gvd_nvr && git rm frontend/src/pages/MultiPlayback.js
```

- [ ] **Step 3: Commit**

```bash
git commit -m "chore(playback): remove superseded MultiPlayback page"
```

---

## Task 9: Full test suite, build, deploy, browser verify

**Files:** none (verification only)

- [ ] **Step 1: Run the helper test suites**

Run: `cd frontend && CI=true npx craco test src/lib/timeline.test.js src/lib/videoWall.test.js src/lib/telemetry.test.js --watchAll=false`
Expected: all suites PASS.

- [ ] **Step 2: Build and deploy the frontend**

Run:
```bash
cd /Users/snowden/office/side_project/gvd_nvr && DOCKER=/Applications/Docker.app/Contents/Resources/bin/docker && $DOCKER compose build frontend && $DOCKER compose up -d --no-deps frontend && echo REBUILD_DEPLOY_OK
```
Expected: `REBUILD_DEPLOY_OK`.

- [ ] **Step 3: Browser verification (Chrome MCP, tab on https://localhost)**

Verify, in the running app:
1. Navigate to `/`, double-click 2 cameras in the tree, then click the **Playback** icon in the left rail (or navigate to `/playback`). The two cameras appear as a video grid with a multi-track timeline below — one track per camera, teal recording bars, event ticks.
2. Click on the timeline lane → the playhead jumps there and all cells seek together; the clock readout updates.
3. Press Play → cells play in sync; change speed (e.g. 4×) → playback rate changes.
4. Ctrl/Cmd-scroll on the lane (or the Zoom In button) → the viewport zooms and the ruler relabels; Reset returns to the full day.
5. Click **Mark In**, scrub forward, click **Mark Out** → a shaded range appears; click **Export** → a success toast ("Export queued…").
6. Double-click another camera in the tree → it is added as a third track/cell; the ✕ on a tile removes it.

Expected: all six behaviors work; no console errors; theme is full-black consistent with the rest of the shell.

---

## Self-Review

**1. Spec coverage (design §6):**
- Multi-track horizontal timeline, one track per camera, recording bars + event ticks → Tasks 1, 3, 4, 6. ✓
- Draggable, zoomable playhead (hour ↔ day) + date jump → `MultiTimeline` (pointer seek, zoom, ruler) + `PlaybackConsole` date controls. ✓
- Sync scrub, speeds 0.25–8× + frame step → `seekAll`, `SPEEDS`, `FRAME` step (`,`/`.`). ✓
- Export selected range via existing flow → `range` + `exportClip` (Task 6, verified Task 9). ✓
- Same `CameraTree` to add/remove cameras → Task 5 (`playbackCameras`, route-aware `onActivate`) + ✕ remove. ✓
- Keep `parseUtc`/grid logic where useful → reused in `lib/timeline` (`parseUtc`, `dayOffset`) and `CameraCell`. ✓

**2. Placeholder scan:** No TBD/TODO; every code step is complete. ✓

**3. Type consistency:** `view` is `{ start, end }` everywhere; `range` is `{ in, out }` everywhere; segment objects use `{ id, start_time, duration }`; events use `{ id, triggered_at, severity, event_type }`; helper names (`clampView`, `zoomView`, `timeToPct`, `pctToTime`, `gridTicks`, `segmentBars`, `eventTicks`, `fmtClock`, `dayOffset`, `parseUtc`) are identical across `lib/timeline.js`, its test, `TimelineTrack`, `MultiTimeline`, and `PlaybackConsole`. ✓

**Notes for the implementer:**
- `getEvents` returns `{ events, total, limit, offset }` — read `.events` (handled in `eventsByCam`).
- The `start_date`/`end_date` event params filter on `triggered_at`; if the backend ignores naive strings, ticks simply won't render — not a blocker for timeline shipping.
- The label gutter width is duplicated as `w-32` (TimelineTrack) and `GUTTER_PX = 128` (MultiTimeline). They must stay equal; if you change one, change both.
