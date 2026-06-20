// =============================================================================
// Authentication Context — Auth State, Refresh Token, Role Awareness
// =============================================================================

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from "react";
import {
  loginUser,
  registerUser,
  getCurrentUser,
  updateProfile,
} from "../api/auth";
import { setTokens, clearTokens, getAccessToken } from "../api/client";

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  // Clear everything and mark as logged-out
  const resetAuth = useCallback(() => {
    clearTokens();
    setUser(null);
    setIsAuthenticated(false);
  }, []);

  // Listen for forced-logout events dispatched by the axios interceptor
  useEffect(() => {
    const handleForceLogout = () => resetAuth();
    window.addEventListener("auth:logout", handleForceLogout);
    return () => window.removeEventListener("auth:logout", handleForceLogout);
  }, [resetAuth]);

  // Verify stored token on mount
  useEffect(() => {
    const initAuth = async () => {
      const token = getAccessToken();
      if (!token) {
        setIsLoading(false);
        return;
      }
      try {
        const userData = await getCurrentUser();
        setUser(userData);
        setIsAuthenticated(true);
        localStorage.setItem("nvr_user", JSON.stringify(userData));
      } catch {
        clearTokens();
      }
      setIsLoading(false);
    };
    initAuth();
  }, []);

  // ---- login ----
  // totpToken is optional — supplied on the second step when the account has
  // 2FA enabled (or when using a one-time recovery code).
  const login = useCallback(async (username, password, totpToken) => {
    const payload = { username, password };
    if (totpToken) payload.totp_token = totpToken;
    const res = await loginUser(payload);
    setTokens(res.access_token, res.refresh_token);
    localStorage.setItem("nvr_user", JSON.stringify(res.user));
    setUser(res.user);
    setIsAuthenticated(true);
    return res.user;
  }, []);

  // ---- register ----
  const register = useCallback(async (username, email, password) => {
    const res = await registerUser({ username, email, password });
    setTokens(res.access_token, res.refresh_token);
    localStorage.setItem("nvr_user", JSON.stringify(res.user));
    setUser(res.user);
    setIsAuthenticated(true);
    return res.user;
  }, []);

  // ---- logout ----
  const logout = useCallback(() => resetAuth(), [resetAuth]);

  // ---- refresh profile from server ----
  const refreshUser = useCallback(async () => {
    try {
      const userData = await getCurrentUser();
      setUser(userData);
      localStorage.setItem("nvr_user", JSON.stringify(userData));
      return userData;
    } catch {
      resetAuth();
      return null;
    }
  }, [resetAuth]);

  // ---- update profile ----
  const updateUserProfile = useCallback(async (data) => {
    const updated = await updateProfile(data);
    setUser(updated);
    localStorage.setItem("nvr_user", JSON.stringify(updated));
    return updated;
  }, []);

  // ---- role helpers ----
  const hasRole = useCallback(
    (role) => {
      if (!user) return false;
      if (user.is_admin) return true;
      return (user.role_name || user.role) === role;
    },
    [user],
  );

  const isAdmin = useMemo(() => user?.is_admin === true, [user]);

  // ---- context value ----
  const value = useMemo(
    () => ({
      user,
      isLoading,
      isAuthenticated,
      isAdmin,
      login,
      register,
      logout,
      refreshUser,
      updateUserProfile,
      hasRole,
    }),
    [
      user,
      isLoading,
      isAuthenticated,
      isAdmin,
      login,
      register,
      logout,
      refreshUser,
      updateUserProfile,
      hasRole,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};

export default AuthContext;
