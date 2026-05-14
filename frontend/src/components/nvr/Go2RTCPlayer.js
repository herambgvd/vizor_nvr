// =============================================================================
// go2rtc Stream Player Component - MSE (Media Source Extensions) Player
// =============================================================================
// Video player for live RTSP camera streams via go2rtc.
// Uses MSE over WebSocket for reliable, low-latency playback.
// go2rtc endpoint: ws://{host}/api/ws?src={streamId}
// =============================================================================

import React, { useEffect, useRef, useState, useCallback } from "react";
import { AlertCircle, Loader2, Play, RefreshCw } from "lucide-react";
import { cn } from "../../lib/utils";

const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RECONNECT_DELAY = 2000;
const MAX_BUFFER_QUEUE_SIZE = 20; // Prevent unbounded memory growth

export const Go2RTCPlayer = ({
  streamId,
  autoPlay = true,
  muted = true,
  controls = true,
  className,
  onError,
  onPlay,
  onPause,
}) => {
  const videoRef = useRef(null);
  const wsRef = useRef(null);
  const msRef = useRef(null);
  const sbRef = useRef(null);
  const bufferQueue = useRef([]);
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const mountedRef = useRef(true);
  const gotFirstDataRef = useRef(false);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [needsUserInteraction, setNeedsUserInteraction] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);

  // Cleanup WebSocket + MediaSource
  const cleanup = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onmessage = null;
      wsRef.current.onerror = null;
      wsRef.current.onclose = null;
      if (wsRef.current.readyState <= 1) wsRef.current.close();
      wsRef.current = null;
    }
    if (sbRef.current) {
      try {
        sbRef.current.abort();
      } catch (_) {}
      sbRef.current = null;
    }
    if (msRef.current) {
      try {
        if (msRef.current.readyState === "open") msRef.current.endOfStream();
      } catch (_) {}
      msRef.current = null;
    }
    bufferQueue.current = [];
    if (videoRef.current) {
      videoRef.current.src = "";
      videoRef.current.load();
    }
  }, []);

  // Flush queued buffers into SourceBuffer
  const flushQueue = useCallback(() => {
    const sb = sbRef.current;
    if (!sb || sb.updating || bufferQueue.current.length === 0) return;
    const chunk = bufferQueue.current.shift();
    try {
      sb.appendBuffer(chunk);
    } catch (e) {
      console.error("SourceBuffer append error:", e);
    }
  }, []);

  // MSE connect via WebSocket
  const connect = useCallback(() => {
    if (!streamId || !videoRef.current || !mountedRef.current) return;

    setIsLoading(true);
    setError(null);
    gotFirstDataRef.current = false;
    cleanup();

    const GO2RTC_URL =
      process.env.REACT_APP_GO2RTC_URL || "http://localhost:1984";
    const wsUrl = GO2RTC_URL.replace(/^http/, "ws") + `/api/ws?src=${streamId}`;

    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    let mimeCodec = "";
    let mediaSource = null;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      // go2rtc MSE protocol: first text message has codec info,
      // then binary MP4 init segment, then binary media segments
    };

    ws.onmessage = (ev) => {
      if (!mountedRef.current) return;

      // Text message = codec info from go2rtc (e.g. "mse" or codec string)
      if (typeof ev.data === "string") {
        // go2rtc sends the MSE codec string like:
        // video/mp4; codecs="avc1.640029" or similar
        mimeCodec = ev.data;

        // If go2rtc sends just "mse", default to a common codec
        if (!mimeCodec.includes("video/")) {
          mimeCodec = 'video/mp4; codecs="avc1.640029"';
        }

        if (!MediaSource.isTypeSupported(mimeCodec)) {
          // Try common fallback
          mimeCodec = 'video/mp4; codecs="avc1.42E01E"';
        }

        // Create MediaSource and attach to video
        mediaSource = new MediaSource();
        msRef.current = mediaSource;
        videoRef.current.src = URL.createObjectURL(mediaSource);

        mediaSource.addEventListener("sourceopen", () => {
          if (!mountedRef.current) return;
          try {
            const sb = mediaSource.addSourceBuffer(mimeCodec);
            sbRef.current = sb;
            sb.mode = "segments";
            sb.addEventListener("updateend", () => {
              flushQueue();
              // Keep buffer trimmed to avoid memory bloat (keep last 30s)
              if (sb.buffered.length > 0 && !sb.updating) {
                const end = sb.buffered.end(sb.buffered.length - 1);
                const start = sb.buffered.start(0);
                if (end - start > 60) {
                  try {
                    sb.remove(start, end - 30);
                  } catch (_) {}
                }
              }
            });
          } catch (e) {
            console.error("addSourceBuffer error:", e);
            if (mountedRef.current) {
              setError("Codec not supported: " + mimeCodec);
              setIsLoading(false);
            }
          }
        });
        return;
      }

      // Binary message = MP4 segment data
      const data = new Uint8Array(ev.data);
      if (sbRef.current) {
        // Limit buffer queue size to prevent unbounded memory growth
        if (bufferQueue.current.length < MAX_BUFFER_QUEUE_SIZE) {
          bufferQueue.current.push(data);
        } else {
          // Queue is full - drop oldest chunks to make room
          // This indicates network or SourceBuffer issues
          console.warn("Go2RTC buffer queue full, dropping oldest chunks");
          while (bufferQueue.current.length >= MAX_BUFFER_QUEUE_SIZE - 5) {
            bufferQueue.current.shift();
          }
          bufferQueue.current.push(data);
        }
        flushQueue();

        // First data received => stream is playing
        if (!gotFirstDataRef.current) {
          gotFirstDataRef.current = true;
          setIsLoading(false);
          setReconnecting(false);
          reconnectAttemptsRef.current = 0;
          if (autoPlay && videoRef.current) {
            videoRef.current.play().catch(() => {
              if (mountedRef.current) setNeedsUserInteraction(true);
            });
          }
        }
      }
    };

    ws.onerror = () => {
      if (!mountedRef.current) return;
      console.error("MSE WebSocket error for stream:", streamId);
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      scheduleReconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streamId, autoPlay, onError, cleanup, flushQueue]);

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

  // Manual retry
  const handleRetry = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    setError(null);
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
      if (onPlay) onPlay();
    };
    const handlePauseEvt = () => {
      if (onPause) onPause();
    };

    video.addEventListener("play", handlePlayEvt);
    video.addEventListener("pause", handlePauseEvt);

    return () => {
      video.removeEventListener("play", handlePlayEvt);
      video.removeEventListener("pause", handlePauseEvt);
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
            <span className="text-sm text-white">Connecting...</span>
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

export default Go2RTCPlayer;
