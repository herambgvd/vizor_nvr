// =============================================================================
// AI · ScenarioIntegrationPanel — public dashboard + third-party ingest API.
//
// Generic, slug-driven integration controls shared by every scenario's Settings
// tab. Renders the public-dashboard toggle (with optional show-names) and the
// data-ingest API controls (endpoint, key rotation, sample payload). All copy is
// scenario-neutral; pass `scenarioName` to personalise the descriptions.
// =============================================================================

import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Copy,
  Globe,
  PlugZap,
  RefreshCw,
  ToggleLeft,
  ToggleRight,
} from "lucide-react";
import { toast } from "sonner";
import { friendlyError } from "../../lib/utils";
import {
  getScenarioFeatureSettings,
  rotateScenarioIngestKey,
  updateScenarioFeatureSettings,
} from "../../api/ai";

const copyText = (value, label) => {
  navigator.clipboard?.writeText(String(value || ""));
  toast.success(`${label} copied`);
};

const ScenarioIntegrationPanel = ({ slug, scenarioName }) => {
  const qc = useQueryClient();
  const label = scenarioName || "this feature";
  const { data, isLoading } = useQuery({
    queryKey: ["scenario-feature-settings", slug],
    queryFn: () => getScenarioFeatureSettings(slug),
    retry: 1,
  });

  const save = useMutation({
    mutationFn: (patch) => updateScenarioFeatureSettings(slug, patch),
    onSuccess: (res) => {
      qc.setQueryData(["scenario-feature-settings", slug], res);
      toast.success("Saved");
    },
    onError: (e) => toast.error(friendlyError(e, "Could not save")),
  });

  const rotate = useMutation({
    mutationFn: () => rotateScenarioIngestKey(slug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scenario-feature-settings", slug] });
      toast.success("New ingest key generated");
    },
    onError: (e) => toast.error(friendlyError(e, "Could not rotate key")),
  });

  const publicUrl = `${window.location.origin}/public/${slug}`;
  const ingestUrl = `${window.location.origin}/api/ai/${slug}/ingest`;
  const sample = data?.sample_ingest_payload || {};

  const Row = ({ icon: Icon, title, desc, checked, onToggle, children }) => (
    <div
      className="rounded p-4 space-y-3"
      style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <Icon className="h-4 w-4 mt-0.5 shrink-0" style={{ color: "var(--console-accent)" }} />
          <div className="min-w-0">
            <p className="text-sm font-semibold" style={{ color: "var(--console-text)" }}>{title}</p>
            <p className="mt-0.5 text-[12px] leading-relaxed" style={{ color: "var(--console-muted)" }}>{desc}</p>
          </div>
        </div>
        <button
          type="button"
          disabled={save.isPending}
          onClick={onToggle}
          className="inline-flex h-8 items-center gap-1.5 rounded px-3 text-[11px] font-semibold uppercase tracking-wide disabled:opacity-50 shrink-0"
          style={{
            background: checked ? "var(--console-accent)" : "var(--console-panel)",
            color: checked ? "var(--console-accent-foreground)" : "var(--console-text)",
            border: "1px solid var(--console-border)",
          }}
        >
          {checked ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}
          {checked ? "On" : "Off"}
        </button>
      </div>
      {checked && children}
    </div>
  );

  const Field = ({ label: fieldLabel, value, onCopy, mono = true }) => (
    <div className="flex items-center gap-2">
      <div className="min-w-0 flex-1">
        <p className="text-[10px] uppercase tracking-widest font-telemetry" style={{ color: "var(--console-muted)" }}>{fieldLabel}</p>
        <p className={`mt-0.5 truncate text-[12px] ${mono ? "font-mono" : ""}`} style={{ color: "var(--console-text)" }}>{value}</p>
      </div>
      <button
        type="button"
        onClick={onCopy}
        className="inline-flex h-7 w-7 items-center justify-center rounded shrink-0"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
        title="Copy"
      >
        <Copy className="h-3.5 w-3.5" style={{ color: "var(--console-muted)" }} />
      </button>
    </div>
  );

  return (
    <div
      className="rounded p-4 space-y-4"
      style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
    >
      <div className="flex items-center gap-2">
        <Globe className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
        <h3 className="font-telemetry text-[12px] font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
          Public dashboard &amp; data ingest
        </h3>
      </div>

      {isLoading ? (
        <p className="text-[12px]" style={{ color: "var(--console-muted)" }}>Loading…</p>
      ) : (
        <div className="space-y-3">
          {/* Public dashboard */}
          <Row
            icon={Globe}
            title="Public dashboard"
            desc={`A live, no-login analytics page for ${label}. Anyone with the link can view aggregate numbers (no snapshots or personal data are shown).`}
            checked={!!data?.public_dashboard_enabled}
            onToggle={() => save.mutate({ public_dashboard_enabled: !data?.public_dashboard_enabled })}
          >
            <Field label="Public link" value={publicUrl} onCopy={() => copyText(publicUrl, "Link")} mono={false} />
            <label className="flex items-center gap-2 text-[12px]" style={{ color: "var(--console-muted)" }}>
              <input
                type="checkbox"
                checked={!!data?.public_show_names}
                onChange={() => save.mutate({ public_show_names: !data?.public_show_names })}
              />
              Show person names on the public dashboard
            </label>
          </Row>

          {/* Ingest API */}
          <Row
            icon={PlugZap}
            title="Data ingest API"
            desc={`Let other systems send their detections to ${label}. Those become events and appear in this scenario's views.`}
            checked={!!data?.ingest_api_enabled}
            onToggle={() => save.mutate({ ingest_api_enabled: !data?.ingest_api_enabled })}
          >
            <Field label="Endpoint (POST)" value={ingestUrl} onCopy={() => copyText(ingestUrl, "Endpoint")} mono={false} />
            <div className="flex items-end gap-2">
              <div className="flex-1 min-w-0">
                <Field
                  label="API key (header: X-Scn-Ingest-Key)"
                  value={data?.ingest_api_key || "—"}
                  onCopy={() => copyText(data?.ingest_api_key, "Key")}
                />
              </div>
              <button
                type="button"
                disabled={rotate.isPending}
                onClick={() => rotate.mutate()}
                className="inline-flex h-7 items-center gap-1.5 rounded px-2.5 text-[11px] disabled:opacity-50 shrink-0"
                style={{ background: "var(--console-raised)", color: "var(--console-text)", border: "1px solid var(--console-border)" }}
                title="Generate a new key"
              >
                <RefreshCw className="h-3.5 w-3.5" /> New key
              </button>
            </div>
            <div>
              <div className="flex items-center justify-between">
                <p className="text-[10px] uppercase tracking-widest font-telemetry" style={{ color: "var(--console-muted)" }}>Sample request body</p>
                <button
                  type="button"
                  onClick={() => copyText(JSON.stringify(sample, null, 2), "Sample payload")}
                  className="inline-flex h-6 items-center gap-1 rounded px-2 text-[10px]"
                  style={{ background: "var(--console-raised)", color: "var(--console-muted)", border: "1px solid var(--console-border)" }}
                >
                  <Copy className="h-3 w-3" /> Copy
                </button>
              </div>
              <pre
                className="mt-1 overflow-auto rounded p-3 text-[11px] font-mono"
                style={{ background: "var(--console-raised)", color: "var(--console-text)", border: "1px solid var(--console-border)", maxHeight: 220 }}
              >
                {JSON.stringify(sample, null, 2)}
              </pre>
            </div>
          </Row>
        </div>
      )}
    </div>
  );
};

export default ScenarioIntegrationPanel;
