// =============================================================================
// usePermissions — Permission-based access helpers
// =============================================================================

import { useMemo } from "react";
import { useAuth } from "../context/AuthContext";

/**
 * Returns permission booleans based on the current user's role & permissions.
 *
 * The backend returns a `permissions` array on the user object, e.g.:
 *   ["view_live", "view_playback", "control_recording", "manage_camera", ...]
 *
 * Roles hierarchy (for fallback):
 *   admin    → full access
 *   operator → can control cameras & recordings, read everything
 *   viewer   → read-only (dashboard, playback)
 */
export const usePermissions = () => {
  const { user, isAdmin } = useAuth();

  return useMemo(() => {
    const role = user?.role_name || user?.role || "viewer";
    const perms = user?.permissions || [];
    const has = (p) => isAdmin || perms.includes(p);

    return {
      isAdmin,
      role,
      permissions: perms,
      has,

      // Can manage cameras, storage, settings, users
      canManage: isAdmin || has("manage_camera"),
      // Can start/stop recording, PTZ, export
      canOperate: isAdmin || has("control_recording") || role === "operator",
      // Can view dashboards, playback, monitoring
      canView: true,
      // Specific permission checks
      canPTZ: isAdmin || has("control_ptz"),
      canExport: isAdmin || has("export_clips"),
      canDeleteRecordings: isAdmin || has("delete_recordings"),
      canManageUsers: isAdmin || has("manage_users"),
      canManageSettings: isAdmin || has("manage_settings"),
      canManageStorage: isAdmin || has("manage_storage"),
      canViewAudit: isAdmin || has("view_audit_log"),
    };
  }, [user, isAdmin]);
};
