// =============================================================================
// NetworkSettingsPage — /settings/network
// Read-only host network info + editable application-level knobs. Admin only.
// =============================================================================

import React, { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Network, RefreshCw, Info, Server, Globe } from "lucide-react";
import { toast } from "sonner";
import { getNetworkConfig, setNetworkConfig } from "../../api/system";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";

const Field = ({ label, value, mono }) => (
  <div className="flex items-start justify-between py-2 border-b border-white/5 last:border-0">
    <span className="text-xs text-muted-foreground">{label}</span>
    <span className={cn("text-xs max-w-[60%] text-right break-all", mono && "font-mono")}>
      {value || "—"}
    </span>
  </div>
);

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

  // Group interfaces by name for display
  const interfaces = data?.interfaces || [];

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-2xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Network Configuration
        </h2>
        <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isLoading}>
          <RefreshCw className={cn("h-4 w-4 mr-1.5", isLoading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Read-only host info */}
      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <div className="flex items-center gap-2 px-5 py-3 border-b border-white/5">
          <Server className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold">Host Network</h3>
          <span className="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground">
            <Info className="h-3 w-3" />
            Read-only — set via .env / host OS
          </span>
        </div>
        <div className="px-5 py-2">
          <Field label="Hostname" value={data?.hostname} mono />
          <Field label="Platform" value={data?.platform} />
        </div>

        {interfaces.length > 0 && (
          <div className="px-5 pb-3">
            <p className="text-[11px] text-muted-foreground uppercase tracking-wider mb-2">
              Interfaces
            </p>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted-foreground">
                  <th className="text-left font-medium pb-1 pr-4">Name</th>
                  <th className="text-left font-medium pb-1 pr-4">IP</th>
                  <th className="text-left font-medium pb-1 pr-4">Mask</th>
                  <th className="text-left font-medium pb-1">Family</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {interfaces.map((iface, i) => (
                  <tr key={i} className="font-mono">
                    <td className="py-1 pr-4 text-zinc-300">{iface.name}</td>
                    <td className="py-1 pr-4">{iface.ip}</td>
                    <td className="py-1 pr-4 text-muted-foreground">{iface.mask || "—"}</td>
                    <td className="py-1 text-muted-foreground">{iface.family}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Editable application-level knobs */}
      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <div className="flex items-center gap-2 px-5 py-3 border-b border-white/5">
          <Globe className="h-4 w-4 text-teal-300" />
          <h3 className="text-sm font-semibold">Application Network</h3>
        </div>
        <div className="p-5 space-y-4">
          {/* LAN Subnet */}
          <div>
            <label className="block text-xs font-medium mb-1.5">
              LAN Subnet for ONVIF Discovery
            </label>
            <input
              type="text"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
              value={lanSubnet}
              onChange={(e) => { setLanSubnet(e.target.value); mark(); }}
              placeholder="e.g. 192.168.1.0/24"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Subnet scanned for ONVIF discovery. Leave empty to scan all interfaces.
            </p>
          </div>

          {/* CORS Origins */}
          <div>
            <label className="block text-xs font-medium mb-1.5">
              CORS Allowed Origins
            </label>
            <input
              type="text"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
              value={corsOrigins}
              onChange={(e) => { setCorsOrigins(e.target.value); mark(); }}
              placeholder="* or https://myhost.local"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Comma-separated allowed origins. Use <code>*</code> to allow all (development only).
            </p>
          </div>

          {/* NVR Public Host */}
          <div>
            <label className="block text-xs font-medium mb-1.5">
              NVR Public Host (WebRTC)
            </label>
            <input
              type="text"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
              value={nvrPublicHost}
              onChange={(e) => { setNvrPublicHost(e.target.value); mark(); }}
              placeholder="e.g. nvr.example.com or 1.2.3.4"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Hostname/IP advertised to remote WebRTC peers. Leave empty for LAN-only use.
            </p>
          </div>

          {/* go2rtc Candidates */}
          <div>
            <label className="block text-xs font-medium mb-1.5">
              go2rtc WebRTC ICE Candidates
            </label>
            <input
              type="text"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
              value={go2rtcCandidates}
              onChange={(e) => { setGo2rtcCandidates(e.target.value); mark(); }}
              placeholder="e.g. stun:stun.l.google.com:19302"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Comma-separated ICE server URLs passed to go2rtc WebRTC config.
            </p>
          </div>
        </div>
      </div>

      {/* Save */}
      <div>
        <Button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending || !dirty}
        >
          {saveMutation.isPending && (
            <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
          )}
          Save Network Settings
        </Button>
      </div>
    </div>
  );
};

export default NetworkSettingsPage;
