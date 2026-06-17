// =============================================================================
// FRS Query API client (F6) — read-side endpoints powering the FRS workspace
// tabs (Live / Events / Attendance / Reports).
//
// Backend: FRS scenario microservice (scenarios/frs), reached through the
// generic scenario proxy (NVR gates by license + enable). Plugin route paths
// mirror the former /ai/frs/* paths.
//   GET /events             — recognition events (filters)
//   GET /attendance         — attendance list (person name joined)
//   GET /attendance/report  — per-person attendance aggregate
//   GET /live               — recent events for FE polling
//
// Scenario→camera assignments come from the AI camera-config router
//   GET /api/ai/scenarios/{scenario_id}/cameras
// =============================================================================

import apiClient from "./client";
import { proxyScenario } from "./ai";

const FRS_SLUG = "frs";

// ---------- Events ----------

// params: { camera_id?: string|string[], person_id?, event_type?,
//           since?, until?, limit?, offset? }
export const listFrsEvents = async (params = {}) =>
  proxyScenario(FRS_SLUG, "/events", { params }); // { items, total, limit, offset }

// Recent recognition events for the live tab (polling / SSE backfill).
// params: { camera_id?: string|string[], limit? }
export const listFrsLive = async (params = {}) =>
  proxyScenario(FRS_SLUG, "/live", { params }); // { items }

// ---------- Attendance ----------

// params: { person_id?, camera_id?, since?, until?, limit?, offset? }
export const listAttendance = async (params = {}) =>
  proxyScenario(FRS_SLUG, "/attendance", { params }); // { items, total, limit, offset }

// params: { day_from: "YYYY-MM-DD", day_to: "YYYY-MM-DD" }
export const attendanceReport = async (params = {}) =>
  proxyScenario(FRS_SLUG, "/attendance/report", { params }); // { items, day_from, day_to }

// ---------- Scenario → assigned cameras ----------

export const getScenarioCameras = async (scenarioId) => {
  const r = await apiClient.get(`/ai/scenarios/${scenarioId}/cameras`);
  return r.data; // [{ id, camera_id, camera_name, enabled, stream_state, ... }]
};
