// =============================================================================
// AI · Live tab — video-wall of cameras assigned to this scenario, each with
// the NVR's WebRTCPlayer (go2rtc, low-latency). Recent recognition events are
// polled every 3s via GET /api/ai/frs/live and overlaid per-camera as
// person-name + confidence badges so operators see who was just recognized.
// =============================================================================

import React, { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ScanFace, VideoOff, UserCheck, ShieldAlert, UserX } from "lucide-react";

import { WebRTCPlayer } from "../../../components/nvr/WebRTCPlayer";
import { getScenarioCameras, listFrsLive } from "../../../api/frs";
import {
  eventPersonName,
  eventTypeBadgeClass,
  confidenceBadgeClass,
  fmtConfidence,
} from "./frsShared";
import { cn } from "../../../lib/utils";

const LIVE_POLL_MS = 3000;
// How many recent recognitions to surface per camera overlay.
const MAX_OVERLAY_PER_CAM = 4;

function OverlayIcon({ type }) {
  if (type === "spoof_detected") return <ShieldAlert className="h-3 w-3" />;
  if (type === "face_unknown") return <UserX className="h-3 w-3" />;
  return <UserCheck className="h-3 w-3" />;
}

function CameraTile({ cam, events }) {
  const recent = (events || []).slice(0, MAX_OVERLAY_PER_CAM);

  return (
    <div
      className="relative aspect-video rounded-lg overflow-hidden border"
      style={{
        borderColor: "var(--console-border)",
        background: "var(--console-raised)",
      }}
    >
      <WebRTCPlayer
        streamId={cam.camera_id}
        cameraId={cam.camera_id}
        autoPlay
        muted
        className="rounded-none"
      />

      {/* ROI overlay — the configured region of interest (normalised points). */}
      {Array.isArray(cam.config?.roi) && cam.config.roi.length > 1 && (
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none z-20"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
        >
          <polygon
            points={cam.config.roi.map((p) => `${p[0] * 100},${p[1] * 100}`).join(" ")}
            fill="rgba(45,212,191,0.15)"
            stroke="var(--console-accent)"
            strokeWidth="0.4"
          />
        </svg>
      )}

      {/* Camera label — top */}
      <div className="absolute top-0 left-0 right-0 flex items-center justify-between gap-2 p-2 bg-gradient-to-b from-black/70 to-transparent pointer-events-none z-30">
        <span className="text-xs font-telemetry tracking-wider text-white/90 truncate">
          {cam.camera_name || cam.camera_id}
        </span>
        {cam.stream_state === "error" && (
          <span className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-rose-300">
            <VideoOff className="h-3 w-3" /> AI down
          </span>
        )}
      </div>

      {/* Recognition overlay — bottom, newest first */}
      {recent.length > 0 && (
        <div className="absolute bottom-0 left-0 right-0 flex flex-col gap-1 p-2 bg-gradient-to-t from-black/80 to-transparent pointer-events-none z-30">
          {recent.map((ev) => (
            <div
              key={ev.id}
              className={cn(
                "flex items-center gap-1.5 self-start max-w-full rounded-md border px-2 py-0.5 text-[11px] font-medium backdrop-blur-sm",
                eventTypeBadgeClass(ev.event_type),
              )}
            >
              <OverlayIcon type={ev.event_type} />
              <span className="truncate">{eventPersonName(ev)}</span>
              <span
                className={cn(
                  "ml-auto rounded border px-1 text-[10px] font-telemetry",
                  confidenceBadgeClass(ev.confidence),
                )}
              >
                {fmtConfidence(ev.confidence)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function LiveTab({ scenario }) {
  const scenarioId = scenario?.id;

  const {
    data: cameras = [],
    isLoading: camsLoading,
    isError: camsError,
  } = useQuery({
    queryKey: ["frs", "scenario-cameras", scenarioId],
    queryFn: () => getScenarioCameras(scenarioId),
    enabled: !!scenarioId,
  });

  const enabledCameras = useMemo(
    () => cameras.filter((c) => c.enabled !== false),
    [cameras],
  );

  const cameraIds = useMemo(
    () => enabledCameras.map((c) => c.camera_id),
    [enabledCameras],
  );

  // Poll recent recognition events; group by camera for overlays.
  const { data: live } = useQuery({
    queryKey: ["frs", "live", cameraIds],
    queryFn: () => listFrsLive({ camera_id: cameraIds, limit: 100 }),
    enabled: cameraIds.length > 0,
    refetchInterval: LIVE_POLL_MS,
    refetchIntervalInBackground: false,
  });

  const eventsByCamera = useMemo(() => {
    const map = {};
    (live?.items || []).forEach((ev) => {
      if (!ev.camera_id) return;
      (map[ev.camera_id] = map[ev.camera_id] || []).push(ev);
    });
    return map;
  }, [live]);

  if (camsLoading) {
    return (
      <div className="p-4 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="aspect-video rounded-lg border animate-pulse"
            style={{
              borderColor: "var(--console-border)",
              background: "var(--console-raised)",
            }}
          />
        ))}
      </div>
    );
  }

  if (camsError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <VideoOff className="h-10 w-10 text-rose-400 mb-3" />
        <p className="text-sm text-zinc-300">Couldn't load assigned cameras.</p>
      </div>
    );
  }

  if (enabledCameras.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <ScanFace className="h-10 w-10 text-zinc-500 mb-3" />
        <p className="text-sm font-medium text-zinc-200">No cameras assigned</p>
        <p className="text-xs text-zinc-500 mt-1 max-w-sm">
          Assign cameras to this scenario from the Cameras tab to see live
          recognition here.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
      {enabledCameras.map((cam) => (
        <CameraTile
          key={cam.id || cam.camera_id}
          cam={cam}
          events={eventsByCamera[cam.camera_id]}
        />
      ))}
    </div>
  );
}
