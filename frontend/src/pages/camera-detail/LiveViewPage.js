// =============================================================================
// LiveViewPage — /cameras/:id/live
// =============================================================================

import React, { useEffect, useState, useRef } from "react";
import { useOutletContext } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Video,
  Square,
  Volume2,
  VolumeX,
  Maximize2,
  RefreshCw,
  Mic,
  MicOff,
  Activity,
  Monitor,
  Gauge,
  Move3d,
  Radio,
} from "lucide-react";
import { toast } from "sonner";
import {
  getStreamUrls,
  startRecording,
  stopRecording,
  postBackchannelWebrtcSignal,
} from "../../api/cameras";
import { WebRTCPlayer } from "../../components/nvr/WebRTCPlayer";
import { PTZControls } from "../../components/nvr/PTZControls";
import { Button } from "../../components/ui/button";

// Icon-led, color-coded telemetry tile. `tone` accents the icon + value so
// live state (online / recording) reads at a glance.
const StatTile = ({ icon: Icon, label, value, tone, pulse }) => {
  const accent = tone || "var(--console-text)";
  return (
    <div
      className="group flex items-center gap-3 rounded-lg border bg-[#141414] px-3 py-2.5 transition-colors hover:border-[var(--console-accent)]"
      style={{ borderColor: "var(--console-border)" }}
    >
      <div
        className="flex items-center justify-center h-8 w-8 rounded-md flex-shrink-0"
        style={{ background: "rgba(255,255,255,0.04)" }}
      >
        <Icon
          className={`h-4 w-4 ${pulse ? "animate-pulse" : ""}`}
          style={{ color: accent }}
        />
      </div>
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-wider text-[#8a8f98]">
          {label}
        </p>
        <p
          className="text-sm font-semibold truncate mt-0.5"
          style={{ color: accent }}
        >
          {value}
        </p>
      </div>
    </div>
  );
};

// ── Talk (two-way audio) button — WebRTC publish path ────────────────────────

const TalkButton = ({ cameraId }) => {
  const [isTalking, setIsTalking] = useState(false);
  const [loading, setLoading] = useState(false);
  const pcRef = useRef(null);
  const localStreamRef = useRef(null);

  const stopTalk = () => {
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }
    if (localStreamRef.current) {
      localStreamRef.current.getAudioTracks().forEach((t) => t.stop());
      localStreamRef.current = null;
    }
    setIsTalking(false);
    setLoading(false);
  };

  const startTalk = async () => {
    setLoading(true);
    try {
      // 1. Request mic
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
          video: false,
        });
      } catch (micErr) {
        toast.error("Microphone access denied");
        setLoading(false);
        return;
      }
      localStreamRef.current = stream;

      // 2. Build PeerConnection
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
      });
      pcRef.current = pc;

      // Add mic tracks so the offer contains a sendonly audio m-line
      stream.getAudioTracks().forEach((t) => pc.addTrack(t, stream));

      // 3. Create offer and set local description
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // 4. POST offer to backend — get SDP answer
      let answerSdp;
      let result;
      try {
        result = await postBackchannelWebrtcSignal(cameraId, offer.sdp);
        answerSdp = result.sdp;
      } catch (err) {
        const status = err?.response?.status;
        if (status === 503) {
          toast.error("Camera does not support two-way audio");
        } else {
          const detail = err?.response?.data?.detail || err?.message || "WebRTC signaling failed";
          toast.error(detail);
        }
        stopTalk();
        return;
      }

      // 5. Apply SDP answer
      await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

      // Handle unexpected peer disconnect
      pc.onconnectionstatechange = () => {
        if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
          stopTalk();
        }
      };

      setIsTalking(true);
      const pathLabel = result?.audio_path === "webrtc" ? "WebRTC" : "audio";
      toast.success(`Talk active — speaking to camera (${pathLabel})`);
    } catch (err) {
      const msg = err?.message || "Failed to start talk mode";
      toast.error(msg);
      stopTalk();
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      variant={isTalking ? "destructive" : "outline"}
      size="sm"
      onClick={isTalking ? stopTalk : startTalk}
      disabled={loading}
      title="Two-way audio (Talk)"
    >
      {isTalking ? (
        <>
          <MicOff className="h-4 w-4 mr-1" /> Stop Talk
        </>
      ) : (
        <>
          <Mic className="h-4 w-4 mr-1" /> Talk
        </>
      )}
    </Button>
  );
};

// ── Main Component ───────────────────────────────────────────────────────────

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
        {/* Two-way audio Talk button */}
        <TalkButton cameraId={cameraId} />
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

        {/* Live telemetry tiles — 2-col grid on mobile, single col on lg */}
        <div className="grid grid-cols-2 lg:grid-cols-1 gap-3">
          <StatTile
            icon={Activity}
            label="Status"
            value={isOnline ? "Online" : camera.status || "Offline"}
            tone={isOnline ? "var(--console-online)" : "var(--console-offline)"}
            pulse={isOnline}
          />
          <StatTile
            icon={camera.is_recording ? Video : Square}
            label="Recording"
            value={camera.is_recording ? "Recording" : "Idle"}
            tone={camera.is_recording ? "var(--console-rec)" : "var(--console-muted)"}
            pulse={camera.is_recording}
          />
          <StatTile
            icon={Monitor}
            label="Resolution"
            value={camera.resolution || "—"}
          />
          <StatTile
            icon={Gauge}
            label="FPS"
            value={camera.fps ? `${camera.fps} fps` : "—"}
          />
          <StatTile
            icon={Move3d}
            label="PTZ"
            value={camera.ptz_capable ? "Supported" : "Not available"}
            tone={camera.ptz_capable ? "var(--console-accent)" : "var(--console-muted)"}
          />
          <StatTile
            icon={Radio}
            label="Two-way Audio"
            value={camera.has_backchannel ? "Supported" : "—"}
            tone={camera.has_backchannel ? "var(--console-accent)" : "var(--console-muted)"}
          />
        </div>
      </div>
    </div>
  );
};

export default LiveViewPage;
