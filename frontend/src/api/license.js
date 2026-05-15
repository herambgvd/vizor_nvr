// =============================================================================
// License API client
// =============================================================================

import apiClient from "./client";

export const getLicense = async () => {
  const r = await apiClient.get("/license");
  return r.data;
};

export const getFingerprint = async () => {
  const r = await apiClient.get("/license/fingerprint");
  return r.data;
};

export const activateLicense = async (file) => {
  const form = new FormData();
  form.append("file", file);
  const r = await apiClient.post("/license/activate", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return r.data;
};

export const clearLicense = async () => {
  await apiClient.delete("/license");
};
