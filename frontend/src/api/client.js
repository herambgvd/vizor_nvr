// =============================================================================
// API Client - Axios Configuration with Token Refresh
// =============================================================================

import axios from "axios";

// Empty default = same-origin. Nginx proxies /api → backend in prod/dev
// docker. Set REACT_APP_BACKEND_URL only when the frontend is served
// from a different origin than the API (e.g. local CRA dev server at
// :3000 talking to backend at :8000).
export const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";

const apiClient = axios.create({
  baseURL: `${BACKEND_URL}/api`,
  headers: { "Content-Type": "application/json" },
  timeout: 15000,
});

// ---------- token helpers ----------
export const getAccessToken = () => localStorage.getItem("nvr_token");
export const getRefreshToken = () => localStorage.getItem("nvr_refresh_token");
export const setTokens = (access, refresh) => {
  localStorage.setItem("nvr_token", access);
  if (refresh) localStorage.setItem("nvr_refresh_token", refresh);
};
export const clearTokens = () => {
  localStorage.removeItem("nvr_token");
  localStorage.removeItem("nvr_refresh_token");
  localStorage.removeItem("nvr_user");
};

// ---------- refresh queue ----------
let isRefreshing = false;
let refreshSubscribers = [];

const onRefreshed = (token) => {
  refreshSubscribers.forEach((cb) => cb(token));
  refreshSubscribers = [];
};

const onRefreshFailed = () => {
  refreshSubscribers.forEach((cb) => cb(null));
  refreshSubscribers = [];
};

const addRefreshSubscriber = (cb) => {
  refreshSubscribers.push(cb);
};

// ---------- request interceptor ----------
apiClient.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ---------- response interceptor ----------
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Backend license gate: any data API returns 403 { license_required }
    // when no valid license is installed. Force the operator to the license
    // screen. The license/auth/health endpoints are never gated, so this
    // cannot loop.
    if (
      error.response?.status === 403 &&
      error.response?.data?.license_required &&
      typeof window !== "undefined" &&
      window.location.pathname !== "/license-required"
    ) {
      window.location.assign("/license-required");
      return Promise.reject(error);
    }

    // Only attempt refresh on 401 and if we haven't already retried
    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      originalRequest.url !== "/auth/login" &&
      originalRequest.url !== "/auth/refresh"
    ) {
      const refreshToken = getRefreshToken();

      if (!refreshToken) {
        clearTokens();
        window.dispatchEvent(new Event("auth:logout"));
        return Promise.reject(error);
      }

      if (isRefreshing) {
        // Queue this request until the ongoing refresh completes
        return new Promise((resolve, reject) => {
          addRefreshSubscriber((newToken) => {
            if (!newToken) {
              reject(error);
              return;
            }
            originalRequest.headers.Authorization = `Bearer ${newToken}`;
            resolve(apiClient(originalRequest));
          });
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const { data } = await axios.post(
          `${BACKEND_URL}/api/auth/refresh`,
          { refresh_token: refreshToken },
          { headers: { "Content-Type": "application/json" } },
        );
        setTokens(data.access_token, data.refresh_token);
        onRefreshed(data.access_token);
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
        return apiClient(originalRequest);
      } catch (refreshError) {
        clearTokens();
        onRefreshFailed();
        window.dispatchEvent(new Event("auth:logout"));
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  },
);

export default apiClient;
