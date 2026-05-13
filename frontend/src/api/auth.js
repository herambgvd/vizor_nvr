// =============================================================================
// Authentication API — Login, Register, Profile, User Management
// =============================================================================

import apiClient from "./client";

// ---------- auth flows ----------

export const checkSetup = async () => {
  const response = await apiClient.get("/auth/setup");
  return response.data; // { required: bool }
};

export const registerUser = async (data) => {
  const response = await apiClient.post("/auth/register", data);
  return response.data;
};

export const loginUser = async (data) => {
  const response = await apiClient.post("/auth/login", data);
  return response.data;
};

export const refreshToken = async (refreshToken) => {
  const response = await apiClient.post("/auth/refresh", {
    refresh_token: refreshToken,
  });
  return response.data;
};

// ---------- profile ----------

export const getCurrentUser = async () => {
  const response = await apiClient.get("/auth/me");
  return response.data;
};

export const updateProfile = async (data) => {
  const response = await apiClient.put("/auth/me", data);
  return response.data;
};

// ---------- roles ----------

export const getRoles = async () => {
  const response = await apiClient.get("/auth/roles");
  return response.data;
};

// ---------- user management (admin) ----------

export const getAllUsers = async () => {
  const response = await apiClient.get("/auth/users");
  return response.data;
};

export const createUser = async (data) => {
  const response = await apiClient.post("/auth/users", data);
  return response.data;
};

export const updateUser = async (userId, data) => {
  const response = await apiClient.put(`/auth/users/${userId}`, data);
  return response.data;
};

export const deleteUser = async (userId) => {
  const response = await apiClient.delete(`/auth/users/${userId}`);
  return response.data;
};

export const revokeSessions = async (userId) => {
  const response = await apiClient.post(`/auth/users/${userId}/revoke-sessions`);
  return response.data;
};

export const logoutUser = async (refreshToken) => {
  const response = await apiClient.post("/auth/logout", { refresh_token: refreshToken });
  return response.data;
};
