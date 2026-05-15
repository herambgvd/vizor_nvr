// =============================================================================
// useEventStream — Server-Sent Events subscription for /api/events/stream
// =============================================================================
// One-way live event feed used by AI Modules (Live tab, alerts, dashboard).
// EventSource doesn't allow Authorization headers, so we pass the JWT as
// a query param. Backend get_current_user reads ?token= too.
//
// Filters:
//   { scenario?, event_type?, camera_id? }
// =============================================================================

import { useEffect, useRef, useState } from "react";
import { BACKEND_URL, getAccessToken } from "../api/client";

export const useEventStream = ({
  scenario,
  eventType,
  cameraId,
  onEvent,
  enabled = true,
} = {}) => {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState(null);
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    if (!enabled) return undefined;
    const token = getAccessToken();
    if (!token) return undefined;

    const params = new URLSearchParams({ token });
    if (scenario) params.set("scenario", scenario);
    if (eventType) params.set("event_type", eventType);
    if (cameraId) params.set("camera_id", cameraId);

    const url = `${BACKEND_URL}/api/events/stream?${params.toString()}`;
    let es;
    try {
      es = new EventSource(url);
    } catch {
      return undefined;
    }

    es.addEventListener("connected", () => setConnected(true));
    es.addEventListener("ping", () => {});
    es.addEventListener("ai_event", (e) => {
      try {
        const data = JSON.parse(e.data);
        setLastEvent(data);
        cbRef.current?.(data);
      } catch {
        /* ignore */
      }
    });
    es.onerror = () => {
      setConnected(false);
      // EventSource auto-reconnects (3s default). Do nothing.
    };

    return () => {
      try {
        es.close();
      } catch {
        /* ignore */
      }
    };
  }, [enabled, scenario, eventType, cameraId]);

  return { connected, lastEvent };
};

export default useEventStream;
