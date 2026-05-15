// =============================================================================
// Events API — events CRUD, acknowledge, stats, linkage rules
// =============================================================================

import apiClient from "./client";

// ---------- Events ----------

export const getEvents = async (params = {}) => {
  const response = await apiClient.get("/events", { params });
  return response.data;
};

export const getEvent = async (eventId) => {
  const response = await apiClient.get(`/events/${eventId}`);
  return response.data;
};

export const getEventStats = async () => {
  const response = await apiClient.get("/events/stats");
  return response.data;
};

export const getUnacknowledgedCount = async (cameraId) => {
  const params = cameraId ? { camera_id: cameraId } : {};
  const response = await apiClient.get("/events/unacknowledged-count", { params });
  return response.data;
};

export const acknowledgeEvent = async (eventId, note) => {
  const response = await apiClient.post(`/events/${eventId}/acknowledge`, { note });
  return response.data;
};

export const acknowledgeAllEvents = async (params = {}) => {
  const response = await apiClient.post("/events/acknowledge-all", null, { params });
  return response.data;
};

export const markFalseAlarm = async (eventId, note) => {
  const response = await apiClient.post(`/events/${eventId}/false-alarm`, { note });
  return response.data;
};

export const deleteEvent = async (eventId) => {
  const response = await apiClient.delete(`/events/${eventId}`);
  return response.data;
};

export const bulkDeleteEvents = async (body = {}) => {
  // body: { event_ids?: string[], camera_id?, event_type?, severity?,
  //         acknowledged?, before? } — pass ids OR filters
  const response = await apiClient.delete("/events/bulk", { data: body });
  return response.data;
};

export const exportEventsCSV = async (params = {}) => {
  const response = await apiClient.get("/events/export/csv", {
    params,
    responseType: "blob",
  });
  return response.data;
};

// ---------- Linkage Rules ----------

export const getLinkageRules = async () => {
  const response = await apiClient.get("/events/rules/list");
  return response.data;
};

export const getLinkageRule = async (ruleId) => {
  const response = await apiClient.get(`/events/rules/${ruleId}`);
  return response.data;
};

export const createLinkageRule = async (data) => {
  const response = await apiClient.post("/events/rules", data);
  return response.data;
};

export const updateLinkageRule = async (ruleId, data) => {
  const response = await apiClient.patch(`/events/rules/${ruleId}`, data);
  return response.data;
};

export const deleteLinkageRule = async (ruleId) => {
  const response = await apiClient.delete(`/events/rules/${ruleId}`);
  return response.data;
};

// ---------- Motion / Privacy (camera endpoints) ----------

export const getMotionConfig = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/motion-config`);
  return response.data;
};

export const updateMotionConfig = async (cameraId, config) => {
  const response = await apiClient.put(`/cameras/${cameraId}/motion-config`, { config });
  return response.data;
};

export const getMotionStatus = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/motion-status`);
  return response.data;
};

export const getPrivacyMasks = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/privacy-masks`);
  return response.data;
};

export const updatePrivacyMasks = async (cameraId, masks) => {
  const response = await apiClient.put(`/cameras/${cameraId}/privacy-masks`, { masks });
  return response.data;
};
