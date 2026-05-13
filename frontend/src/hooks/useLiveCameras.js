// =============================================================================
// useLiveCameras — Real-time camera data via WebSocket + React Query
// =============================================================================

import { useCallback, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCamerasQuery } from "./useCameras";
import { useWebSocket, WS_STATE } from "./useWebSocket";
import { useNotifications } from "./useNotifications";

/**
 * Enhanced camera hook that uses WebSocket for real-time updates.
 * 
 * Combines:
 * - React Query for data fetching and caching
 * - WebSocket for instant status updates
 * - Browser notifications for alerts
 * 
 * When a camera status change comes via WebSocket, it updates the
 * React Query cache immediately without requiring a refetch.
 * 
 * Falls back to polling if WebSocket is disconnected.
 * 
 * @param {Object} options - Options to pass to useCamerasQuery
 * @param {boolean} options.enableNotifications - Enable browser notifications (default: true)
 * @returns {Object} Camera data plus WebSocket connection state
 */
export function useLiveCameras(options = {}) {
  const { enableNotifications = true, ...queryOptions } = options;
  const queryClient = useQueryClient();
  
  // Browser notifications
  const notifications = useNotifications({
    enabled: enableNotifications,
    autoClose: 5000,
  });
  
  // Base camera query - reduce polling interval since WebSocket handles updates
  const camerasQuery = useCamerasQuery({
    refetchInterval: 30000, // Fallback refresh every 30s
    ...queryOptions,
  });

  /**
   * Handle camera status updates from WebSocket
   * Updates specific camera in the cache without full refetch
   */
  const handleCameraUpdate = useCallback(
    (update) => {
      if (!update?.camera_id) return;

      queryClient.setQueryData(["cameras"], (oldData) => {
        if (!Array.isArray(oldData)) return oldData;

        return oldData.map((camera) => {
          if (camera.id === update.camera_id) {
            // Trigger notification if status changed
            if (update.status && update.status !== camera.status) {
              notifications.notifyCameraStatus(
                camera.name,
                update.status,
                camera.id
              );
            }
            
            // Trigger notification for recording state change
            if (update.is_recording !== undefined && update.is_recording !== camera.is_recording) {
              notifications.notifyRecording(
                camera.name,
                update.is_recording,
                camera.id
              );
            }

            return {
              ...camera,
              status: update.status ?? camera.status,
              is_recording: update.is_recording ?? camera.is_recording,
              last_seen: update.last_seen ?? camera.last_seen,
              error_message: update.error_message ?? camera.error_message,
            };
          }
          return camera;
        });
      });
    },
    [queryClient, notifications]
  );

  /**
   * Handle system events
   */
  const handleSystemEvent = useCallback(
    (event) => {
      // System events could trigger various refreshes
      if (event?.event_type === "cameras_changed") {
        queryClient.invalidateQueries({ queryKey: ["cameras"] });
      }
      
      // Show system notification
      if (event?.message) {
        notifications.notifySystem(
          event.title || "System Event",
          event.message,
          event.severity || "info"
        );
      }
    },
    [queryClient, notifications]
  );

  // Connect to WebSocket
  const ws = useWebSocket({
    channels: ["cameras"],
    onCameraUpdate: handleCameraUpdate,
    onSystemEvent: handleSystemEvent,
    autoReconnect: true,
    reconnectInterval: 5000,
    maxReconnectAttempts: 20,
  });

  // If WebSocket disconnects, increase polling rate temporarily
  useEffect(() => {
    if (ws.connectionState === WS_STATE.DISCONNECTED) {
      // Trigger immediate refetch when disconnected
      camerasQuery.refetch();
    }
  }, [ws.connectionState]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    // Camera data from React Query
    cameras: camerasQuery.data ?? [],
    isLoading: camerasQuery.isLoading,
    isError: camerasQuery.isError,
    error: camerasQuery.error,
    refetch: camerasQuery.refetch,
    
    // WebSocket state
    isLive: ws.isConnected,
    wsState: ws.connectionState,
    reconnectCount: ws.reconnectCount,
    
    // Notifications
    notificationsEnabled: notifications.isGranted,
    requestNotificationPermission: notifications.requestPermission,
    
    // Full query object if needed
    query: camerasQuery,
  };
}

export default useLiveCameras;
