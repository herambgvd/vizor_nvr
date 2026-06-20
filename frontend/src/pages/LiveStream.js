// =============================================================================
// LiveStream — Fullscreen single-camera view with PTZ overlay
// =============================================================================

import React, { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Maximize2,
  Minimize2,
  Volume2,
  VolumeX,
  Video,
  Square,
  RefreshCw,
} from "lucide-react";
import {
  getCamera,
  getStreamUrls,
  startRecording,
  stopRecording,
} from "../api/cameras";
import { WebRTCPlayer } from "../components/nvr/WebRTCPlayer";
import { PTZControls } from "../components/nvr/PTZControls";
import { StatusBadge } from "../components/nvr/StatusBadge";
import { Button } from "../components/ui/button";
import { toast } from "sonner";

const LiveStream = () => {
  const { cameraId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const containerRef = useRef(null);

  const [isMuted, setIsMuted] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [streamReady, setStreamReady] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [liveStreamId, setLiveStreamId] = useState(null);

  // Camera data
  const { data: camera, isLoading } = useQuery({
    queryKey: ["camera", cameraId],
    queryFn: () => getCamera(cameraId),
    refetchInterval: 10000,
  });

  // Register stream on mount / when camera comes online
  useEffect(() => {
    let mounted = true;
    const register = async () => {
      if (!camera || camera.status !== "online" || streamReady) return;
      setRegistering(true);
      try {
        const streamUrls = await getStreamUrls(cameraId);
        if (mounted) {
          setLiveStreamId(streamUrls.live_stream_id || cameraId);
          setStreamReady(true);
        }
      } catch {
        if (mounted) {
          toast.error("Failed to start stream");
          setLiveStreamId(cameraId); // fallback
        }
      } finally {
        if (mounted) setRegistering(false);
      }
    };
    register();
    return () => {
      mounted = false;
    };
  }, [camera, cameraId, streamReady]);

  // Fullscreen listeners
  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen();
    } else {
      document.exitFullscreen();
    }
  };

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

  // ---------- loading / error states ----------

  if (isLoading) {
    return (
      <div className="h-screen flex items-center justify-center bg-black">
        <RefreshCw className="h-12 w-12 text-white animate-spin" />
      </div>
    );
  }

  if (!camera) {
    return (
      <div className="h-screen flex items-center justify-center bg-black">
        <div className="text-center">
          <p className="text-white text-xl mb-4">Camera not found</p>
          <Button onClick={() => navigate("/")}>Go Back</Button>
        </div>
      </div>
    );
  }

  const isOnline = camera.status === "online";

  return (
    <div
      ref={containerRef}
      className="h-screen bg-black relative overflow-hidden"
    >
      {/* Video */}
      {isOnline && streamReady && !registering && liveStreamId ? (
        <WebRTCPlayer
          streamId={liveStreamId}
          cameraId={cameraId}
          autoPlay
          muted={isMuted}
          controls={false}
          className="w-full h-full"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-white text-center">
          {registering ? (
            <>
              <RefreshCw className="h-16 w-16 mx-auto mb-4 animate-spin" />
              <p className="text-xl">Starting stream…</p>
            </>
          ) : !isOnline ? (
            <>
              <Video className="h-16 w-16 mx-auto mb-4 opacity-50" />
              <p className="text-xl">Camera offline</p>
            </>
          ) : (
            <RefreshCw className="h-16 w-16 animate-spin" />
          )}
        </div>
      )}

      {/* PTZ Controls — only shown for PTZ-capable cameras */}
      {isOnline && streamReady && camera.ptz_capable && (
        <PTZControls cameraId={cameraId} ptzCapable={camera.ptz_capable} />
      )}

      {/* Top bar */}
      <div className="absolute top-0 inset-x-0 p-4 bg-gradient-to-b from-black/80 to-transparent">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => navigate(-1)}
              className="text-white hover:bg-card/20"
            >
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-white text-xl font-semibold">
                {camera.name}
              </h1>
              {camera.location && (
                <p className="text-white/70 text-sm">{camera.location}</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge
              status={camera.status}
              className="bg-black/60 backdrop-blur-sm text-white border-transparent"
            />
            {camera.is_recording && (
              <div className="flex items-center gap-2 bg-red-500/20 backdrop-blur-sm px-3 py-1.5 rounded-full">
                <div className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
                <span className="text-white text-sm font-medium">REC</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom bar */}
      <div className="absolute bottom-0 inset-x-0 p-4 bg-gradient-to-t from-black/80 to-transparent">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {isOnline && camera.resolution && (
              <div className="text-white/80 text-sm bg-black/40 backdrop-blur-sm px-3 py-1.5 rounded">
                {camera.resolution} {camera.fps ? `• ${camera.fps}fps` : ""}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={handleRecordingToggle}
              disabled={!isOnline}
              className="text-white hover:bg-card/20"
              title={camera.is_recording ? "Stop Recording" : "Start Recording"}
            >
              {camera.is_recording ? (
                <Square className="h-5 w-5 fill-current" />
              ) : (
                <Video className="h-5 w-5" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setIsMuted(!isMuted)}
              className="text-white hover:bg-card/20"
            >
              {isMuted ? (
                <VolumeX className="h-5 w-5" />
              ) : (
                <Volume2 className="h-5 w-5" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleFullscreen}
              className="text-white hover:bg-card/20"
            >
              {isFullscreen ? (
                <Minimize2 className="h-5 w-5" />
              ) : (
                <Maximize2 className="h-5 w-5" />
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default LiveStream;
