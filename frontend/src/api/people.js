// =============================================================================
// People Counting API — zones CRUD + counts aggregation + live snapshot
// =============================================================================

import apiClient from "./client";

export const listZones = async (cameraId) => {
  const res = await apiClient.get(`/ai/people/cameras/${cameraId}/zones`);
  return res.data;
};

export const createZone = async (cameraId, payload) => {
  const res = await apiClient.post(
    `/ai/people/cameras/${cameraId}/zones`,
    payload,
  );
  return res.data;
};

export const updateZone = async (zoneId, payload) => {
  const res = await apiClient.patch(`/ai/people/zones/${zoneId}`, payload);
  return res.data;
};

export const deleteZone = async (zoneId) => {
  const res = await apiClient.delete(`/ai/people/zones/${zoneId}`);
  return res.data;
};

export const getCounts = async (params = {}) => {
  const res = await apiClient.get("/ai/people/counts", { params });
  return res.data;
};

export const getLiveSnapshot = async () => {
  const res = await apiClient.get("/ai/people/live");
  return res.data;
};

export const triggerAIReload = async () => {
  const res = await apiClient.post("/ai/control/reload");
  return res.data;
};

export const getActiveCamerasBundle = async (scenario = "people_counting") => {
  const res = await apiClient.get("/ai/cameras/active", { params: { scenario } });
  return res.data;
};
