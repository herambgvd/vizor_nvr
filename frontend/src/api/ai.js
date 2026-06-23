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

export const getScenarioHealth = async (slug) => {
  const r = await apiClient.get(`/ai/scenarios/${slug}/health`);
  return r.data;
};

export const proxyScenario = async (
  slug,
  path,
  { method = "GET", data = undefined, params = undefined, headers = undefined, timeout = 120000, responseType = undefined } = {},
) => {
  const clean = String(path || "").replace(/^\/+/, "");
  const r = await apiClient.request({
    url: `/ai/scenarios/${slug}/proxy/${clean}`,
    method,
    data,
    params,
    headers,
    timeout,
    responseType,
  });
  return r.data;
};

// Scenario feature settings (public dashboard + third-party ingest API) — works
// for ANY scenario (frs/ppe/anpr/suspect-search). Operator-facing, routed through
// the authenticated proxy.
export const getScenarioFeatureSettings = (slug) =>
  proxyScenario(slug, "/settings");

export const updateScenarioFeatureSettings = (slug, patch) =>
  proxyScenario(slug, "/settings", { method: "PUT", data: patch });

export const rotateScenarioIngestKey = (slug) =>
  proxyScenario(slug, "/settings/ingest-key/rotate", { method: "POST" });

// Back-compat FRS-named aliases (kept so existing callers don't break).
export const getFrsFeatureSettings = (slug = "frs") => getScenarioFeatureSettings(slug);
export const updateFrsFeatureSettings = (patch, slug = "frs") => updateScenarioFeatureSettings(slug, patch);
export const rotateFrsIngestKey = (slug = "frs") => rotateScenarioIngestKey(slug);

// Realtime search — returns matching events directly ({items, total}); no job,
// no polling. The primary search path.
export const scenarioSearch = async (slug, formData) => (
  proxyScenario(slug, "/search", {
    method: "POST",
    data: formData,
    headers: { "Content-Type": "multipart/form-data" },
  })
);

// Legacy async search job (kept for compatibility; UI uses scenarioSearch).
export const createScenarioSearchJob = async (slug, formData) => (
  proxyScenario(slug, "/jobs/search", {
    method: "POST",
    data: formData,
    headers: { "Content-Type": "multipart/form-data" },
  })
);

export const createScenarioIndexJob = async (slug, payload = {}) => (
  proxyScenario(slug, "/jobs/index", {
    method: "POST",
    data: payload,
  })
);

export const createScenarioSimilarSearchJob = async (slug, resultId, payload = {}) => (
  proxyScenario(slug, `/results/${resultId}/search-similar`, {
    method: "POST",
    data: payload,
  })
);

export const getScenarioJob = async (slug, jobId) => (
  proxyScenario(slug, `/jobs/${jobId}`)
);

export const getScenarioJobResults = async (slug, jobId, params = {}) => (
  proxyScenario(slug, `/jobs/${jobId}/results`, { params })
);

export const listScenarioJobs = async (slug, params = {}) => (
  proxyScenario(slug, "/jobs", { params })
);

export const cancelScenarioJob = async (slug, jobId) => (
  proxyScenario(slug, `/jobs/${jobId}`, { method: "DELETE" })
);

export const scenarioReportsSummary = async (slug, params = {}) => (
  proxyScenario(slug, "/reports/summary", { params })
);

