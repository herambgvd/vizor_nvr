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

export const bulkDeleteCameras = async (cameraIds) => {
  const response = await apiClient.post(
    `/cameras/bulk-delete`,
    { camera_ids: cameraIds },
    { timeout: 60000 },
  );
  return response.data;
};

export const bulkStartRecording = async (cameraIds) => {
  const response = await apiClient.post(
    `/cameras/bulk/start`,
    { camera_ids: cameraIds },
    { timeout: 60000 },
  );
  return response.data;
};

export const bulkStopRecording = async (cameraIds) => {
  const response = await apiClient.post(
    `/cameras/bulk/stop`,
    { camera_ids: cameraIds },
    { timeout: 60000 },
  );
  return response.data;
};

export const bulkTestConnection = async (cameraIds) => {
  const response = await apiClient.post(
    `/cameras/bulk/test`,
    { camera_ids: cameraIds },
    { timeout: 60000 },
  );
  return response.data;
};

export const bulkSetEnabled = async (cameraIds, enabled) => {
  const response = await apiClient.post(
    `/cameras/bulk/enable`,
    { camera_ids: cameraIds, enabled },
    { timeout: 60000 },
  );
  return response.data;
};

export const reorderCameras = async (cameraIds) => {
  const response = await apiClient.post(
    `/cameras/reorder`,
    { camera_ids: cameraIds },
    { timeout: 30000 },
  );
  return response.data;
};

export const getLatestHealth = async () => {
  const response = await apiClient.get(`/cameras/health/latest`);
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
  // Backend reads `subnet` and `timeout` from query string. Empty body POST.
  const response = await apiClient.post("/cameras/onvif/discover", null, {
    params,
    timeout: 60000,
  });
  return response.data;
};

export const onvifProbe = async (data) => {
  const response = await apiClient.post("/cameras/onvif/probe", data, {
    timeout: 15000,
  });
  return response.data;
};

export const onvifChannels = async (data) => {
  const response = await apiClient.post("/cameras/onvif/channels", data, {
    timeout: 30000,
  });
  return response.data;
};

export const onvifBulkAdd = async (cameras) => {
  const response = await apiClient.post(
    "/cameras/onvif/bulk-add",
    { cameras },
    { timeout: 60000 },
  );
  return response.data;
};

export const getOnvifEdgeRecordings = async (cameraId, params = {}) => {
  const response = await apiClient.get(`/cameras/${cameraId}/onvif/recordings`, {
    params,
    timeout: 30000,
  });
  return response.data;
};

export const getOnvifReplayUri = async (cameraId, recordingToken) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/onvif/replay-uri`,
    { recording_token: recordingToken },
    { timeout: 15000 },
  );
  return response.data;
};

export const getOnvifMetadataStream = async (cameraId) => {
  const response = await apiClient.get(
    `/cameras/${cameraId}/onvif/metadata-stream`,
    { timeout: 20000 },
  );
  return response.data;
};

// Returns a blob URL to a JPEG snapshot from the camera. Caller is
// responsible for revokeObjectURL when the URL is no longer needed.
//
// Implementation note:
//   Uses native `fetch` instead of axios because some browser extensions
//   (e.g. screen-recorder / monitoring helpers) wrap XMLHttpRequest and
//   try to read `responseText` on every error. When responseType is
//   "blob" that throws InvalidStateError on 404. `fetch` uses a
//   different transport that those extensions don't monkey-patch.
import { BACKEND_URL, getAccessToken } from "./client";  // noqa
export const onvifSnapshotBlobUrl = async (data) => {
  const token = getAccessToken();
  let response;
  try {
    response = await fetch(`${BACKEND_URL}/api/cameras/onvif/snapshot`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(data),
      // 15 s — same as axios default we had
      signal: AbortSignal.timeout
        ? AbortSignal.timeout(15000)
        : undefined,
    });
  } catch (_e) {
    return null;
  }
  if (!response.ok) return null;
  const blob = await response.blob();
  if (!blob || blob.size === 0) return null;
  return URL.createObjectURL(blob);
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
  const response = await apiClient.get(`/cameras/${cameraId}/onvif-capabilities`, { timeout: 20000 });
  return response.data;
};

export const getONVIFDeviceInfo = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/system-info`, { timeout: 15000 });
  return response.data;
};

export const getONVIFTime = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/system-time`, { timeout: 10000 });
  return response.data;
};

export const syncONVIFTime = async (cameraId) => {
  const response = await apiClient.post(`/cameras/${cameraId}/system-time/sync`, {}, { timeout: 15000 });
  return response.data;
};

export const rebootCamera = async (cameraId) => {
  const response = await apiClient.post(`/cameras/${cameraId}/reboot`, {}, { timeout: 30000 });
  return response.data;
};

export const factoryDefaultCamera = async (cameraId, hard = false) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/factory-default`,
    { hard },
    { timeout: 30000 },
  );
  return response.data;
};

