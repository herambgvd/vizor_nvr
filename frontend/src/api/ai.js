// =============================================================================
// AI scenarios API client
// =============================================================================
// Covers the catalog (scenarios), per-camera enablement (CameraAIConfig) and
// the FRS sub-domain (groups, persons, photos, recognition events, attendance,
// reports). Mirrors the backend routers mounted under /api/ai.
// =============================================================================

import apiClient, { BACKEND_URL, getAccessToken } from "./client";

// ---------- scenarios (catalog) ----------

export const getScenarios = async () => {
  const r = await apiClient.get("/ai/scenarios");
  return r.data;
};

export const getActiveScenarios = async () => {
  const r = await apiClient.get("/ai/scenarios/active");
  return r.data;
};

export const getScenario = async (id) => {
  const r = await apiClient.get(`/ai/scenarios/${id}`);
  return r.data;
};

// Resolve a scenario by its slug ("frs", "ppe"). The catalog is tiny, so we
// fetch the full list and filter client-side rather than add a slug endpoint.
export const getScenarioBySlug = async (slug) => {
  const list = await getScenarios();
  return (list || []).find((s) => s.slug === slug) || null;
};

export const toggleScenario = async (id, enabled) => {
  const r = await apiClient.put(`/ai/scenarios/${id}/enable`, { enabled });
  return r.data;
};

// ---------- per-camera config (CameraAIConfig) ----------

export const listScenarioCameras = async (scenarioId) => {
  const r = await apiClient.get(`/ai/scenarios/${scenarioId}/cameras`);
  return r.data;
};

export const assignCamera = async (scenarioId, { camera_id, enabled = true, config = null }) => {
  const r = await apiClient.post(`/ai/scenarios/${scenarioId}/cameras`, {
    camera_id,
    enabled,
    config,
  });
  return r.data;
};

export const updateCameraConfig = async (id, patch) => {
  const r = await apiClient.put(`/ai/camera-configs/${id}`, patch);
  return r.data;
};

export const unassignCamera = async (id) => {
  const r = await apiClient.delete(`/ai/camera-configs/${id}`);
  return r.data;
};

// ---------- FRS — groups ----------

export const listGroups = async () => {
  const r = await apiClient.get("/ai/frs/groups");
  return r.data;
};

export const createGroup = async (payload) => {
  const r = await apiClient.post("/ai/frs/groups", payload);
  return r.data;
};

export const updateGroup = async (id, patch) => {
  const r = await apiClient.put(`/ai/frs/groups/${id}`, patch);
  return r.data;
};

export const deleteGroup = async (id) => {
  const r = await apiClient.delete(`/ai/frs/groups/${id}`);
  return r.data;
};

// ---------- FRS — persons ----------

export const listPersons = async (params = {}) => {
  const r = await apiClient.get("/ai/frs/persons", { params });
  return r.data;
};

export const createPerson = async (payload) => {
  const r = await apiClient.post("/ai/frs/persons", payload);
  return r.data;
};

export const getPerson = async (id) => {
  const r = await apiClient.get(`/ai/frs/persons/${id}`);
  return r.data;
};

export const updatePerson = async (id, patch) => {
  const r = await apiClient.put(`/ai/frs/persons/${id}`, patch);
  return r.data;
};

export const deletePerson = async (id) => {
  const r = await apiClient.delete(`/ai/frs/persons/${id}`);
  return r.data;
};

// ---------- FRS — photos ----------

