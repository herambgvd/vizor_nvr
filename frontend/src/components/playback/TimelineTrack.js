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