export const getImagingSettings = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/imaging`, { timeout: 15000 });
  return response.data;
};

export const setImagingSettings = async (cameraId, data) => {
  const response = await apiClient.put(`/cameras/${cameraId}/imaging`, data, { timeout: 15000 });
  return response.data;
};

export const moveFocus = async (cameraId, data) => {
  const response = await apiClient.post(`/cameras/${cameraId}/imaging/focus`, data, { timeout: 10000 });
  return response.data;
};

export const getRelayOutputs = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/io/outputs`, { timeout: 15000 });
  return response.data;
};

export const triggerRelayOutput = async (cameraId, token, state) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/io/outputs/${token}/trigger`,
    { state },
    { timeout: 10000 },
  );
  return response.data;
};

export const getDigitalInputs = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/io/inputs`, { timeout: 15000 });
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

// ---------- PTZ Tour (B1) ----------

export const getPtzTour = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/ptz/tour`);
  return response.data;
};

export const putPtzTour = async (cameraId, config) => {
  const response = await apiClient.put(`/cameras/${cameraId}/ptz/tour`, config);
  return response.data;
};

export const startPtzTour = async (cameraId) => {
  const response = await apiClient.post(`/cameras/${cameraId}/ptz/tour/start`);
  return response.data;
};

export const stopPtzTour = async (cameraId) => {
  const response = await apiClient.post(`/cameras/${cameraId}/ptz/tour/stop`);
  return response.data;
};

// ---------- Bulk camera operations (C3) ----------

export const bulkCameraAction = async (action, cameraIds, params = {}) => {
  const response = await apiClient.post(
    `/cameras/bulk`,
    { action, camera_ids: cameraIds, params },
    { timeout: 60000 },
  );
  return response.data;
};

// ---------- Firmware (B2) ----------

export const getFirmwareInfo = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/firmware/info`, { timeout: 15000 });
  return response.data;
};

export const uploadFirmware = async (cameraId, file) => {
  const form = new FormData();
  form.append("firmware", file);
  const response = await apiClient.post(`/cameras/${cameraId}/firmware/upload`, form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return response.data;
};

// ---------- Credentials (B3) ----------

export const rotateCredentials = async (cameraId, newPassword) => {
  const response = await apiClient.post(`/cameras/${cameraId}/credentials/rotate`, {
    new_password: newPassword,
  });
  return response.data;
};

// ---------- Two-way Audio Backchannel (B4) ----------

export const startBackchannel = async (cameraId) => {
  const response = await apiClient.post(`/cameras/${cameraId}/audio/backchannel/start`);
  return response.data;
};

export const stopBackchannel = async (cameraId) => {
  const response = await apiClient.post(`/cameras/${cameraId}/audio/backchannel/stop`);
  return response.data;
};

/**
 * Send a WebRTC SDP offer for the two-way audio publish (push) path.
 * The browser creates a PeerConnection with mic audio, generates an offer,
 * and passes the raw SDP string here.  Returns { sdp: <answer> }.
 */
export const postBackchannelWebrtcSignal = async (cameraId, sdp) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/audio/backchannel/webrtc-signal`,
    { sdp },
    { timeout: 15000 },
  );
  return response.data;
};

// ---------- Scheduled Snapshots (D1) ----------

export const getScheduledSnapshotConfig = async (cameraId) => {
  const response = await apiClient.get(`/cameras/${cameraId}/snapshots/scheduled`);
  return response.data;
};

export const updateScheduledSnapshotConfig = async (cameraId, config) => {
  const response = await apiClient.put(`/cameras/${cameraId}/snapshots/scheduled`, config);
  return response.data;
};

export const listSnapshots = async (cameraId, params = {}) => {
  const response = await apiClient.get(`/cameras/${cameraId}/snapshots/gallery`, { params });
  return response.data;
};

// ---------- Snapshot Annotation (K3) ----------

export const annotateSnapshot = async (cameraId, sourceUrl, operations) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/snapshots/annotate`,
    { source_url: sourceUrl, operations },
    { responseType: "blob", timeout: 30000 },
  );
  return response.data;
};

export const annotateAndSaveSnapshot = async (cameraId, sourceUrl, operations) => {
  const response = await apiClient.post(
    `/cameras/${cameraId}/snapshots/annotate/save`,
    { source_url: sourceUrl, operations },
    { timeout: 30000 },
  );
  return response.data;
};

// Evidence export with optional snapshot attachments
export const exportEvidence = (recordingId, attachSnapshots = []) =>
  apiClient.post(`/recordings/${recordingId}/export-evidence`, {
    attach_snapshots: attachSnapshots,
  });
