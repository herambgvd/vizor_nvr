// =============================================================================
// Monitoring API — Resources, Bandwidth, History
// =============================================================================

import apiClient from "./client";

// ---------- resources ----------

export const getResources = async () => {
  const response = await apiClient.get("/monitoring/resources");
  return response.data;
};

export const getSystemInfo = async () => {
  const response = await apiClient.get("/monitoring/system-info");
  return response.data;
};

export const getResourceHistory = async (params = {}) => {
  const response = await apiClient.get("/monitoring/resources/history", {
    params,
  });
  return response.data;
};

// ---------- bandwidth ----------

export const getBandwidthSummary = async () => {
  const response = await apiClient.get("/monitoring/bandwidth");
  return response.data;
};

export const getCameraBandwidth = async (cameraId) => {
  const response = await apiClient.get(`/monitoring/bandwidth/${cameraId}`);
  return response.data;
};

export const getCameraBandwidthHistory = async (cameraId, params = {}) => {
  const response = await apiClient.get(
    `/monitoring/bandwidth/${cameraId}/history`,
    { params },
  );
  return response.data;
};
