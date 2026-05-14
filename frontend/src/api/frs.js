// =============================================================================
// FRS API — Persons + Groups for the face recognition gallery.
// =============================================================================
import apiClient from "./client";

// ---------- Groups ----------
export const listFRSGroups = () =>
  apiClient.get("/ai/frs/groups").then((r) => r.data);

export const createFRSGroup = (data) =>
  apiClient.post("/ai/frs/groups", data).then((r) => r.data);

export const updateFRSGroup = (groupId, data) =>
  apiClient.patch(`/ai/frs/groups/${groupId}`, data).then((r) => r.data);

export const deleteFRSGroup = (groupId) =>
  apiClient.delete(`/ai/frs/groups/${groupId}`).then((r) => r.data);


// ---------- Persons ----------
export const listFRSPersons = (params = {}) =>
  apiClient.get("/ai/frs/persons", { params }).then((r) => r.data);

export const getFRSPerson = (personId) =>
  apiClient.get(`/ai/frs/persons/${personId}`).then((r) => r.data);

export const createFRSPerson = (data) =>
  apiClient.post("/ai/frs/persons", data).then((r) => r.data);

export const updateFRSPerson = (personId, data) =>
  apiClient.patch(`/ai/frs/persons/${personId}`, data).then((r) => r.data);

export const deleteFRSPerson = (personId) =>
  apiClient.delete(`/ai/frs/persons/${personId}`).then((r) => r.data);


// ---------- Photos ----------
export const listFRSPhotos = (personId) =>
  apiClient.get(`/ai/frs/persons/${personId}/photos`).then((r) => r.data);

export const uploadFRSPhoto = (personId, file) => {
  const form = new FormData();
  form.append("file", file);
  return apiClient
    .post(`/ai/frs/persons/${personId}/photos`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

export const deleteFRSPhoto = (personId, photoId) =>
  apiClient
    .delete(`/ai/frs/persons/${personId}/photos/${photoId}`)
    .then((r) => r.data);
