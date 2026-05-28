// =============================================================================
// Storage API — Pools, Tier Rules, Summary, Cloud, Disk Explorer
// =============================================================================

import apiClient from "./client";

// ---------- pools ----------

export const getStoragePools = async () => {
  const response = await apiClient.get("/storage/pools");
  return response.data;
};

export const createStoragePool = async (data) => {
  const response = await apiClient.post("/storage/pools", data);
  return response.data;
};

export const updateStoragePool = async (poolId, data) => {
  const response = await apiClient.put(`/storage/pools/${poolId}`, data);
  return response.data;
};

export const deleteStoragePool = async (poolId) => {
  const response = await apiClient.delete(`/storage/pools/${poolId}`);
  return response.data;
};

export const testNasConnection = async (data) => {
  const response = await apiClient.post("/storage/nas/test-connection", data);
  return response.data;
};

export const mountNasPool = async (poolId) => {
  const response = await apiClient.post(`/storage/pools/${poolId}/mount`);
  return response.data;
};

export const unmountNasPool = async (poolId) => {
  const response = await apiClient.post(`/storage/pools/${poolId}/unmount`);
  return response.data;
};

export const getNasPoolHealth = async (poolId) => {
  const response = await apiClient.get(`/storage/pools/${poolId}/nas-health`);
  return response.data;
};

// ---------- rules ----------

export const getStorageRules = async () => {
  const response = await apiClient.get("/storage/rules");
  return response.data;
};

export const createStorageRule = async (data) => {
  const response = await apiClient.post("/storage/rules", data);
  return response.data;
};

export const deleteStorageRule = async (ruleId) => {
  const response = await apiClient.delete(`/storage/rules/${ruleId}`);
  return response.data;
};

// ---------- summary ----------

export const getStorageSummary = async () => {
  const response = await apiClient.get("/storage/summary");
  return response.data;
};

// ---------- system disks ----------

export const getSystemDisks = async () => {
  const response = await apiClient.get("/storage/disks");
  return response.data;
};

// ---------- cloud storage ----------

export const getCloudConfigs = async () => {
  const response = await apiClient.get("/storage/cloud");
  return response.data;
};

export const createCloudConfig = async (data) => {
  const response = await apiClient.post("/storage/cloud", data);
  return response.data;
};

export const updateCloudConfig = async (configId, data) => {
  const response = await apiClient.put(`/storage/cloud/${configId}`, data);
  return response.data;
};

export const deleteCloudConfig = async (configId) => {
  const response = await apiClient.delete(`/storage/cloud/${configId}`);
  return response.data;
};

export const testCloudConfig = async (configId) => {
  const response = await apiClient.post(`/storage/cloud/${configId}/test`);
  return response.data;
};

export const uploadToCloud = async (data) => {
  const response = await apiClient.post("/storage/cloud/upload", data);
  return response.data;
};

// ---------- backup schedules ----------

export const getBackupSchedules = async () => {
  const response = await apiClient.get("/storage/backups");
  return response.data;
};

export const createBackupSchedule = async (data) => {
  const response = await apiClient.post("/storage/backups", data);
  return response.data;
};

export const updateBackupSchedule = async (scheduleId, data) => {
  const response = await apiClient.put(`/storage/backups/${scheduleId}`, data);
  return response.data;
};

export const deleteBackupSchedule = async (scheduleId) => {
  const response = await apiClient.delete(`/storage/backups/${scheduleId}`);
  return response.data;
};

export const runBackupNow = async (scheduleId) => {
  const response = await apiClient.post(`/storage/backups/${scheduleId}/run`);
  return response.data;
};
