// =============================================================================
// Recordings API — Queries, Timeline, Playback, Export
// =============================================================================

import apiClient, { BACKEND_URL, getAccessToken } from "./client";

// ---------- recording queries ----------

export const getRecordings = async (params = {}) => {
  const response = await apiClient.get("/recordings", { params });
  return response.data;
};

export const getRecording = async (recordingId) => {
  const response = await apiClient.get(`/recordings/${recordingId}`);
  return response.data;
};

export const deleteRecording = async (recordingId) => {
  const response = await apiClient.delete(`/recordings/${recordingId}`);
  return response.data;
};

export const bulkDeleteRecordings = async (recordingIds) => {
  const response = await apiClient.post("/recordings/bulk-delete", {
    recording_ids: recordingIds,
  });
  return response.data;
};

// ---------- timeline & dates ----------

export const getTimeline = async (cameraId, date) => {
  // Backend expects 'day' param in YYYY-MM-DD format (local date, not UTC)
  let dayParam = date;
  if (date) {
    const d = new Date(date);
    if (!isNaN(d.getTime())) {
      // Use local date components to avoid timezone issues
      const year = d.getFullYear();
      const month = String(d.getMonth() + 1).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      dayParam = `${year}-${month}-${day}`;
    }
  }
  const response = await apiClient.get(`/recordings/timeline/${cameraId}`, {
    params: { day: dayParam },
  });
  return response.data;
};

export const getRecordingDates = async (cameraId) => {
  const response = await apiClient.get(`/recordings/dates/${cameraId}`);
  return response.data;
};

export const getRecordingStats = async (cameraId) => {
  const response = await apiClient.get(`/recordings/stats/${cameraId}`);
  return response.data;
};

// ---------- playback ----------

export const getPlaybackInfo = async (cameraId, params = {}) => {
  const response = await apiClient.get(`/recordings/playback/${cameraId}`, {
    params,
  });
  return response.data;
};

export const getContinuousPlayback = async (cameraId, params = {}) => {
  const response = await apiClient.get(
    `/recordings/playback/${cameraId}/continuous`,
    { params },
  );
  return response.data;
};

// ---------- thumbnails ----------

export const getThumbnailUrl = (cameraId, timestamp) => {
  const token = getAccessToken();
  const ts = encodeURIComponent(timestamp);
  return `${BACKEND_URL}/api/recordings/thumbnail/${cameraId}?timestamp=${ts}&token=${token}`;
};

// ---------- export ----------

export const exportClip = async (data) => {
  const response = await apiClient.post("/recordings/export", data);
  return response.data;
};

export const getExportStatus = async (exportId) => {
  const response = await apiClient.get(`/recordings/export/${exportId}`);
  return response.data;
};

export const getExportDownloadUrl = (exportId) => {
  const token = getAccessToken();
  return `${BACKEND_URL}/api/recordings/export/${exportId}/download?token=${token}`;
};

export const exportMultiSegment = async (data) => {
  const response = await apiClient.post(
    "/recordings/export/multi-segment",
    data,
  );
  return response.data;
};

// ---------- download ----------

export const getRecordingDownloadUrl = (recordingId) => {
  const token = getAccessToken();
  return `${BACKEND_URL}/api/recordings/${recordingId}/download?token=${token}`;
};

/** Alias used by TimelinePlayer for <video> src */
export const getVideoUrl = getRecordingDownloadUrl;

// ---------- lock / protect ----------

export const lockRecording = async (recordingId) => {
  const response = await apiClient.put(`/recordings/${recordingId}/lock`);
  return response.data;
};

export const unlockRecording = async (recordingId) => {
  const response = await apiClient.put(`/recordings/${recordingId}/unlock`);
  return response.data;
};
