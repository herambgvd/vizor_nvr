// =============================================================================
// Settings API — System Configuration
// =============================================================================

import apiClient from "./client";

// ---------- general settings ----------

export const getSettings = async () => {
  const response = await apiClient.get("/settings");
  return response.data;
};

export const updateSettings = async (data) => {
  const response = await apiClient.put("/settings", data);
  return response.data;
};

export const getSetting = async (key) => {
  const response = await apiClient.get(`/settings/${key}`);
  return response.data;
};

export const updateSetting = async (key, value) => {
  const response = await apiClient.put(`/settings/${key}`, value);
  return response.data;
};

// ---------- retention ----------

export const getRetentionConfig = async () => {
  const response = await apiClient.get("/settings/config/retention");
  return response.data;
};

export const updateRetentionConfig = async (data) => {
  const response = await apiClient.put("/settings/config/retention", data);
  return response.data;
};

// ---------- recording config ----------

export const getRecordingConfig = async () => {
  const response = await apiClient.get("/settings/config/recording");
  return response.data;
};

export const updateRecordingConfig = async (data) => {
  const response = await apiClient.put("/settings/config/recording", data);
  return response.data;
};

// ---------- health ----------

export const getHealth = async () => {
  const response = await apiClient.get("/health");
  return response.data;
};
