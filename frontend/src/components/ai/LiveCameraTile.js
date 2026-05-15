// =============================================================================
// LiveCameraTile — MJPEG-ish thumbnail (2s refresh) + SVG detection overlay.
// =============================================================================
// Reused across People / FRS / PPE Live pages.
//
// Props:
//   cameraId       string — required, drives /cameras/{id}/thumbnail
//   label          string — caption under tile
//   zones          [{ id, name, points: [[x,y], …], severity?: 'info'|'warning'|'critical' }]
//                  points are normalized 0–1.
//   detections     [{ bbox: [x, y, w, h] (normalized 0–1), label?, confidence?, color? }]
//   onClick        () => void
//   showOverlay    bool — toggle bbox/zones (default true)
// =============================================================================

import React from "react";
import CameraThumbnail from "../nvr/CameraThumbnail";
import { cn } from "../../lib/utils";

const SEVERITY_FILL = {
  info: "rgba(56, 189, 248, 0.18)",     // sky-400
  warning: "rgba(251, 191, 36, 0.22)",  // amber-400
  critical: "rgba(244, 63, 94, 0.25)",  // rose-500
};
const SEVERITY_STROKE = {
  info: "#38bdf8",
  warning: "#fbbf24",
  critical: "#f43f5e",
};

const LiveCameraTile = ({
  cameraId,
  label,
  zones = [],
  detections = [],
  onClick,
  showOverlay = true,
  className,
}) => {
  return (
    <div
      onClick={onClick}
      className={cn(
        "relative rounded-lg overflow-hidden border border-border bg-black/30 group",
        onClick && "cursor-pointer hover:border-teal-500/50",
        className,
      )}
    >
      <div className="relative aspect-video w-full">
        <CameraThumbnail
          cameraId={cameraId}
          className="absolute inset-0 w-full h-full"
          refreshSec={2}
        />
        {showOverlay && (
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className="absolute inset-0 w-full h-full pointer-events-none"
          >
            {zones.map((z) => {
              if (!z.points || z.points.length < 2) return null;
              const tier = z.severity || "info";
              const isLine = z.points.length === 2;
              if (isLine) {
                const [[x1, y1], [x2, y2]] = z.points;
                return (
                  <line
                    key={z.id}
                    x1={x1 * 100}
                    y1={y1 * 100}
                    x2={x2 * 100}
                    y2={y2 * 100}
                    stroke={SEVERITY_STROKE[tier]}
                    strokeWidth="0.6"
                    strokeDasharray="2 1.5"
                    vectorEffect="non-scaling-stroke"
                  />
                );
              }
              const d = z.points
                .map((p, i) => `${i === 0 ? "M" : "L"} ${p[0] * 100} ${p[1] * 100}`)
                .join(" ") + " Z";
              return (
                <path
                  key={z.id}
                  d={d}
                  fill={SEVERITY_FILL[tier]}
                  stroke={SEVERITY_STROKE[tier]}
                  strokeWidth="0.4"
                  vectorEffect="non-scaling-stroke"
                />
              );
            })}
            {detections.map((d, i) => {
              if (!d.bbox || d.bbox.length < 4) return null;
              const [x, y, w, h] = d.bbox;
              const stroke = d.color || "#34d399";
              return (
                <g key={i}>
                  <rect
                    x={x * 100}
                    y={y * 100}
                    width={w * 100}
                    height={h * 100}
                    fill="none"
                    stroke={stroke}
                    strokeWidth="0.5"
                    vectorEffect="non-scaling-stroke"
                  />
                  {d.label && (
                    <text
                      x={x * 100 + 0.6}
                      y={y * 100 + 2.8}
                      fontSize="2.4"
                      fill={stroke}
                      style={{ fontFamily: "ui-monospace, monospace" }}
                    >
                      {d.label}
                      {d.confidence != null
                        ? ` ${Math.round(d.confidence * 100)}%`
                        : ""}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        )}
        <div className="absolute top-1.5 right-1.5 z-10">
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-black/60 text-[10px] font-medium text-rose-300 backdrop-blur-sm">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />
            LIVE
          </span>
        </div>
      </div>
      {label && (
        <div className="px-2.5 py-1.5 text-xs text-muted-foreground border-t border-white/5 flex items-center justify-between">
          <span className="truncate font-medium text-zinc-200">{label}</span>
          {detections.length > 0 && (
            <span className="font-mono text-[10px]">{detections.length}</span>
          )}
        </div>
      )}
    </div>
  );
};

export default LiveCameraTile;
