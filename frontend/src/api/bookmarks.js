// =============================================================================
// Bookmarks API — CRUD
// =============================================================================

import apiClient from "./client";

export const createBookmark = async (data) => {
  const response = await apiClient.post("/bookmarks", data);
  return response.data;
};

export const getBookmarks = async (params = {}) => {
  const response = await apiClient.get("/bookmarks", { params });
  return response.data;
};

export const getBookmark = async (id) => {
  const response = await apiClient.get(`/bookmarks/${id}`);
  return response.data;
};

export const updateBookmark = async (id, data) => {
  const response = await apiClient.patch(`/bookmarks/${id}`, data);
  return response.data;
};

export const deleteBookmark = async (id) => {
  const response = await apiClient.delete(`/bookmarks/${id}`);
  return response.data;
};
