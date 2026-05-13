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