export const scenarioThumbnailUrl = async (slug, resultId) => {
  const token = getAccessToken();
  let resp;
  try {
    resp = await fetch(`${BACKEND_URL}/api/ai/scenarios/${slug}/proxy/results/${resultId}/thumbnail`, {
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

// FRS runs as a standalone scenario microservice (scenarios/frs) that owns its
// own Postgres gallery, Qdrant face index and photo volume. Every call below
// goes through the generic scenario proxy, so the NVR gates each request by
// license + enable. The plugin route paths mirror the former /ai/frs/* paths.

const FRS_SLUG = "frs";

// ---------- FRS — groups ----------

export const listGroups = async () => proxyScenario(FRS_SLUG, "/groups");

export const createGroup = async (payload) =>
  proxyScenario(FRS_SLUG, "/groups", { method: "POST", data: payload });

export const updateGroup = async (id, patch) =>
  proxyScenario(FRS_SLUG, `/groups/${id}`, { method: "PUT", data: patch });

export const deleteGroup = async (id) =>
  proxyScenario(FRS_SLUG, `/groups/${id}`, { method: "DELETE" });

// ---------- FRS — persons ----------

export const listPersons = async (params = {}) =>
  proxyScenario(FRS_SLUG, "/persons", { params });

export const createPerson = async (payload) =>
  proxyScenario(FRS_SLUG, "/persons", { method: "POST", data: payload });

export const getPerson = async (id) => proxyScenario(FRS_SLUG, `/persons/${id}`);

export const updatePerson = async (id, patch) =>
  proxyScenario(FRS_SLUG, `/persons/${id}`, { method: "PUT", data: patch });

export const deletePerson = async (id) =>
  proxyScenario(FRS_SLUG, `/persons/${id}`, { method: "DELETE" });

// ---------- FRS — photos ----------

export const uploadPhoto = async (personId, file) => {
  const form = new FormData();
  form.append("file", file);
  return proxyScenario(FRS_SLUG, `/persons/${personId}/photos`, {
    method: "POST",
    data: form,
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const listPhotos = async (personId) =>
  proxyScenario(FRS_SLUG, `/persons/${personId}/photos`);

export const deletePhoto = async (id) =>
  proxyScenario(FRS_SLUG, `/photos/${id}`, { method: "DELETE" });

export const retryPhoto = async (id) =>
  proxyScenario(FRS_SLUG, `/photos/${id}/retry`, { method: "POST" });

// The photo image endpoint is gated by get_current_user (Authorization header
// only — no ?token= query support), so a bare <img src> cannot authenticate.
// Fetch the bytes with the bearer token and hand back an object URL. The caller
// MUST URL.revokeObjectURL(url) when the image unmounts. Uses native fetch for
// the same reason as cameras.onvifSnapshotBlobUrl (blob + buggy XHR shims).
export const photoImageUrl = async (id) => {
  const token = getAccessToken();
  let resp;
  try {
    resp = await fetch(`${BACKEND_URL}/api/ai/scenarios/${FRS_SLUG}/proxy/photos/${id}/image`, {
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

// Event snapshots live in the FRS plugin and are gated by the service token via
// the scenario proxy — a bare <img src> can't authenticate. The plugin stores
// snapshot_path as a plugin-relative path ("/snapshot?key=..."). Fetch the bytes
// through the proxy with the bearer token and return an object URL (caller must
// URL.revokeObjectURL on unmount).
export const scenarioSnapshotUrl = async (slug, snapshotPath) => {
  if (!snapshotPath) return null;
  const token = getAccessToken();
  const clean = String(snapshotPath).replace(/^\/+/, "");
  let resp;
  try {
    resp = await fetch(`${BACKEND_URL}/api/ai/scenarios/${slug}/proxy/${clean}`, {
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

export const listFrsEvents = async (params = {}) =>
  proxyScenario(FRS_SLUG, "/events", { params });

export const deleteFrsEvent = async (eventId) =>
  proxyScenario(FRS_SLUG, `/events/${eventId}`, { method: "DELETE" });

// Bulk delete: pass { ids: [...] } or { all_matching: true, camera_id, event_type, since, until }.
export const bulkDeleteFrsEvents = async (body) =>
  proxyScenario(FRS_SLUG, "/events/delete", { method: "POST", data: body });

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

export const listAttendance = async (params = {}) =>
  proxyScenario(FRS_SLUG, "/attendance", { params });

export const attendanceReport = async (params = {}) =>
  proxyScenario(FRS_SLUG, "/attendance/report", { params });

export const frsReportsSummary = async (params = {}) =>
  proxyScenario(FRS_SLUG, "/reports/summary", { params });

export const submitFrsFeedback = async (body) =>
  proxyScenario(FRS_SLUG, "/feedback", { method: "POST", data: body });

// ---------- FRS — recognition (image + video) ----------
// One-shot IMAGE recognition (synchronous) and async VIDEO-file jobs, served by
// the FRS scenario microservice through the scenario proxy. Image returns the
// result immediately; video submits a job and the caller polls status, then
// fetches results when state === "JOB_COMPLETED".

export const recognizeImage = async (file) => {
  const form = new FormData();
  form.append("file", file);
  return proxyScenario(FRS_SLUG, "/recognize-image", {
    method: "POST",
    data: form,
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const detectFaces = async (file) => {
  const form = new FormData();
  form.append("file", file);
  return proxyScenario(FRS_SLUG, "/detect-faces", {
    method: "POST",
    data: form,
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const submitVideoJob = async (file) => {
  const form = new FormData();
  form.append("file", file);
  return proxyScenario(FRS_SLUG, "/video-jobs", {
    method: "POST",
    data: form,
    headers: { "Content-Type": "multipart/form-data" },
  }); // { job_id, state }
};

export const videoJobStatus = async (jobId) =>
  proxyScenario(FRS_SLUG, `/video-jobs/${jobId}`);

export const videoJobResults = async (jobId) =>
  proxyScenario(FRS_SLUG, `/video-jobs/${jobId}/results`);

// ---------- FRS — investigate (forensic snapshot search by query face) ----------
// Upload a query face image + top_k; the FRS scenario ranks matching snapshots.

export const createInvestigation = async (file, { top_k = 50 } = {}) => {
  const form = new FormData();
  form.append("file", file);
  form.append("top_k", String(top_k));
  return proxyScenario(FRS_SLUG, "/investigate", {
    method: "POST",
    data: form,
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  }); // { job_id, hits: [...], total }
};

export const listInvestigations = async (limit = 50) =>
  proxyScenario(FRS_SLUG, "/investigations", { params: { limit } });

export const getInvestigation = async (jobId) =>
  proxyScenario(FRS_SLUG, `/investigations/${jobId}`);

// ---------- FRS — tour (cross-camera person timeline) ----------

export const personTimeline = async (personId) =>
  proxyScenario(FRS_SLUG, `/tour/timeline/${personId}`); // { person_id, entries: [...] }

// ---------- FRS — transit (rules CRUD + sessions) ----------

export const listTransitRules = async () =>
  proxyScenario(FRS_SLUG, "/transit/rules"); // { rules: [...] }

export const createTransitRule = async (payload) =>
  proxyScenario(FRS_SLUG, "/transit/rules", { method: "POST", data: payload });

export const updateTransitRule = async (id, payload) =>
  proxyScenario(FRS_SLUG, `/transit/rules/${id}`, { method: "PUT", data: payload });

export const deleteTransitRule = async (id) =>
  proxyScenario(FRS_SLUG, `/transit/rules/${id}`, { method: "DELETE" });

export const listTransitSessions = async (params = {}) =>
  proxyScenario(FRS_SLUG, "/transit/sessions", { params }); // { sessions: [...], total }

// ---------- generic scenario events / plates (plugin-owned) ----------
// Plugin scenarios (PPE, ANPR) own their event store and expose a unified
// {items,total,limit,offset} envelope. Read endpoint differs by scenario:
// PPE serves /events, ANPR serves /plates (the plate reads ARE the events).
export const SCENARIO_EVENT_ENDPOINT = { ppe: "/events", anpr: "/plates" };

export const scenarioEventEndpoint = (slug) =>
  SCENARIO_EVENT_ENDPOINT[slug] || "/events";

// List a plugin scenario's events/plate-reads via its own read endpoint.
export const listScenarioPluginEvents = async (slug, params = {}) =>
  proxyScenario(slug, scenarioEventEndpoint(slug), { params });

// Delete one plugin event (PPE /events/{id}, ANPR /plates/{id}).
export const deleteScenarioPluginEvent = async (slug, id) =>
  proxyScenario(slug, `${scenarioEventEndpoint(slug)}/${id}`, { method: "DELETE" });

// Bulk delete — accepts { ids: [...] } or { all_matching: true, ... }.
export const bulkDeleteScenarioPluginEvents = async (slug, body) =>
  proxyScenario(slug, `${scenarioEventEndpoint(slug)}/delete`, { method: "POST", data: body });

// ---------- ANPR — user-defined plate lists ----------
const ANPR_SLUG = "anpr";

// List definitions (categories, each with an action alert/allow/log).
export const listAnprListDefs = async () =>
  proxyScenario(ANPR_SLUG, "/lists/defs");

export const createAnprListDef = async (payload) =>
  proxyScenario(ANPR_SLUG, "/lists/defs", { method: "POST", data: payload });

export const updateAnprListDef = async (id, patch) =>
  proxyScenario(ANPR_SLUG, `/lists/defs/${id}`, { method: "PUT", data: patch });

export const deleteAnprListDef = async (id) =>
  proxyScenario(ANPR_SLUG, `/lists/defs/${id}`, { method: "DELETE" });

// Plate entries (each belongs to a list_id).
export const listAnprLists = async (params = {}) =>
  proxyScenario(ANPR_SLUG, "/lists", { params });

export const addAnprListEntry = async (payload) =>
  proxyScenario(ANPR_SLUG, "/lists", { method: "POST", data: payload });

export const deleteAnprListEntry = async (id) =>
  proxyScenario(ANPR_SLUG, `/lists/${id}`, { method: "DELETE" });

// CSV import — multipart upload (field `file`) into a target list (by id).
export const importAnprList = async (file, listId) => {
  const form = new FormData();
  form.append("file", file);
  return proxyScenario(ANPR_SLUG, "/lists/import", {
    method: "POST",
    data: form,
    params: { list_id: listId },
    headers: { "Content-Type": "multipart/form-data" },
  });
};
