// =============================================================================
// WebRTC Stream Player Component - Low-latency live streaming via go2rtc
// =============================================================================
// Uses WebRTC for ultra-low latency live camera viewing.
// go2rtc WebRTC endpoint: POST /api/webrtc?src={streamId}
// Falls back to MSE if WebRTC fails.
// =============================================================================

import React, { useEffect, useRef, useState, useCallback } from "react";
import { AlertCircle, Loader2, Play, RefreshCw } from "lucide-react";
import { cn } from "../../lib/utils";
import { BACKEND_URL, getAccessToken } from "../../api/client";

const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RECONNECT_DELAY = 2000;
// If the peer connects but no actual video frames arrive within this window we
// treat the tile as a failed attempt and retry instead of showing frozen black.
const MEDIA_WATCHDOG_MS = 8000;
const ICE_SERVERS = [
  { urls: "stun:stun.l.google.com:19302" },
  { urls: "stun:stun1.l.google.com:19302" },
];

export const WebRTCPlayer = ({
  streamId,
  cameraId,
  autoPlay = true,
  muted = true,
  controls = false,
  className,
  onError,
  onPlay,
  onPause,
  onConnected,
}) => {
  const videoRef = useRef(null);
  const pcRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const mountedRef = useRef(true);
  const scheduleReconnectRef = useRef(null);
  const attemptIceRestartRef = useRef(null);
  // Guards against multiple overlapping transient-recovery timers.
  const iceRestartingRef = useRef(false);
  // Watchdog that fires if no real frames arrive after connecting.
  const mediaWatchdogRef = useRef(null);
  // Set true once the <video> reports playable frames for this attempt.
  const gotMediaRef = useRef(false);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [needsUserInteraction, setNeedsUserInteraction] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [connectionState, setConnectionState] = useState("new");

  const GO2RTC_URL =
    process.env.REACT_APP_GO2RTC_URL || "/go2rtc";

  // Cleanup WebRTC connection
  const cleanup = useCallback(() => {
    if (mediaWatchdogRef.current) {
      clearTimeout(mediaWatchdogRef.current);
      mediaWatchdogRef.current = null;
    }
    if (pcRef.current) {
      pcRef.current.ontrack = null;
      pcRef.current.onicecandidate = null;
      pcRef.current.oniceconnectionstatechange = null;
      pcRef.current.onconnectionstatechange = null;
      pcRef.current.close();
      pcRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  // Create WebRTC offer and connect to go2rtc
  const connect = useCallback(async () => {
    if (!streamId || !mountedRef.current) return;

    setIsLoading(true);
    setError(null);
    gotMediaRef.current = false;
    cleanup();

    try {
      // Create RTCPeerConnection
      const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
      pcRef.current = pc;

      // Handle incoming tracks (video/audio from camera)
      pc.ontrack = (event) => {
        if (!mountedRef.current) return;

        if (videoRef.current && event.streams[0]) {
          videoRef.current.srcObject = event.streams[0];

          // Try to play
          if (autoPlay) {
            videoRef.current.play().catch((e) => {
              console.warn("[WebRTC] Autoplay blocked:", e);
              if (mountedRef.current) setNeedsUserInteraction(true);
            });
          }
        }
      };

      // Monitor connection state
      pc.onconnectionstatechange = () => {
        if (!mountedRef.current) return;
        const state = pc.connectionState;
        setConnectionState(state);

        switch (state) {
          case "connected":
            // ICE is connected, but media may not be flowing yet. Don't clear
            // the loading state on the connection signal alone — wait for the
            // <video> to actually report frames (handled by the watchdog +
            // video 'playing' listener). Arm a watchdog so an ICE-connected-
            // but-no-RTP tile retries instead of showing frozen black.
            setReconnecting(false);
            if (onConnected) onConnected();
            if (mediaWatchdogRef.current) clearTimeout(mediaWatchdogRef.current);
            if (!gotMediaRef.current) {
              mediaWatchdogRef.current = setTimeout(() => {
                if (!mountedRef.current) return;
                // currentTime advancing is the most reliable "frames arrived"
                // signal across browsers.
                const v = videoRef.current;
                const playing =
                  gotMediaRef.current ||
                  (v && v.readyState >= 2 && v.currentTime > 0);
                if (!playing) {
                  // Connected but no media — treat as a failed attempt.
                  scheduleReconnectRef.current?.();
                }
              }, MEDIA_WATCHDOG_MS);
            } else {
              setIsLoading(false);
            }
            break;
          case "disconnected":
            // Transient by spec — ICE may recover on its own. Try an ICE
            // restart rather than counting it as a hard failure. If it doesn't
            // recover it will transition to 'failed' and be retried for real.
            attemptIceRestartRef.current?.();
            break;
          case "failed":
            scheduleReconnectRef.current?.();
            break;
          case "closed":
            // Don't reconnect if intentionally closed
            break;
          default:
            break;
        }
      };

      pc.oniceconnectionstatechange = () => {
        if (!mountedRef.current) return;
        // 'disconnected'/'failed' at the ICE layer also warrant an ICE restart
        // attempt; the connection-state handler covers the higher-level cases.
        if (pc.iceConnectionState === "failed") {
          attemptIceRestartRef.current?.();
        }
      };

      // Add transceivers for receiving media
      pc.addTransceiver("video", { direction: "recvonly" });
      pc.addTransceiver("audio", { direction: "recvonly" });

      // Create offer
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // Wait for ICE gathering to complete (or timeout after 2s)
      await new Promise((resolve) => {
        if (pc.iceGatheringState === "complete") {
          resolve();
        } else {
          const checkState = () => {
            if (pc.iceGatheringState === "complete") {
              pc.removeEventListener("icegatheringstatechange", checkState);
              resolve();
            }
          };
          pc.addEventListener("icegatheringstatechange", checkState);
          // Timeout after 2 seconds
          setTimeout(resolve, 2000);
        }
      });

      // Send offer to backend proxy (re-registers stream with go2rtc) or directly to go2rtc
      let answerSDP;
      if (cameraId) {
        // Route through backend — ensures stream registration + auth
        const token = getAccessToken();
        const response = await fetch(
          `${BACKEND_URL}/api/cameras/${encodeURIComponent(cameraId)}/webrtc-signal`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ sdp: pc.localDescription.sdp }),
          },
        );
        if (!response.ok) {
          throw new Error(`WebRTC signaling failed: ${response.status}`);
        }
        const data = await response.json();
        answerSDP = data.sdp;
      } else {
        // Direct go2rtc (fallback)
        const GO2RTC_URL =
          process.env.REACT_APP_GO2RTC_URL || "/go2rtc";
        const response = await fetch(
          `${GO2RTC_URL}/api/webrtc?src=${encodeURIComponent(streamId)}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/sdp" },
            body: pc.localDescription.sdp,
          },
        );
        if (!response.ok) {
          throw new Error(`WebRTC signaling failed: ${response.status}`);
        }
        answerSDP = await response.text();
      }

      // Set remote description
      await pc.setRemoteDescription({
        type: "answer",
        sdp: answerSDP,
      });

    } catch (err) {
      if (mountedRef.current) {
        setError("Couldn't load live view. Click to retry.");
        setIsLoading(false);
        scheduleReconnectRef.current?.();
      }
      if (onError) onError(err);
    }
  }, [streamId, cameraId, autoPlay, cleanup, onError, onConnected]);

  // Schedule reconnect with exponential backoff
  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current) return;

    if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
      setError("Connection lost. Click to retry.");
      setIsLoading(false);
      setReconnecting(false);
      return;
    }

    const attempt = reconnectAttemptsRef.current;
    const delay = BASE_RECONNECT_DELAY * Math.pow(2, attempt);
    reconnectAttemptsRef.current = attempt + 1;
    setReconnecting(true);
    setIsLoading(false);

    clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = setTimeout(() => {
      if (mountedRef.current) connect();
    }, delay);
  }, [connect]);

  // Attempt recovery from a TRANSIENT ICE 'disconnected'/'failed' (ICE layer)
  // by re-running full negotiation. This does NOT consume a hard-failure
  // attempt — only a genuine 'failed' connectionState or a no-media watchdog
  // does. A short grace delay gives ICE a chance to self-heal first.
  const attemptIceRestart = useCallback(() => {
    if (!mountedRef.current || iceRestartingRef.current) return;
    iceRestartingRef.current = true;
    setReconnecting(true);
    clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = setTimeout(() => {
      iceRestartingRef.current = false;
      if (!mountedRef.current) return;
      const pc = pcRef.current;
      // If ICE recovered on its own, do nothing.
      if (pc && pc.connectionState === "connected") {
        setReconnecting(false);
        return;
      }
      connect();
    }, 1500);
  }, [connect]);

  // Update the refs when callbacks change
  useEffect(() => {
    scheduleReconnectRef.current = scheduleReconnect;
  }, [scheduleReconnect]);

  useEffect(() => {
    attemptIceRestartRef.current = attemptIceRestart;
  }, [attemptIceRestart]);

  // Manual retry
  const handleRetry = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    iceRestartingRef.current = false;
    gotMediaRef.current = false;
    setError(null);
    // connect() re-runs the full offer/answer negotiation from scratch.
    connect();
  }, [connect]);

  // Initial connection
  useEffect(() => {
    mountedRef.current = true;
    reconnectAttemptsRef.current = 0;
    connect();

    return () => {
      mountedRef.current = false;
      clearTimeout(reconnectTimerRef.current);
      cleanup();
    };
  }, [connect, cleanup]);

  // Video event listeners
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handlePlayEvt = () => {
      setNeedsUserInteraction(false);
      if (onPlay) onPlay();
    };
    const handlePauseEvt = () => {
      if (onPause) onPause();
    };
    // Real frames are flowing — clear loading and the no-media watchdog, and
    // reset the failure counter now that the tile is genuinely live.
    const handleMediaFlowing = () => {
      if (!mountedRef.current) return;
      gotMediaRef.current = true;
      if (mediaWatchdogRef.current) {
        clearTimeout(mediaWatchdogRef.current);
        mediaWatchdogRef.current = null;
      }
      setIsLoading(false);
      setReconnecting(false);
      setError(null);
      reconnectAttemptsRef.current = 0;
    };
    // Media stalled/errored after starting — try to reconnect rather than
    // freezing on a stale frame.
    const handleStalled = () => {
      if (!mountedRef.current || !gotMediaRef.current) return;
      gotMediaRef.current = false;
      scheduleReconnectRef.current?.();
    };

    video.addEventListener("play", handlePlayEvt);
    video.addEventListener("pause", handlePauseEvt);
    video.addEventListener("playing", handleMediaFlowing);
    video.addEventListener("loadeddata", handleMediaFlowing);
    video.addEventListener("stalled", handleStalled);
    video.addEventListener("error", handleStalled);

    return () => {
      video.removeEventListener("play", handlePlayEvt);
      video.removeEventListener("pause", handlePauseEvt);
      video.removeEventListener("playing", handleMediaFlowing);
      video.removeEventListener("loadeddata", handleMediaFlowing);
      video.removeEventListener("stalled", handleStalled);
      video.removeEventListener("error", handleStalled);
    };
  }, [onPlay, onPause]);

  // Handle click to play
  const handleClickToPlay = () => {
    if (videoRef.current && needsUserInteraction) {
      videoRef.current
        .play()
        .then(() => setNeedsUserInteraction(false))
        .catch((err) => console.error("Failed to play:", err));
    }
  };

  return (
    <div
      className={cn(
        "relative w-full h-full bg-black rounded-lg overflow-hidden",
        className,
      )}
    >
      {/* Loading overlay */}
      {isLoading && !error && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/50 z-10">
          <div className="flex flex-col items-center space-y-2">
            <Loader2 className="h-8 w-8 animate-spin text-white" />
            <span className="text-sm text-white">Loading live view…</span>
          </div>
        </div>
      )}

      {/* Reconnecting overlay */}
      {reconnecting && !isLoading && !error && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/40 z-10">
          <div className="flex flex-col items-center space-y-2">
            <RefreshCw className="h-6 w-6 animate-spin text-amber-400" />
            <span className="text-sm text-amber-300">
              Reconnecting (attempt {reconnectAttemptsRef.current}/
              {MAX_RECONNECT_ATTEMPTS})...
            </span>
          </div>
        </div>
      )}

      {/* Click to play overlay */}
      {needsUserInteraction && !error && (
        <div
          className="absolute inset-0 flex items-center justify-center bg-black/70 z-20 cursor-pointer hover:bg-black/80 transition-colors"
          onClick={handleClickToPlay}
        >
          <div className="flex flex-col items-center space-y-3">
            <div className="bg-card/20 backdrop-blur-sm rounded-full p-6 hover:bg-card/30 transition-colors">
              <Play className="h-12 w-12 text-white fill-white" />
            </div>
            <span className="text-sm text-white font-medium">
              Click to play
            </span>
          </div>
        </div>
      )}

      {/* Error overlay with retry */}
      {error && (
        <div
          className="absolute inset-0 flex items-center justify-center bg-black/50 z-10 cursor-pointer"
          onClick={handleRetry}
        >
          <div className="flex flex-col items-center space-y-2 text-red-400 px-4 text-center">
            <AlertCircle className="h-8 w-8" />
            <span className="text-sm">{error}</span>
            <span className="text-xs text-white/60 mt-1">
              Click anywhere to retry
            </span>
          </div>
        </div>
      )}

      {/* Video element */}
      <video
        ref={videoRef}
        className="w-full h-full object-contain"
        muted={muted}
        controls={controls}
        playsInline
        autoPlay={autoPlay}
      />
    </div>
  );
};

export default WebRTCPlayer;
