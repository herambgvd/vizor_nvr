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

  /**
   * Build WebSocket URL with authentication
   */
  const buildWsUrl = useCallback(() => {
    const token = getAccessToken();
    if (!token) return null;

    // Convert http(s):// to ws(s)://
    const wsProtocol = BACKEND_URL.startsWith("https") ? "wss" : "ws";
    const wsBase = BACKEND_URL.replace(/^https?/, wsProtocol);
    const channelParam = channels.join(",");

    return `${wsBase}/api/ws?token=${token}&channels=${channelParam}`;
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
    [onCameraUpdate, onSystemEvent, onConnected]
  );

  /**
   * Connect to WebSocket server
   */
  const connect = useCallback(() => {
    // Clear any existing connection
    if (wsRef.current) {
      wsRef.current.close();
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
        console.log("WebSocket connected");
        // Start ping interval to keep connection alive
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
          }
        }, 30000);
      };

      ws.onmessage = handleMessage;

      ws.onerror = (error) => {
        console.error("WebSocket error:", error);
        setConnectionState(WS_STATE.ERROR);
      };

      ws.onclose = (event) => {
        console.log("WebSocket closed:", event.code, event.reason);
        setConnectionState(WS_STATE.DISCONNECTED);
        onDisconnected?.();

        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }

        // Auto-reconnect if enabled and not intentionally closed
        if (autoReconnect && event.code !== 1000 && event.code !== 1008) {
          if (reconnectCount < maxReconnectAttempts) {
            console.log(
              `Reconnecting in ${reconnectInterval}ms... (attempt ${reconnectCount + 1}/${maxReconnectAttempts})`
            );
            reconnectTimerRef.current = setTimeout(() => {
              setReconnectCount((c) => c + 1);
              connect();
            }, reconnectInterval);
          } else {
            console.warn("Max reconnect attempts reached");
          }
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
