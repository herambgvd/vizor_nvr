// =============================================================================
// useLiveDetections — keep last-N detections per camera from SSE stream.
// =============================================================================
// Each SSE ai_event may carry bbox + camera_id. We bucket by camera_id and
// expire entries older than `ttlMs` so stale boxes fade out when the worker
// stops emitting.
// =============================================================================

import { useCallback, useEffect, useRef, useState } from "react";
import { useEventStream } from "./useEventStream";

const DEFAULT_TTL = 4000;

export const useLiveDetections = ({
  scenario,
  ttlMs = DEFAULT_TTL,
  enabled = true,
} = {}) => {
  const [byCamera, setByCamera] = useState({});
  const sweeperRef = useRef(null);

  const handleEvent = useCallback(
    (ev) => {
      const cam = ev.camera_id;
      if (!cam) return;
      const det = {
        bbox: ev.bbox,
        label: ev.event_type || ev.detection_type,
        confidence: ev.confidence,
        color:
          ev.severity === "critical"
            ? "#f43f5e"
            : ev.severity === "warning"
            ? "#fbbf24"
            : "#34d399",
        ts: Date.now(),
      };
      setByCamera((prev) => {
        const list = prev[cam] || [];
        const next = [det, ...list].slice(0, 8);
        return { ...prev, [cam]: next };
      });
    },
    [],
  );

  useEventStream({ scenario, onEvent: handleEvent, enabled });

  // Periodic sweep — drop entries past TTL
  useEffect(() => {
    if (sweeperRef.current) clearInterval(sweeperRef.current);
    sweeperRef.current = setInterval(() => {
      const now = Date.now();
      setByCamera((prev) => {
        const next = {};
        let changed = false;
        for (const [cam, list] of Object.entries(prev)) {
          const kept = list.filter((d) => now - d.ts < ttlMs);
          if (kept.length) next[cam] = kept;
          if (kept.length !== list.length) changed = true;
        }
        return changed ? next : prev;
      });
    }, 1000);
    return () => {
      if (sweeperRef.current) clearInterval(sweeperRef.current);
    };
  }, [ttlMs]);

  return byCamera;
};

export default useLiveDetections;