export const uploadPhoto = async (personId, file) => {
  const form = new FormData();
  form.append("file", file);
  const r = await apiClient.post(`/ai/frs/persons/${personId}/photos`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return r.data;
};

export const listPhotos = async (personId) => {
  const r = await apiClient.get(`/ai/frs/persons/${personId}/photos`);
  return r.data;
};

export const deletePhoto = async (id) => {
  const r = await apiClient.delete(`/ai/frs/photos/${id}`);
  return r.data;
};

// The photo image endpoint is gated by get_current_user (Authorization header
// only — no ?token= query support), so a bare <img src> cannot authenticate.
// Fetch the bytes with the bearer token and hand back an object URL. The caller
// MUST URL.revokeObjectURL(url) when the image unmounts. Uses native fetch for
// the same reason as cameras.onvifSnapshotBlobUrl (blob + buggy XHR shims).
export const photoImageUrl = async (id) => {
  const token = getAccessToken();
  let resp;
  try {
    resp = await fetch(`${BACKEND_URL}/api/ai/frs/photos/${id}/image`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch (_e) {
    return null;
  }
  if (!resp.ok) return null;
  const blob = await resp.blob();
  if (!blob || blob.size === 0) return null;
  return URL.createObjectURL(blob);
};

// ---------- FRS — query (events / attendance / reports) ----------

export const listFrsEvents = async (params = {}) => {
  const r = await apiClient.get("/ai/frs/events", { params });
  return r.data;
};

// Generic scenario events via the unified NVR event store, filtered by the
// scenario's source_service (slug). Used by non-FRS scenarios (PPE, future
// plugins) whose events aren't in the FRS-scoped query endpoint. Normalises
// the response to the {items,total} shape EventsTab expects.
export const listScenarioEvents = async (slug, params = {}) => {
  const { since, until, ...rest } = params;
  const q = { ...rest, source_service: slug };
  if (since) q.start_date = since;
  if (until) q.end_date = until;
  const r = await apiClient.get("/events", { params: q });
  return { items: r.data.events || [], total: r.data.total || 0 };
};

export const listAttendance = async (params = {}) => {
  const r = await apiClient.get("/ai/frs/attendance", { params });
  return r.data;
};

export const attendanceReport = async (params = {}) => {
  const r = await apiClient.get("/ai/frs/attendance/report", { params });
  return r.data;
};

export const frsSummary = async (params = {}) => {
  const r = await apiClient.get("/ai/frs/summary", { params });
  return r.data;
};

// ---------- FRS — recognition (image + video) ----------
// One-shot IMAGE recognition (synchronous) and async VIDEO-file jobs. Both are
// proxied by the NVR backend through the bridge (HTTP :8099) to the FRS gRPC
// service. Image returns the result immediately; video submits a job and the
// caller polls status, then fetches results when state === "completed".

export const recognizeImage = async (file) => {
  const form = new FormData();
  form.append("file", file);
  const r = await apiClient.post("/ai/frs/recognize-image", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return r.data;
};

export const detectFaces = async (file) => {
  const form = new FormData();
  form.append("file", file);
  const r = await apiClient.post("/ai/frs/detect-faces", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return r.data;
};

export const submitVideoJob = async (file) => {
  const form = new FormData();
  form.append("file", file);
  const r = await apiClient.post("/ai/frs/video-jobs", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return r.data; // { job_id }
};

export const videoJobStatus = async (jobId) => {
  const r = await apiClient.get(`/ai/frs/video-jobs/${jobId}`);
  return r.data;
};

export const videoJobResults = async (jobId) => {
  const r = await apiClient.get(`/ai/frs/video-jobs/${jobId}/results`);
  return r.data;
};

// ---------- FRS — investigate (forensic snapshot search by query face) ----------
// Upload a query face image + top_k; the FRS scenario ranks matching snapshots.
// Proxied by the NVR backend through the bridge — NVR holds no FRS data.

export const createInvestigation = async (file, { top_k = 50 } = {}) => {
  const form = new FormData();
  form.append("file", file);
  form.append("top_k", String(top_k));
  const r = await apiClient.post("/ai/frs/investigate", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return r.data; // { hits: [...], total }
};

// ---------- FRS — tour (cross-camera person timeline) ----------

export const personTimeline = async (personId) => {
  const r = await apiClient.get(`/ai/frs/tour/timeline/${personId}`);
  return r.data; // { person_id, entries: [...] }
};

// ---------- FRS — transit (rules CRUD + sessions) ----------

export const listTransitRules = async () => {
  const r = await apiClient.get("/ai/frs/transit/rules");
  return r.data; // { rules: [...] }
};

export const createTransitRule = async (payload) => {
  const r = await apiClient.post("/ai/frs/transit/rules", payload);
  return r.data;
};

export const updateTransitRule = async (id, payload) => {
  const r = await apiClient.put(`/ai/frs/transit/rules/${id}`, payload);
  return r.data;
};

export const deleteTransitRule = async (id) => {
  const r = await apiClient.delete(`/ai/frs/transit/rules/${id}`);
  return r.data;
};

export const listTransitSessions = async (params = {}) => {
  const r = await apiClient.get("/ai/frs/transit/sessions", { params });
  return r.data; // { sessions: [...], total }
};

// ---------- PPE — compliance detection (image + video) ----------
// One-shot IMAGE compliance (synchronous) and async VIDEO-file jobs. Both are
// proxied by the NVR backend through the bridge (HTTP :8099) to the PPE gRPC
// service (:50052). Image returns per-person compliance immediately; video
// submits a job and the caller polls status, then fetches results when
// state === "JOB_COMPLETED". NVR holds no PPE data — pure proxy.

export const detectPPE = async (file) => {
  const form = new FormData();
  form.append("file", file);
  const r = await apiClient.post("/ai/ppe/detect", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return r.data; // { persons: [...], width, height, compliant_count, violation_count }
};

export const detectPose = async (file) => {
  const form = new FormData();
  form.append("file", file);
  const r = await apiClient.post("/ai/ppe/detect-pose", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return r.data; // { persons: [...], width, height }
};

export const submitPPEVideoJob = async (file) => {
  const form = new FormData();
  form.append("file", file);
  const r = await apiClient.post("/ai/ppe/video-jobs", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return r.data; // { job_id }
};

export const ppeVideoJobStatus = async (jobId) => {
  const r = await apiClient.get(`/ai/ppe/video-jobs/${jobId}`);
  return r.data;
};

export const ppeVideoJobResults = async (jobId) => {
  const r = await apiClient.get(`/ai/ppe/video-jobs/${jobId}/results`);
  return r.data;
};
