// =============================================================================
// useNotifications — Browser notifications with WebSocket integration
// =============================================================================

import { useState, useEffect, useCallback, useRef } from "react";

/**
 * Notification permission states
 */
export const NOTIFICATION_STATUS = {
  DEFAULT: "default",
  GRANTED: "granted",
  DENIED: "denied",
  NOT_SUPPORTED: "not-supported",
};

/**
 * Custom hook for browser desktop notifications.
 * 
 * @param {Object} options - Configuration options
 * @param {boolean} options.enabled - Whether notifications are enabled (default: true)
 * @param {string} options.icon - Default icon URL for notifications
 * @param {number} options.autoClose - Auto-close timeout in ms (default: 5000, 0 for no auto-close)
 * @returns {Object} Notification state and functions
 */
export function useNotifications({
  enabled = true,
  icon = "/favicon.ico",
  autoClose = 5000,
} = {}) {
  const [permission, setPermission] = useState(() => {
    if (typeof window === "undefined" || !("Notification" in window)) {
      return NOTIFICATION_STATUS.NOT_SUPPORTED;
    }
    return Notification.permission;
  });

  const activeNotifications = useRef(new Map());

  /**
   * Check if notifications are supported
   */
  const isSupported = permission !== NOTIFICATION_STATUS.NOT_SUPPORTED;

  /**
   * Check if notifications are allowed
   */
  const isGranted = permission === NOTIFICATION_STATUS.GRANTED;

  /**
   * Request notification permission from the user
   */
  const requestPermission = useCallback(async () => {
    if (!isSupported) {
      console.warn("Browser notifications not supported");
      return false;
    }

    try {
      const result = await Notification.requestPermission();
      setPermission(result);
      return result === NOTIFICATION_STATUS.GRANTED;
    } catch (error) {
      console.error("Failed to request notification permission:", error);
      return false;
    }
  }, [isSupported]);

  /**
   * Show a notification
   * 
   * @param {string} title - Notification title
   * @param {Object} options - Notification options
   * @param {string} options.body - Notification body text
   * @param {string} options.tag - Unique tag to replace existing notification
   * @param {string} options.icon - Icon URL
   * @param {boolean} options.requireInteraction - Keep notification visible until clicked
   * @param {function} options.onClick - Click handler
   * @param {function} options.onClose - Close handler
   * @returns {Notification|null} The notification object or null
   */
  const notify = useCallback(
    (title, options = {}) => {
      if (!enabled || !isGranted) {
        console.log("Notification blocked:", { enabled, isGranted, title });
        return null;
      }

      try {
        const notification = new Notification(title, {
          body: options.body,
          icon: options.icon || icon,
          tag: options.tag,
          requireInteraction: options.requireInteraction || false,
          silent: options.silent || false,
        });

        // Store active notification
        const notificationId = options.tag || Date.now().toString();
        activeNotifications.current.set(notificationId, notification);

        // Handle click
        if (options.onClick) {
          notification.onclick = (e) => {
            window.focus();
            notification.close();
            options.onClick(e);
          };
        } else {
          notification.onclick = () => {
            window.focus();
            notification.close();
          };
        }

        // Handle close
        notification.onclose = () => {
          activeNotifications.current.delete(notificationId);
          options.onClose?.();
        };

        // Auto-close
        if (autoClose > 0 && !options.requireInteraction) {
          setTimeout(() => {
            notification.close();
          }, autoClose);
        }

        return notification;
      } catch (error) {
        console.error("Failed to show notification:", error);
        return null;
      }
    },
    [enabled, isGranted, icon, autoClose]
  );

  /**
   * Notify about camera status change
   */
  const notifyCameraStatus = useCallback(
    (cameraName, status, cameraId) => {
      const statusMessages = {
        online: `Camera "${cameraName}" is now online`,
        offline: `Camera "${cameraName}" went offline`,
        error: `Camera "${cameraName}" has an error`,
      };

      const statusIcons = {
        online: "🟢",
        offline: "🔴",
        error: "⚠️",
      };

      return notify(`${statusIcons[status] || ""} Camera ${status}`, {
        body: statusMessages[status] || `Camera "${cameraName}" status: ${status}`,
        tag: `camera-status-${cameraId}`,
        onClick: () => {
          window.location.href = `/cameras`;
        },
      });
    },
    [notify]
  );

  /**
   * Notify about recording started/stopped
   */
  const notifyRecording = useCallback(
    (cameraName, isRecording, cameraId) => {
      const icon = isRecording ? "🔴" : "⏹️";
      const action = isRecording ? "started" : "stopped";

      return notify(`${icon} Recording ${action}`, {
        body: `Recording ${action} on "${cameraName}"`,
        tag: `recording-${cameraId}`,
      });
    },
    [notify]
  );

  /**
   * Notify about system event
   */
  const notifySystem = useCallback(
    (title, message, type = "info") => {
      const icons = {
        info: "ℹ️",
        warning: "⚠️",
        error: "❌",
        success: "✅",
      };

      return notify(`${icons[type] || ""} ${title}`, {
        body: message,
        tag: `system-${Date.now()}`,
        requireInteraction: type === "error",
      });
    },
    [notify]
  );

  /**
   * Close all active notifications
   */
  const closeAll = useCallback(() => {
    activeNotifications.current.forEach((notification) => {
      notification.close();
    });
    activeNotifications.current.clear();
  }, []);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      closeAll();
    };
  }, [closeAll]);

  return {
    // State
    permission,
    isSupported,
    isGranted,
    
    // Actions
    requestPermission,
    notify,
    
    // Convenience methods
    notifyCameraStatus,
    notifyRecording,
    notifySystem,
    closeAll,
  };
}

export default useNotifications;
