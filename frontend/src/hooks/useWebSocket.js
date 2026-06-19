// =============================================================================
// useWebSocket - Real-time WebSocket connection for live updates
// =============================================================================

import { useState, useEffect, useCallback, useRef } from "react";
import { BACKEND_URL, getAccessToken } from "../api/client";

/**
 * WebSocket connection states
 */
export const WS_STATE = {
  CONNECTING: "connecting",
  CONNECTED: "connected",
  DISCONNECTED: "disconnected",
  ERROR: "error",
};

// Upper bound for reconnect backoff. After maxReconnectAttempts the hook keeps
// retrying at this interval forever rather than giving up permanently.
const MAX_RECONNECT_DELAY = 30000;

/**
 * Custom hook for WebSocket connection to the NVR backend.
 *
 * @param {Object} options - Configuration options
 * @param {string[]} options.channels - Channels to subscribe to: "cameras", "events", "system", "all"
 * @param {function} options.onCameraUpdate - Callback for camera status updates
 * @param {function} options.onSystemEvent - Callback for system events
 * @param {function} options.onConnected - Callback when connection is established
 * @param {function} options.onDisconnected - Callback when connection is lost
 * @param {boolean} options.autoReconnect - Whether to auto-reconnect on disconnect (default: true)
 * @param {number} options.reconnectInterval - Milliseconds between reconnect attempts (default: 5000)
 * @param {number} options.maxReconnectAttempts - Max reconnect attempts before giving up (default: 10)
 * @returns {Object} WebSocket state and control functions
 */
