// =============================================================================
// Audit API — Logs, Actions, Cleanup
// =============================================================================

import apiClient from "./client";

// ---------- logs ----------

export const getAuditLogs = async (params = {}) => {
  const response = await apiClient.get("/audit/logs", { params });
  return response.data;
};

// ---------- actions ----------

export const getAuditActions = async () => {
  const response = await apiClient.get("/audit/actions");
  return response.data;
};

// ---------- cleanup ----------

export const cleanupAuditLogs = async (params = {}) => {
  const response = await apiClient.delete("/audit/cleanup", { params });
  return response.data;
};

// ---------- export ----------

/**
 * Trigger a browser download of the audit log export.
 * params: { format: 'csv'|'json', from, to, user_id, action }
 */
export const exportAuditLogs = async (params = {}) => {
  const response = await apiClient.get("/audit/logs/export", {
    params,
    responseType: "blob",
  });
  const fmt = params.format || "csv";
  const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  const filename = `audit-${ts}.${fmt}`;
  const url = URL.createObjectURL(response.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};
