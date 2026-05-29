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

import React, { useRef, useCallback, useEffect } from "react";
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

  // Wheel handling lives on a NATIVE, non-passive listener (below). React's
  // synthetic onWheel is registered as passive, so e.preventDefault() there is
  // silently ignored — which let trackpad pinch-zoom fall through to the
  // browser and zoom the whole console (video tiles included). A native
  // { passive: false } listener lets us actually cancel that default.
  useEffect(() => {
    const el = laneRef.current;
    if (!el) return undefined;

    const handleWheel = (e) => {
      // Pinch-zoom and ctrl/cmd+wheel arrive as wheel events with a modifier.
      // Zoom the timeline around the cursor and swallow the event so the
      // browser doesn't page-zoom the surrounding video wall.
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const anchor = pointerToTime(e.clientX);
        const factor = e.deltaY > 0 ? 1.25 : 0.8;
        onViewChange?.(zoomView(view, factor, anchor));
        return;
      }

      // Horizontal trackpad scroll (or Shift+vertical) pans the viewport so a
      // zoomed-in window can slide left/right. Plain vertical scroll is left
      // alone for the page.
      const dx =
        Math.abs(e.deltaX) > Math.abs(e.deltaY)
          ? e.deltaX
          : e.shiftKey
          ? e.deltaY
          : 0;
      if (dx === 0) return;
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const laneWidth = rect.width - GUTTER_PX;
      if (laneWidth <= 0) return;
      const secPerPx = (view.end - view.start) / laneWidth;
      const shift = dx * secPerPx;
      onViewChange?.(
        clampView({ start: view.start + shift, end: view.end + shift })
      );
    };

    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [view, pointerToTime, onViewChange]);

  const center = (view.start + view.end) / 2;
  const ticks = gridTicks(view);

  // Clamp all overlay positions to the visible [0,100]% track. Without this an
  // out-of-range playhead (e.g. a currentTime past the viewport) renders far to
  // the right of the lane and triggers a stray horizontal scrollbar under the
  // seekbar.
  const clampPct = (p) => Math.max(0, Math.min(100, p));
  const playheadPct = clampPct(timeToPct(currentTime, view));

  const rangeStyle =
    range && range.in != null && range.out != null
      ? (() => {
          const lo = clampPct(timeToPct(Math.min(range.in, range.out), view));
          const hi = clampPct(timeToPct(Math.max(range.in, range.out), view));
          return { left: `${lo}%`, width: `${hi - lo}%` };
        })()
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
        <div className="relative flex-1 min-w-0 overflow-hidden">
          {ticks.map((t) => (
            <span
              key={t.t}
              className="absolute top-0 bottom-0 flex items-center text-[10px] font-telemetry whitespace-nowrap"
              style={{
                left: `${t.left}%`,
                color: "var(--console-muted)",
                // The final tick (left ≈ 100%) would render its label past the
                // right edge and trigger a stray horizontal scrollbar. Right-
                // align it so it sits inside the bar; all others hang slightly
                // to the right of their gridline as usual.
                transform: t.left >= 99 ? "translateX(calc(-100% - 4px))" : "translateX(2px)",
              }}
            >
              {t.label}
            </span>
          ))}
        </div>
      </div>

      {/* Interactive lane stack */}
      <div
        ref={laneRef}
        className="relative cursor-crosshair overflow-hidden"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
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