export function useWebSocket({
  channels = ["all"],
  onCameraUpdate,
  onSystemEvent,
  onNewEvent,
  onConnected,
  onDisconnected,
  autoReconnect = true,
  reconnectInterval = 5000,
  maxReconnectAttempts = 10,
} = {}) {
  const [connectionState, setConnectionState] = useState(WS_STATE.DISCONNECTED);
  const [lastMessage, setLastMessage] = useState(null);
  const [reconnectCount, setReconnectCount] = useState(0);

  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const pingIntervalRef = useRef(null);
  const reconnectCountRef = useRef(0);

  // Keep ref in sync with state so closures see current value
  useEffect(() => {
    reconnectCountRef.current = reconnectCount;
  }, [reconnectCount]);

  /**
   * Build WebSocket URL. The auth token is NOT placed in the URL (it would
   * leak into logs/history); it is sent as the first message after open.
   */
  const buildWsUrl = useCallback(() => {
    const token = getAccessToken();
    if (!token) return null;

    // Convert http(s):// to ws(s)://
    const wsProtocol = BACKEND_URL.startsWith("https") ? "wss" : "ws";
    const wsBase = BACKEND_URL.replace(/^https?/, wsProtocol);
    const channelParam = channels.join(",");

    return `${wsBase}/api/ws?channels=${channelParam}`;
  }, [channels]);

  /**
   * Handle incoming WebSocket messages
   */
  const handleMessage = useCallback(
    (event) => {
      try {
        const data = JSON.parse(event.data);
        setLastMessage(data);

        switch (data.type) {
          case "connected":
            setConnectionState(WS_STATE.CONNECTED);
            setReconnectCount(0);
            onConnected?.(data);
            break;

          case "camera_status":
            onCameraUpdate?.(data.data);
            break;

          case "system_event":
            onSystemEvent?.(data.data);
            break;

          case "new_event":
          case "linkage_event":
            onNewEvent?.(data.data);
            break;

          case "pong":
            // Heartbeat response - connection is alive
            break;

          case "error":
            console.warn("WebSocket error message:", data.message);
            break;

          default:
            // Handle other message types if needed
            break;
        }
      } catch (err) {
        console.error("Failed to parse WebSocket message:", err);
      }
    },
    [onCameraUpdate, onSystemEvent, onNewEvent, onConnected]
  );

  /**
   * Connect to WebSocket server
   */
  const connect = useCallback(() => {
    // Avoid stacking sockets when React StrictMode double-invokes effects
    // or when channel deps change mid-handshake.
    if (wsRef.current) {
      const rs = wsRef.current.readyState;
      if (rs === WebSocket.OPEN || rs === WebSocket.CONNECTING) {
        return;
      }
      try {
        wsRef.current.close();
      } catch {
        /* ignore */
      }
    }

    const url = buildWsUrl();
    if (!url) {
      console.warn("Cannot connect to WebSocket: No auth token");
      setConnectionState(WS_STATE.ERROR);
      return;
    }

    setConnectionState(WS_STATE.CONNECTING);

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        // Authenticate as the first message — the backend requires an auth
        // frame before it registers channels or sends the welcome message.
        const token = getAccessToken();
        if (token) {
          ws.send(JSON.stringify({ type: "auth", token }));
        }

        // Start ping interval to keep connection alive
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
          }
        }, 30000);
      };

      ws.onmessage = handleMessage;

      ws.onerror = () => {
        // Don't log — the matching `close` event already tells the story
        // and React StrictMode dev double-invocation produces noisy
        // first-attempt errors that aren't real failures.
        setConnectionState(WS_STATE.ERROR);
      };

      ws.onclose = (event) => {
        setConnectionState(WS_STATE.DISCONNECTED);
        onDisconnected?.();

        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }

        // Auto-reconnect if enabled and not intentionally closed (1000 =
        // normal close, 1008 = policy violation / auth rejected — don't retry).
        if (autoReconnect && event.code !== 1000 && event.code !== 1008) {
          // Never permanently give up. Below maxReconnectAttempts we use a
          // fast exponential backoff; once past the cap we keep retrying on a
          // long capped interval so a backend that comes back is reconnected.
          // Jitter avoids a thundering-herd reconnect storm.
          const attempt = reconnectCountRef.current;
          let delay;
          if (attempt < maxReconnectAttempts) {
            // Exponential backoff capped at 30s, based on the configured base
            // interval (e.g. 5s, 10s, 20s, 30s, 30s…).
            const backoff = reconnectInterval * Math.pow(2, attempt);
            delay = Math.min(backoff, MAX_RECONNECT_DELAY);
          } else {
            // Past the cap: keep trying forever on the long interval.
            delay = MAX_RECONNECT_DELAY;
          }
          // Add up to ±20% jitter.
          const jitter = delay * 0.2 * (Math.random() * 2 - 1);
          delay = Math.max(1000, Math.round(delay + jitter));

          reconnectTimerRef.current = setTimeout(() => {
            setReconnectCount((c) => c + 1);
            connect();
          }, delay);
        }
      };
    } catch (err) {
      console.error("Failed to create WebSocket:", err);
      setConnectionState(WS_STATE.ERROR);
    }
  }, [
    buildWsUrl,
    handleMessage,
    onDisconnected,
    autoReconnect,
    reconnectInterval,
    maxReconnectAttempts,
    reconnectCount,
  ]);

  /**
   * Disconnect from WebSocket server
   */
  const disconnect = useCallback(() => {
    // Clear reconnect timer
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    // Clear ping interval
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }

    // Close WebSocket
    if (wsRef.current) {
      wsRef.current.close(1000, "User disconnected");
      wsRef.current = null;
    }

    setConnectionState(WS_STATE.DISCONNECTED);
    setReconnectCount(0);
  }, []);

  /**
   * Send a message to the server
   */
  const sendMessage = useCallback((message) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
      return true;
    }
    return false;
  }, []);

  /**
   * Subscribe to additional channels
   */
  const subscribe = useCallback(
    (newChannels) => {
      return sendMessage({
        type: "subscribe",
        channels: Array.isArray(newChannels) ? newChannels : [newChannels],
      });
    },
    [sendMessage]
  );

  /**
   * Unsubscribe from channels
   */
  const unsubscribe = useCallback(
    (channelsToRemove) => {
      return sendMessage({
        type: "unsubscribe",
        channels: Array.isArray(channelsToRemove)
          ? channelsToRemove
          : [channelsToRemove],
      });
    },
    [sendMessage]
  );

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    const token = getAccessToken();
    if (token) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Reconnect when channels change
  useEffect(() => {
    if (connectionState === WS_STATE.CONNECTED) {
      // Reconnect with new channels
      disconnect();
      connect();
    }
  }, [channels.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    connectionState,
    isConnected: connectionState === WS_STATE.CONNECTED,
    isConnecting: connectionState === WS_STATE.CONNECTING,
    lastMessage,
    reconnectCount,
    connect,
    disconnect,
    sendMessage,
    subscribe,
    unsubscribe,
  };
}

export default useWebSocket;
