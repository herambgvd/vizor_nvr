// =============================================================================
// License Required — full-screen gate shown when no valid license is active.
// =============================================================================
// The platform is non-operational without a signed .lic file. Admins can
// upload one here (and copy the machine fingerprint the vendor needs to bind
// the license). Non-admins are told to contact their administrator.
// Reachable only while authenticated; redirects to "/" once a license is
// active.
// =============================================================================

import React, { useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ShieldAlert,
  ShieldCheck,
  UploadCloud,
  Cpu,
  Copy,
  LogOut,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { getLicense, getFingerprint, activateLicense } from "../api/license";
import { useAuth } from "../context/AuthContext";

const REASON_LABELS = {
  no_license_installed: "No license has been installed on this system.",
  not_loaded: "License state is still initializing.",
  expired: "The installed license has expired.",
  in_grace_period: "The license has expired and is in its grace period.",
  hardware_mismatch:
    "This license was issued for a different machine. Send your machine fingerprint to your vendor for a re-issue.",
  bad_signature: "The license file signature is invalid.",
  decode_failed: "The license file could not be read.",
  too_short: "The license file is malformed.",
  missing_expires_at: "The license file is missing an expiry date.",
};

const LicenseRequired = () => {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const inputRef = useRef(null);
  const { isAdmin, logout } = useAuth();

  const { data, isLoading } = useQuery({
    queryKey: ["license"],
    queryFn: getLicense,
    refetchInterval: 30 * 1000,
  });

  const { data: fp } = useQuery({
    queryKey: ["license-fingerprint"],
    queryFn: getFingerprint,
    enabled: isAdmin,
    retry: false,
  });

  const activateMut = useMutation({
    mutationFn: activateLicense,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["license"] });
      if (res?.active) {
        toast.success("License activated");
        navigate("/", { replace: true });
      } else {
        toast.error(
          REASON_LABELS[res?.reason] || res?.reason || "License not valid",
        );
      }
    },
    onError: (e) =>
      toast.error(e?.response?.data?.detail || "License activation failed"),
  });

  // Active license → leave the gate.
  React.useEffect(() => {
    if (data?.active) navigate("/", { replace: true });
  }, [data?.active, navigate]);

  const onPick = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    activateMut.mutate(f);
    e.target.value = "";
  };

  const copyFingerprint = () => {
    if (!fp?.fingerprint) return;
    navigator.clipboard.writeText(fp.fingerprint);
    toast.success("Fingerprint copied");
  };

  const reason = data?.reason;

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4"
      style={{ background: "var(--console-bg)", color: "var(--console-text)" }}
    >
      <div className="w-full max-w-lg">
        {/* Brand / status header */}
        <div className="flex flex-col items-center text-center mb-6">
          <div
            className="p-4 rounded-full mb-4"
            style={{ background: "var(--console-raised)" }}
          >
            <ShieldAlert className="h-9 w-9" style={{ color: "var(--console-rec)" }} />
          </div>
          <h1
            className="text-xl font-bold mb-1"
            style={{ fontFamily: "Manrope, sans-serif" }}
          >
            License Required
          </h1>
          <p className="text-sm" style={{ color: "var(--console-muted)" }}>
            This platform is inactive. Install a valid license to enable cameras,
            recording, and all other features.
          </p>
        </div>

        <div
          className="rounded-lg p-5 space-y-5"
          style={{
            background: "var(--console-panel)",
            border: "1px solid var(--console-border)",
          }}
        >
          {/* Status reason */}
          <div
            className="flex items-start gap-2 rounded p-3 text-[12px]"
            style={{ background: "var(--console-raised)" }}
          >
            <ShieldCheck
              className="h-4 w-4 mt-0.5 flex-shrink-0"
              style={{ color: "var(--console-muted)" }}
            />
            <span style={{ color: "var(--console-muted)" }}>
              {isLoading
                ? "Checking license status…"
                : REASON_LABELS[reason] || reason || "No active license."}
            </span>
          </div>

          {isAdmin ? (
            <>
              {/* Machine fingerprint */}
              <div>
                <div
                  className="flex items-center gap-2 mb-1.5 text-[10px] uppercase tracking-widest"
                  style={{ color: "var(--console-muted)" }}
                >
                  <Cpu className="h-3.5 w-3.5" /> Machine fingerprint
                </div>
                <div className="flex items-center gap-2">
                  <code
                    className="flex-1 truncate rounded px-2 py-1.5 text-[11px]"
                    style={{
                      background: "var(--console-raised)",
                      border: "1px solid var(--console-border)",
                      color: "var(--console-text)",
                    }}
                  >
                    {fp?.fingerprint || "…"}
                  </code>
                  <button
                    onClick={copyFingerprint}
                    className="inline-flex items-center justify-center h-[30px] w-[30px] rounded border transition-colors hover:bg-white/5"
                    style={{
                      background: "var(--console-raised)",
                      borderColor: "var(--console-border)",
                      color: "var(--console-muted)",
                    }}
                    title="Copy fingerprint"
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </button>
                </div>
                <p className="mt-1.5 text-[11px]" style={{ color: "var(--console-muted)" }}>
                  Send this fingerprint to your vendor to receive a license bound
                  to this machine.
                </p>
              </div>

              {/* Upload */}
              <input
                ref={inputRef}
                type="file"
                accept=".lic,text/plain"
                className="hidden"
                onChange={onPick}
              />
              <button
                onClick={() => inputRef.current?.click()}
                disabled={activateMut.isPending}
                className="w-full inline-flex items-center justify-center gap-2 h-[40px] rounded font-semibold text-sm transition-opacity disabled:opacity-50"
                style={{ background: "var(--console-accent)", color: "#06231f" }}
              >
                {activateMut.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <UploadCloud className="h-4 w-4" />
                )}
                Upload License File (.lic)
              </button>
            </>
          ) : (
            <p
              className="text-[12px] text-center rounded p-3"
              style={{ background: "var(--console-raised)", color: "var(--console-muted)" }}
            >
              Please contact your system administrator to install a valid
              license.
            </p>
          )}

          {/* Logout */}
          <button
            onClick={() => logout?.()}
            className="w-full inline-flex items-center justify-center gap-2 h-[34px] rounded border text-[12px] transition-colors hover:bg-white/5"
            style={{
              background: "var(--console-raised)",
              borderColor: "var(--console-border)",
              color: "var(--console-muted)",
            }}
          >
            <LogOut className="h-3.5 w-3.5" /> Sign out
          </button>
        </div>
      </div>
    </div>
  );
};

export default LicenseRequired;
