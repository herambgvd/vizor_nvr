// =============================================================================
// FRS Query API client (F6) — read-side endpoints powering the FRS workspace
// tabs (Live / Events / Attendance / Reports).
//
// Backend: app/ai/frs_query_router.py — mounted at /api/ai/frs.
//   GET /api/ai/frs/events             — recognition events (filters)
//   GET /api/ai/frs/attendance         — attendance list (person name joined)
//   GET /api/ai/frs/attendance/report  — per-person attendance aggregate
//   GET /api/ai/frs/reports/summary    — dashboard summary aggregates
//   GET /api/ai/frs/live               — recent events for FE polling
//
// Scenario→camera assignments come from the AI camera-config router
//   GET /api/ai/scenarios/{scenario_id}/cameras
// =============================================================================

import apiClient from "./client";

// ---------- Events ----------

// params: { camera_id?: string|string[], person_id?, event_type?,
//           since?, until?, limit?, offset? }
export const listFrsEvents = async (params = {}) => {
  const r = await apiClient.get("/ai/frs/events", { params });
  return r.data; // { items, total, limit, offset }
};

// Recent recognition events for the live tab (polling / SSE backfill).
// params: { camera_id?: string|string[], limit? }
export const listFrsLive = async (params = {}) => {
  const r = await apiClient.get("/ai/frs/live", { params });
  return r.data; // { items, stream_url }
};

// ---------- Attendance ----------

// params: { person_id?, camera_id?, since?, until?, limit?, offset? }
export const listAttendance = async (params = {}) => {
  const r = await apiClient.get("/ai/frs/attendance", { params });
  return r.data; // { items, total, limit, offset }
};

// params: { day_from: "YYYY-MM-DD", day_to: "YYYY-MM-DD" }
export const attendanceReport = async (params = {}) => {
  const r = await apiClient.get("/ai/frs/attendance/report", { params });
  return r.data; // { items, day_from, day_to }
};

// ---------- Reports ----------

// params: { since?, until? }
export const frsSummary = async (params = {}) => {
  const r = await apiClient.get("/ai/frs/reports/summary", { params });
  return r.data; // { total_events, unique_persons, unknown_count, spoof_count, by_camera, by_hour }
};

// ---------- Scenario → assigned cameras ----------

export const getScenarioCameras = async (scenarioId) => {
  const r = await apiClient.get(`/ai/scenarios/${scenarioId}/cameras`);
  return r.data; // [{ id, camera_id, camera_name, enabled, stream_state, ... }]
};
