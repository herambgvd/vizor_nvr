// =============================================================================
// Cameras API — CRUD, Recording, ONVIF, PTZ, Groups, WebRTC
// =============================================================================

import apiClient from "./client";

// ---------- camera CRUD ----------

export const getAllCameras = async () => {
  const response = await apiClient.get("/cameras");
  return response.data;
};

export const getCamera = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}`);
  return response.data;
};

export const createCamera = async (data) => {
  const response = await apiClient.post("/cameras", data);
  return response.data;
};

export const updateCamera = async (cameraId, data) => {
  const response = await apiClient.put(`/cameras/${cameraId}`, data);
  return response.data;
};

export const deleteCamera = async (cameraId) => {
  const response = await apiClient.delete(`/cameras/${cameraId}`, {
    timeout: 30000,
  });
  return response.data;
};

// ---------- recording control ----------

export const startRecording = async (cameraId) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/start-recording`,
    {},
    { timeout: 15000 },
  );
  return response.data;
};

export const stopRecording = async (cameraId) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/stop-recording`,
    {},
    { timeout: 15000 },
  );
  return response.data;
};

// ---------- connection / snapshot ----------

export const testConnection = async (cameraId) => {
  const response = await apiClient.post(`/cameras/${cameraId}/test-connection`);
  return response.data;
};

export const captureSnapshot = async (cameraId) => {
  const response = await apiClient.post(`/cameras/${cameraId}/snapshot`);
  return response.data;
};

// ---------- stream URLs ----------

export const getStreamUrls = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/stream-urls`);
  return response.data;
};

// ---------- WebRTC signaling through backend ----------

export const webrtcSignal = async (cameraId, offer) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/webrtc-signal`,
    offer,
  );
  return response.data;
};

// ---------- ONVIF discovery ----------

export const onvifDiscover = async (params = {}) => {
  const response = await apiClient.post("/cameras/onvif/discover", params, {
    timeout: 30000,
  });
  return response.data;
};

export const onvifProbe = async (data) => {
  const response = await apiClient.post("/cameras/onvif/probe", data, {
    timeout: 15000,
  });
  return response.data;
};

// ---------- PTZ control ----------

export const ptzMove = async (cameraId, data) => {
  const response = await apiClient.post(`/cameras/${cameraId}/ptz/move`, data);
  return response.data;
};

export const ptzStop = async (cameraId) => {
  const response = await apiClient.post(`/cameras/${cameraId}/ptz/stop`);
  return response.data;
};

export const ptzGetPresets = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/ptz/presets`);
  return response.data;
};

export const ptzGotoPreset = async (cameraId, data) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/ptz/goto-preset`,
    data,
  );
  return response.data;
};

export const ptzSavePreset = async (cameraId, data) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/ptz/presets`,
    data,
  );
  return response.data;
};

export const ptzDeletePreset = async (cameraId, presetToken) => {
  const response = await apiClient.delete(
    `/cameras/${cameraId}/ptz/presets/${presetToken}`,
  );
  return response.data;
};

// ---------- camera groups ----------

export const getCameraGroups = async () => {
  const response = await apiClient.get("/cameras/groups");
  return response.data;
};

export const createCameraGroup = async (data) => {
  const response = await apiClient.post("/cameras/groups", data);
  return response.data;
};

export const updateCameraGroup = async (groupId, data) => {
  const response = await apiClient.put(`/cameras/groups/${groupId}`, data);
  return response.data;
};

export const deleteCameraGroup = async (groupId) => {
  const response = await apiClient.delete(`/cameras/groups/${groupId}`);
  return response.data;
};

export const addUserToGroup = async (groupId, userId) => {
  const response = await apiClient.post(
    `/cameras/groups/${groupId}/users/${userId}`,
  );
  return response.data;
};

export const removeUserFromGroup = async (groupId, userId) => {
  const response = await apiClient.delete(
    `/cameras/groups/${groupId}/users/${userId}`,
  );
  return response.data;
};

// ---------- ONVIF advanced ----------

export const getONVIFCapabilities = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/onvif/capabilities`, { timeout: 20000 });
  return response.data;
};

export const getONVIFDeviceInfo = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/onvif/device-info`, { timeout: 15000 });
  return response.data;
};

export const getONVIFTime = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/onvif/time`, { timeout: 10000 });
  return response.data;
};

export const syncONVIFTime = async (cameraId) => {
  const response = await apiClient.post(`/cameras/${cameraId}/onvif/sync-time`, {}, { timeout: 15000 });
  return response.data;
};

export const rebootCamera = async (cameraId) => {
  const response = await apiClient.post(`/cameras/${cameraId}/onvif/reboot`, {}, { timeout: 30000 });
  return response.data;
};

export const factoryDefaultCamera = async (cameraId, hard = false) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/onvif/factory-default`,
    { hard },
    { timeout: 30000 },
  );
  return response.data;
};

export const getImagingSettings = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/onvif/imaging`, { timeout: 15000 });
  return response.data;
};

export const setImagingSettings = async (cameraId, data) => {
  const response = await apiClient.put(`/cameras/${cameraId}/onvif/imaging`, data, { timeout: 15000 });
  return response.data;
};

export const moveFocus = async (cameraId, data) => {
  const response = await apiClient.post(`/cameras/${cameraId}/onvif/imaging/focus`, data, { timeout: 10000 });
  return response.data;
};

export const getRelayOutputs = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/onvif/relay-outputs`, { timeout: 15000 });
  return response.data;
};

export const triggerRelayOutput = async (cameraId, token, state) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/onvif/relay-outputs/${token}/trigger`,
    { state },
    { timeout: 10000 },
  );
  return response.data;
};

export const getDigitalInputs = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/onvif/digital-inputs`, { timeout: 15000 });
  return response.data;
};

export const getCameraSnapshots = async (cameraId, params = {}) => {
  const response = await apiClient.get(`/cameras/${cameraId}/snapshots`, { params });
  return response.data;
};

export const getLatestSnapshot = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/snapshots/latest`);
  return response.data;
};
