// =============================================================================
// AI Scenarios + Per-Camera Configuration API
// =============================================================================
// Wraps the /api/ai/* endpoints. Backing tables:
//   - ai_scenarios          (catalog seeded at startup)
//   - camera_ai_configs     (per-camera enablement + override config)
// =============================================================================

import apiClient from "./client";

/**
 * List all AI scenarios in the catalog, optionally filtered.
 * @param {Object} filters
 * @param {string} [filters.category] - person|vehicle|behavior|safety|security|search
 * @param {string} [filters.tier]     - free|pro|business|enterprise
 * @param {string} [filters.status]   - ga|beta|planned
 */
export const listScenarios = (filters = {}) =>
  apiClient.get("/ai/scenarios", { params: filters }).then((r) => r.data);

/**
 * Fetch one scenario by slug.
 */
export const getScenario = (slug) =>
  apiClient.get(`/ai/scenarios/${slug}`).then((r) => r.data);

/**
 * List AI scenarios enabled on a camera (with their config blobs).
 */
export const listCameraScenarios = (cameraId) =>
  apiClient.get(`/ai/cameras/${cameraId}/scenarios`).then((r) => r.data);

/**
 * Enable or update an AI scenario on a camera.
 * @param {string} cameraId
 * @param {string} slug
 * @param {Object} body
 * @param {boolean} body.enabled
 * @param {Object} body.config
 */
export const upsertCameraScenario = (cameraId, slug, body) =>
  apiClient
    .put(`/ai/cameras/${cameraId}/scenarios/${slug}`, body)
    .then((r) => r.data);

/**
 * Remove an AI scenario from a camera.
 */
export const removeCameraScenario = (cameraId, slug) =>
  apiClient
    .delete(`/ai/cameras/${cameraId}/scenarios/${slug}`)
    .then((r) => r.data);
