// =============================================================================
// System / Licensing / TLS / NTP / DDNS / Updates API client
// =============================================================================
// Frontend pairing for the new endpoints introduced in Phase 5-7.
// =============================================================================

import client from "./client";

// ── System info ────────────────────────────────────────────────────────────
export const getSystemInfo = () => client.get("/system/info").then(r => r.data);

// ── License (Phase 7.1 / 7.2) ──────────────────────────────────────────────
export const getLicenseStatus = () => client.get("/system/license/status").then(r => r.data);
export const uploadLicense = (file) => {
  const fd = new FormData();
  fd.append("file", file);
  return client.post("/system/license/upload", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  }).then(r => r.data);
};

// ── TLS (Phase 5.1) ────────────────────────────────────────────────────────
export const getTLSStatus = () => client.get("/settings/tls/status").then(r => r.data);
export const generateSelfSignedCert = (common_name = "gvd-nvr.local", days_valid = 365) =>
  client.post("/settings/tls/generate-self-signed", { common_name, days_valid })
    .then(r => r.data);
export const uploadTLS = (cert_pem, key_pem) =>
  client.post("/settings/tls/upload", { cert_pem, key_pem }).then(r => r.data);

// ── NTP (Phase 7.6) ────────────────────────────────────────────────────────
export const getNTPStatus = () => client.get("/system/ntp/status").then(r => r.data);
export const setNTPServer = (server) =>
  client.post("/system/ntp/sync", { server }).then(r => r.data);

// ── DDNS (Phase 7.8) ───────────────────────────────────────────────────────
export const getDDNSStatus = () => client.get("/system/ddns/status").then(r => r.data);
export const setDDNSConfig = (cfg) =>
  client.put("/system/ddns/config", cfg).then(r => r.data);

// ── Updates (Phase 7.5) ────────────────────────────────────────────────────
export const checkUpdates = () => client.get("/system/updates/check").then(r => r.data);
export const applyUpdates = () => client.post("/system/updates/apply").then(r => r.data);

// ── Disk health (Phase 4.2) ────────────────────────────────────────────────
export const getDiskHealth = () => client.get("/monitoring/disks").then(r => r.data);

// ── Storage analytics (Phase 4.8) ──────────────────────────────────────────
export const getStorageAnalytics = () => client.get("/storage/analytics").then(r => r.data);
export const testPoolConnection = (path) =>
  client.post("/storage/pools/test-connection", { path }).then(r => r.data);
export const getPoolHealth = (poolId) =>
  client.get(`/storage/pools/${poolId}/health`).then(r => r.data);

// ── 2FA (Phase 5.3) ────────────────────────────────────────────────────────
export const enable2FA = () => client.post("/auth/2fa/enable").then(r => r.data);
export const verify2FA = (token) => client.post("/auth/2fa/verify", { token }).then(r => r.data);
export const disable2FA = (token) => client.post("/auth/2fa/disable", { token }).then(r => r.data);

// ── Sessions (Phase 5.5) ───────────────────────────────────────────────────
export const listMySessions = () => client.get("/auth/sessions").then(r => r.data);
export const listAllSessions = () => client.get("/auth/sessions/all").then(r => r.data);
export const revokeMySession = (sessionId) =>
  client.delete(`/auth/sessions/${sessionId}`).then(r => r.data);
export const revokeOtherSessions = () =>
  client.post("/auth/sessions/revoke-others").then(r => r.data);

// ── Roles & ACL (Phase 6.3 / 6.6) ──────────────────────────────────────────
export const listPermissions = () => client.get("/auth/permissions/available").then(r => r.data);
export const createRole = (role) => client.post("/auth/roles", role).then(r => r.data);
export const updateRole = (id, role) => client.put(`/auth/roles/${id}`, role).then(r => r.data);
export const deleteRole = (id) => client.delete(`/auth/roles/${id}`).then(r => r.data);
export const getUserCameras = (userId) =>
  client.get(`/auth/users/${userId}/cameras`).then(r => r.data);
export const setUserCameras = (userId, camera_ids) =>
  client.put(`/auth/users/${userId}/cameras`, { camera_ids }).then(r => r.data);
export const setUserAccessSchedule = (userId, schedule) =>
  client.put(`/auth/users/${userId}/access-schedule`, { schedule }).then(r => r.data);

// ── Recording integrity + evidence (Phase 4.5 / 4.6) ───────────────────────
export const verifyRecording = (id) =>
  client.post(`/recordings/${id}/verify`).then(r => r.data);
export const exportEvidence = (id) =>
  client.post(`/recordings/${id}/export-evidence`).then(r => r.data);
export const issueDownloadToken = (id) =>
  client.post(`/recordings/${id}/download-token`).then(r => r.data);

// ── Audit report (Phase 5.7 / 5.8) ─────────────────────────────────────────
export const getAuditReport = (from, to, format = "csv") =>
  client.get("/audit/report", { params: { from, to, format }, responseType: format === "csv" ? "blob" : "json" })
    .then(r => r.data);
export const purgeRecordings = (body) =>
  client.post("/recordings/purge", body).then(r => r.data);
