// =============================================================================
// LiveViewPage — /cameras/:id/live
// =============================================================================

import React, { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Video,
  Square,
  Volume2,
  VolumeX,
  Maximize2,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import {
  getStreamUrls,
  startRecording,
  stopRecording,
} from "../../api/cameras";
import { WebRTCPlayer } from "../../components/nvr/WebRTCPlayer";
import { PTZControls } from "../../components/nvr/PTZControls";
import { Button } from "../../components/ui/button";

const InfoCard = ({ label, value }) => (
  <div className="rounded-lg border border-border bg-card/40 px-3 py-2.5">
    <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
      {label}
    </p>
    <p className="text-sm font-medium text-white truncate mt-0.5">{value}</p>
  </div>
);

const LiveViewPage = () => {
  const { camera, cameraId } = useOutletContext();
  const qc = useQueryClient();
  const [isMuted, setIsMuted] = useState(true);
  const [streamReady, setStreamReady] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [liveStreamId, setLiveStreamId] = useState(null);

  const isOnline = camera.status === "online";

  // Re-register when camera flips online → offline → online
  useEffect(() => {
    let mounted = true;
    setStreamReady(false);
    setLiveStreamId(null);
    if (!isOnline) return undefined;

    setRegistering(true);
    (async () => {
      try {
        const streamUrls = await getStreamUrls(cameraId);
        if (mounted) {
          setLiveStreamId(streamUrls.live_stream_id || cameraId);
          setStreamReady(true);
        }
      } catch {
        if (mounted) {
          toast.error("Failed to start stream");
          setLiveStreamId(cameraId);
          setStreamReady(true);
        }
      } finally {
        if (mounted) setRegistering(false);
      }
    })();

    return () => {
      mounted = false;
    };
  }, [cameraId, isOnline]);

  const handleRecordingToggle = async () => {
    try {
      if (camera.is_recording) {
        await stopRecording(cameraId);
        toast.success("Recording stopped");
      } else {
        await startRecording(cameraId);
        toast.success("Recording started");
      }
      qc.invalidateQueries({ queryKey: ["camera", cameraId] });
      qc.invalidateQueries({ queryKey: ["cameras"] });
    } catch {
      toast.error(
        `Failed to ${camera.is_recording ? "stop" : "start"} recording`,
      );
    }
  };

  return (
    <div className="p-4 md:p-6 space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-2 flex-wrap">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setIsMuted((m) => !m)}
          title={isMuted ? "Currently muted — click to unmute" : "Currently audible — click to mute"}
        >
          {isMuted ? (
            <VolumeX className="h-4 w-4 mr-1" />
          ) : (
            <Volume2 className="h-4 w-4 mr-1" />
          )}
          {isMuted ? "Muted" : "Audible"}
        </Button>
        <Button
          variant={camera.is_recording ? "destructive" : "default"}
          size="sm"
          onClick={handleRecordingToggle}
          disabled={!isOnline}
        >
          {camera.is_recording ? (
            <>
              <Square className="h-4 w-4 mr-1" /> Stop Recording
            </>
          ) : (
            <>
              <Video className="h-4 w-4 mr-1" /> Start Recording
            </>
          )}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => window.open(`/live/${cameraId}`, "_blank")}
        >
          <Maximize2 className="h-4 w-4 mr-1" />
          Fullscreen
        </Button>
      </div>

      {/* Player + info column — 75/25 split */}
      <div className="grid grid-cols-1 lg:grid-cols-[3fr_1fr] gap-4">
        <div className="relative bg-black rounded-lg overflow-hidden aspect-video">
          {isOnline && streamReady && !registering && liveStreamId ? (
            <>
              <WebRTCPlayer
                streamId={liveStreamId}
                cameraId={cameraId}
                autoPlay
                muted={isMuted}
                controls={false}
                className="w-full h-full object-contain"
              />
              {camera.ptz_capable && <PTZControls cameraId={cameraId} />}
            </>
          ) : (
            <div className="w-full h-full flex items-center justify-center text-white min-h-[200px]">
              {registering ? (
                <div className="text-center">
                  <RefreshCw className="h-10 w-10 mx-auto mb-2 animate-spin opacity-70" />
                  <p className="text-sm">Starting stream…</p>
                </div>
              ) : !isOnline ? (
                <div className="text-center">
                  <Video className="h-10 w-10 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">Camera offline</p>
                </div>
              ) : (
                <RefreshCw className="h-10 w-10 animate-spin opacity-70" />
              )}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-3">
          <InfoCard label="Status" value={camera.status} />
          <InfoCard label="Resolution" value={camera.resolution || "—"} />
          <InfoCard label="FPS" value={camera.fps ? `${camera.fps}` : "—"} />
          <InfoCard label="PTZ" value={camera.ptz_capable ? "Yes" : "No"} />
        </div>
      </div>
    </div>
  );
};

export default LiveViewPage;
