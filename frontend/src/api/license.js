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

// Build a portable license-request blob for one scenario. The operator copies it
// and sends it to the vendor, who signs a fingerprint-bound .lic for that plugin.
export const requestScenarioLicense = async (scenario) => {
  const r = await apiClient.post("/license/request", { scenario });
  return r.data; // { request, fingerprint, scenario, name, license_feature }
};
