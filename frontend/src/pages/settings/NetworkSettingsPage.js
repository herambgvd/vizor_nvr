// =============================================================================
// NetworkSettingsPage — /settings/network
// Read-only host network info + editable application-level knobs. Admin only.
// =============================================================================

import React, { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Network, RefreshCw, Info, Server, Globe } from "lucide-react";
import { toast } from "sonner";
import { getNetworkConfig, setNetworkConfig } from "../../api/system";

// ─── Shared primitives ────────────────────────────────────────────────────────

const PrimaryBtn = ({ children, disabled, onClick, type = "button" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className="inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] font-semibold uppercase tracking-wide transition-opacity disabled:opacity-50"
    style={{ background: "var(--console-accent)", color: "#06231f" }}
  >
    {children}
  </button>
);

const ConsoleCard = ({ children, className = "" }) => (
  <div
    className={`rounded overflow-hidden ${className}`}
    style={{
      background: "var(--console-panel)",
      border: "1px solid var(--console-border)",
    }}
  >
    {children}
  </div>
);

const CardHeader = ({ children }) => (
  <div
    className="flex items-center gap-2 px-4 py-3 border-b"
    style={{ borderColor: "var(--console-border)" }}
  >
    {children}
  </div>
);

const ConsoleInput = ({ className = "", style: extraStyle = {}, ...props }) => (
  <input
    {...props}
    className={`w-full rounded font-telemetry text-xs h-[30px] px-2 border outline-none focus:ring-1 ${className}`}
    style={{
      background: "var(--console-raised)",
      border: "1px solid var(--console-border)",
      color: "var(--console-text)",
      "--tw-ring-color": "var(--console-accent)",
      ...extraStyle,
    }}
  />
);

const FieldLabel = ({ children }) => (
  <label
    className="block font-telemetry text-[10px] uppercase tracking-wide mb-1"
    style={{ color: "var(--console-muted)" }}
  >
    {children}
  </label>
);

const FieldHint = ({ children }) => (
  <p className="font-telemetry text-[10px] mt-1" style={{ color: "var(--console-muted)" }}>
    {children}
  </p>
);

// ─── Read-only field row ──────────────────────────────────────────────────────

const ReadField = ({ label, value, mono }) => (
  <div
    className="flex items-start justify-between py-2 border-b last:border-0"
    style={{ borderColor: "var(--console-border)" }}
  >
    <span
      className="font-telemetry text-[11px]"
      style={{ color: "var(--console-muted)" }}
    >
      {label}
    </span>
    <span
      className={`font-telemetry text-[11px] max-w-[60%] text-right break-all ${mono ? "" : ""}`}
      style={{
        color: "var(--console-text)",
        fontFamily: mono ? "var(--font-mono, monospace)" : undefined,
      }}
    >
      {value || "—"}
    </span>
  </div>
);

// ─── Main Page ────────────────────────────────────────────────────────────────

const NetworkSettingsPage = () => {
  const qc = useQueryClient();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["system-network"],
    queryFn: getNetworkConfig,
    staleTime: 30_000,
  });

  const [lanSubnet, setLanSubnet] = useState("");
  const [corsOrigins, setCorsOrigins] = useState("*");
  const [nvrPublicHost, setNvrPublicHost] = useState("");
  const [go2rtcCandidates, setGo2rtcCandidates] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!data) return;
    setLanSubnet(data.lan_subnet || "");
    setCorsOrigins(data.cors_origins || "*");
    setNvrPublicHost(data.nvr_public_host || "");
    setGo2rtcCandidates(data.go2rtc_candidates || "");
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: () =>
      setNetworkConfig({
        lan_subnet: lanSubnet,
        cors_origins: corsOrigins,
        nvr_public_host: nvrPublicHost,
        go2rtc_candidates: go2rtcCandidates,
      }),
    onSuccess: () => {
      toast.success("Network settings saved");
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["system-network"] });
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Save failed"),
  });

  const mark = () => setDirty(true);

  const interfaces = data?.interfaces || [];

  return (
    <div
      className="h-full flex flex-col overflow-hidden"
      style={{ background: "var(--console-bg)", color: "var(--console-text)" }}
    >
      {/* Page header bar */}
      <div
        className="flex items-center gap-3 px-4 py-2.5 border-b flex-shrink-0"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        <div className="flex items-center gap-2">
          <span
            className="w-0.5 h-4 rounded-full flex-shrink-0"
            style={{ background: "var(--console-accent)" }}
          />
          <span
            className="font-telemetry text-xs font-semibold uppercase tracking-widest"
            style={{ color: "var(--console-text)" }}
          >
            Network
          </span>
        </div>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isLoading}
          className="inline-flex items-center h-[28px] px-2 rounded font-telemetry text-[11px] border transition-colors hover:bg-white/5 disabled:opacity-50"
          style={{
            background: "transparent",
            borderColor: "var(--console-border)",
            color: "var(--console-muted)",
          }}
        >
          <RefreshCw
            className={`h-3.5 w-3.5 mr-1.5 ${isLoading ? "animate-spin" : ""}`}
          />
          Refresh
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4 md:p-6 space-y-4">

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
        {/* Read-only host info */}
        <ConsoleCard>
          <CardHeader>
            <Server className="h-3.5 w-3.5" style={{ color: "var(--console-muted)" }} />
            <span
              className="font-telemetry text-xs font-semibold uppercase tracking-wide"
              style={{ color: "var(--console-text)" }}
            >
              Host Network
            </span>
            <span
              className="ml-auto flex items-center gap-1 font-telemetry text-[10px]"
              style={{ color: "var(--console-muted)" }}
            >
              <Info className="h-3 w-3" />
              Read-only — set via .env / host OS
            </span>
          </CardHeader>
          <div className="px-4 py-2">
            <ReadField label="Hostname" value={data?.hostname} mono />
            <ReadField label="Platform" value={data?.platform} />
          </div>

          {interfaces.length > 0 && (
            <div className="px-4 pb-3">
              <p
                className="font-telemetry text-[10px] uppercase tracking-widest mb-2"
                style={{ color: "var(--console-muted)" }}
              >
                Interfaces
              </p>
              <div
                className="rounded overflow-hidden"
                style={{ border: "1px solid var(--console-border)" }}
              >
                <table className="w-full font-telemetry text-[11px]">
                  <thead
                    style={{
                      background: "var(--console-raised)",
                      borderBottom: "1px solid var(--console-border)",
                    }}
                  >
                    <tr>
                      {["Name", "IP", "Mask", "Family"].map((h) => (
                        <th
                          key={h}
                          className="px-3 py-2 text-left font-semibold uppercase tracking-wide"
                          style={{ color: "var(--console-muted)" }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {interfaces.map((iface, i) => (
                      <tr
                        key={i}
                        className="border-b last:border-0"
                        style={{ borderColor: "var(--console-border)" }}
                      >
                        <td className="px-3 py-2" style={{ color: "var(--console-text)", fontFamily: "monospace" }}>
                          {iface.name}
                        </td>
                        <td className="px-3 py-2" style={{ color: "var(--console-text)", fontFamily: "monospace" }}>
                          {iface.ip}
                        </td>
                        <td className="px-3 py-2" style={{ color: "var(--console-muted)", fontFamily: "monospace" }}>
                          {iface.mask || "—"}
                        </td>
                        <td className="px-3 py-2" style={{ color: "var(--console-muted)" }}>
                          {iface.family}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </ConsoleCard>

        {/* Editable application-level knobs */}
        <ConsoleCard>
          <CardHeader>
            <Globe className="h-3.5 w-3.5" style={{ color: "var(--console-accent)" }} />
            <span
              className="font-telemetry text-xs font-semibold uppercase tracking-wide"
              style={{ color: "var(--console-text)" }}
            >
              Application Network
            </span>
          </CardHeader>
          <div className="p-4 space-y-4">
            <div>
              <FieldLabel>LAN Subnet for ONVIF Discovery</FieldLabel>
              <ConsoleInput
                type="text"
                value={lanSubnet}
                onChange={(e) => {
                  setLanSubnet(e.target.value);
                  mark();
                }}
                placeholder="e.g. 192.168.1.0/24"
              />
              <FieldHint>
                Subnet scanned for ONVIF discovery. Leave empty to scan all interfaces.
              </FieldHint>
            </div>

            <div>
              <FieldLabel>CORS Allowed Origins</FieldLabel>
              <ConsoleInput
                type="text"
                value={corsOrigins}
                onChange={(e) => {
                  setCorsOrigins(e.target.value);
                  mark();
                }}
                placeholder="* or https://myhost.local"
              />
              <FieldHint>
                Comma-separated allowed origins. Use <code>*</code> to allow all (development only).
              </FieldHint>
            </div>

            <div>
              <FieldLabel>NVR Public Host (WebRTC)</FieldLabel>
              <ConsoleInput
                type="text"
                value={nvrPublicHost}
                onChange={(e) => {
                  setNvrPublicHost(e.target.value);
                  mark();
                }}
                placeholder="e.g. nvr.example.com or 1.2.3.4"
              />
              <FieldHint>
                Hostname/IP advertised to remote WebRTC peers. Leave empty for LAN-only use.
              </FieldHint>
            </div>

            <div>
              <FieldLabel>go2rtc WebRTC ICE Candidates</FieldLabel>
              <ConsoleInput
                type="text"
                value={go2rtcCandidates}
                onChange={(e) => {
                  setGo2rtcCandidates(e.target.value);
                  mark();
                }}
                placeholder="e.g. stun:stun.l.google.com:19302"
              />
              <FieldHint>
                Comma-separated ICE server URLs passed to go2rtc WebRTC config.
              </FieldHint>
            </div>
          </div>
        </ConsoleCard>
        </div>

        {/* Save */}
        <div>
          <PrimaryBtn
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !dirty}
          >
            {saveMutation.isPending && (
              <RefreshCw className="h-3.5 w-3.5 mr-1.5 animate-spin" />
            )}
            Save Network Settings
          </PrimaryBtn>
        </div>
      </div>
    </div>
  );
};

export default NetworkSettingsPage;
