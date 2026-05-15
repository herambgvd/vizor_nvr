// =============================================================================
// useLicense — global license snapshot, polled every 5 min.
// =============================================================================
// Provides:
//   data            full snapshot from /api/license
//   isLoading       initial fetch in flight
//   isActive        license file installed + signature valid (or in grace)
//   scenarios       Set of licensed scenario slugs (lowercase)
//   isScenarioLicensed(slug)
//   cameraCap       { used, limit }    — null when no license
//   aiCameraCap     { used, limit }    — null when no license
// =============================================================================

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getLicense } from "../api/license";

export const useLicense = () => {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["license"],
    queryFn: getLicense,
    refetchInterval: 5 * 60 * 1000,
    staleTime: 60 * 1000,
  });

  const isActive = !!data?.active;
  const scenarios = useMemo(() => {
    const s = new Set();
    (data?.scenarios || []).forEach((x) => s.add(x));
    return s;
  }, [data]);

  return {
    data,
    isLoading,
    isActive,
    inGrace: !!data?.in_grace,
    daysRemaining: data?.days_remaining ?? 0,
    tier: data?.tier || null,
    scenarios,
    isScenarioLicensed: (slug) =>
      // No license installed → dev mode, treat as licensed
      !isActive || scenarios.has(slug),
    cameraCap: isActive
      ? { used: data?.usage?.cameras ?? 0, limit: data?.camera_limit ?? 0 }
      : null,
    aiCameraCap: isActive
      ? { used: data?.usage?.ai_cameras ?? 0, limit: data?.ai_camera_limit ?? 0 }
      : null,
    refetch,
  };
};

export default useLicense;
