// =============================================================================
// useLicense — global license snapshot, polled every 5 min.
// =============================================================================
// Provides:
//   data            full snapshot from /api/license
//   isLoading       initial fetch in flight
//   isActive        license file installed + signature valid (or in grace)
//   cameraCap       { used, limit }    — null when no license
// =============================================================================

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

  return {
    data,
    isLoading,
    isActive,
    inGrace: !!data?.in_grace,
    daysRemaining: data?.days_remaining ?? 0,
    tier: data?.tier || null,
    cameraCap: isActive
      ? { used: data?.usage?.cameras ?? 0, limit: data?.camera_limit ?? 0 }
      : null,
    refetch,
  };
};

export default useLicense;
