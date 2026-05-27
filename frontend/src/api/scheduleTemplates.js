// =============================================================================
// Schedule Templates API
// =============================================================================

import apiClient from "./client";

export const listScheduleTemplates = async () => {
  const response = await apiClient.get("/schedule-templates");
  return response.data;
};

export const createScheduleTemplate = async (data) => {
  const response = await apiClient.post("/schedule-templates", data);
  return response.data;
};

export const updateScheduleTemplate = async (id, data) => {
  const response = await apiClient.put(`/schedule-templates/${id}`, data);
  return response.data;
};

export const deleteScheduleTemplate = async (id) => {
  const response = await apiClient.delete(`/schedule-templates/${id}`);
  return response.data;
};

export const applyScheduleTemplate = async (id, cameraIds) => {
  const response = await apiClient.post(
    `/schedule-templates/${id}/apply`,
    { camera_ids: cameraIds },
    { timeout: 60000 },
  );
  return response.data;
};
