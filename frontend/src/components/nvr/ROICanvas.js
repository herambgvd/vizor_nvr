// =============================================================================
// ROICanvas — draw lines + polygons over a camera snapshot
// =============================================================================
// Used by:
//   - People Counting zone CRUD (line for in/out, polygon for crowd)
//   - FRS / PPE ROI selection (polygon, multi)
//
// Coords stored as normalized [0..1] over camera frame so zones survive
// resolution changes.
//
// Props:
//   cameraId      string — required, loads thumbnail
//   mode          "line" | "polygon"
//   value         {kind, points} | null  — current geometry (controlled)
//   onChange      fn(geometry)
//   labels        {a, b} optional — direction labels for line ends
//   className     string
// =============================================================================

import React, { useEffect, useRef, useState } from "react";
import { Trash2, RotateCcw } from "lucide-react";
import { BACKEND_URL, getAccessToken } from "../../api/client";
import { Button } from "../ui/button";
import { cn } from "../../lib/utils";

const ROICanvas = ({
  cameraId,
  mode = "polygon",
  value = null,
  onChange,
  labels = { a: "in", b: "out" },
  strokeColor = "rgb(20,184,166)",
  className,
}) => {
  const [bgUrl, setBgUrl] = useState(null);
  const [bgFailed, setBgFailed] = useState(false);
  const [draft, setDraft] = useState(() => (value?.points ? [...value.points] : []));
  const containerRef = useRef(null);

  // Load auth'd thumbnail blob
  useEffect(() => {
    let cancelled = false;
    let obj = null;
    (async () => {
      try {
        const token = getAccessToken();
        const res = await fetch(
          `${BACKEND_URL}/api/cameras/${cameraId}/thumbnail?t=${Date.now()}`,
          { headers: token ? { Authorization: `Bearer ${token}` } : {} },
        );
        if (!res.ok) {
          if (!cancelled) setBgFailed(true);
          return;
        }
        const blob = await res.blob();
        obj = URL.createObjectURL(blob);
        if (!cancelled) setBgUrl(obj);
      } catch {
        if (!cancelled) setBgFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      if (obj) URL.revokeObjectURL(obj);
    };
  }, [cameraId]);

  // Sync draft when external value changes
  useEffect(() => {
    setDraft(value?.points ? [...value.points] : []);
  }, [value]);

  const emit = (points) => {
    onChange?.({ kind: mode, points });
  };

  const handleClick = (e) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    const nx = Math.max(0, Math.min(1, x));
    const ny = Math.max(0, Math.min(1, y));

    setDraft((prev) => {
      let next;
      if (mode === "line") {
        if (prev.length < 2) next = [...prev, [nx, ny]];
        else next = [[nx, ny]]; // restart
      } else {
        next = [...prev, [nx, ny]];
      }
      emit(next);
      return next;
    });
  };

  const handleClear = () => {
    setDraft([]);
    emit([]);
  };

  const handleUndo = () => {
    setDraft((prev) => {
      const next = prev.slice(0, -1);
      emit(next);
      return next;
    });
  };

  const isComplete =
    (mode === "line" && draft.length === 2) ||
    (mode === "polygon" && draft.length >= 3);

  return (
    <div className={cn("space-y-2", className)}>
      <div
        ref={containerRef}
        onClick={handleClick}
        className="relative w-full aspect-video bg-black rounded-lg overflow-hidden border border-white/10 cursor-crosshair select-none"
      >
        {bgUrl ? (
          <img
            src={bgUrl}
            alt="camera"
            className="w-full h-full object-contain pointer-events-none"
            draggable={false}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
            {bgFailed ? "No thumbnail" : "Loading…"}
          </div>
        )}

        {/* SVG overlay — coords scaled to 0-1 viewbox */}
        <svg
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          className="absolute inset-0 w-full h-full pointer-events-none"
        >
          {mode === "polygon" && draft.length >= 2 && (
            <polyline
              points={draft.map((p) => p.join(",")).join(" ")}
              fill={draft.length >= 3 ? "rgba(20,184,166,0.18)" : "none"}
              stroke={strokeColor}
              strokeWidth="0.005"
              strokeLinejoin="round"
            />
          )}
          {mode === "polygon" && draft.length >= 3 && (
            <line
              x1={draft[draft.length - 1][0]}
              y1={draft[draft.length - 1][1]}
              x2={draft[0][0]}
              y2={draft[0][1]}
              stroke={strokeColor}
              strokeWidth="0.005"
              strokeDasharray="0.01,0.01"
            />
          )}
          {mode === "line" && draft.length === 2 && (
            <line
              x1={draft[0][0]}
              y1={draft[0][1]}
              x2={draft[1][0]}
              y2={draft[1][1]}
              stroke={strokeColor}
              strokeWidth="0.006"
              strokeLinecap="round"
            />
          )}
          {draft.map(([x, y], i) => (
            <circle
              key={i}
              cx={x}
              cy={y}
              r="0.012"
              fill="white"
              stroke={strokeColor}
              strokeWidth="0.004"
            />
          ))}
        </svg>

        {/* Line end labels */}
        {mode === "line" && draft.length === 2 && (
          <>
            <span
              className="absolute text-[10px] font-semibold bg-teal-500/80 text-white px-1.5 py-0.5 rounded -translate-x-1/2 -translate-y-1/2 pointer-events-none"
              style={{
                left: `${draft[0][0] * 100}%`,
                top: `${draft[0][1] * 100}%`,
              }}
            >
              {labels.a}
            </span>
            <span
              className="absolute text-[10px] font-semibold bg-rose-500/80 text-white px-1.5 py-0.5 rounded -translate-x-1/2 -translate-y-1/2 pointer-events-none"
              style={{
                left: `${draft[1][0] * 100}%`,
                top: `${draft[1][1] * 100}%`,
              }}
            >
              {labels.b}
            </span>
          </>
        )}

        {/* Hint */}
        <div className="absolute top-2 left-2 text-[10px] bg-card/80 text-muted-foreground px-2 py-1 rounded border border-white/10 pointer-events-none">
          {mode === "line"
            ? "Click 2 points · A → B is the direction"
            : `Click points (${draft.length}) · ≥3 needed for polygon`}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleUndo}
          disabled={draft.length === 0}
        >
          <RotateCcw className="h-3.5 w-3.5 mr-1" />
          Undo
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleClear}
          disabled={draft.length === 0}
        >
          <Trash2 className="h-3.5 w-3.5 mr-1" />
          Clear
        </Button>
        <span className="text-[11px] text-muted-foreground ml-auto">
          {isComplete ? (
            <span className="text-emerald-400">Geometry ready</span>
          ) : (
            <span>Incomplete</span>
          )}
        </span>
      </div>
    </div>
  );
};

export default ROICanvas;
