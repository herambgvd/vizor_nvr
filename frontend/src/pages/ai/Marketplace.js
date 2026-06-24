// =============================================================================
// AI · Marketplace — WordPress-style plugin lifecycle for AI scenarios.
// =============================================================================
// One card per scenario plugin showing the full activation pipeline:
//   Install → License → Enable → Cameras.
// From here an operator can request a license (offline blob → vendor), activate
// (upload the signed .lic via Settings · License), enable/disable a licensed
// plugin, and open its workspace. The catalog is manifest-driven: a plugin that
// has registered its scenario.json appears here even before it is licensed.
// =============================================================================

import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ScanFace, HardHat, Cpu, Search, KeyRound, Copy, X, Check, Lock,
  Power, ArrowRight, CircleDot, CircleCheck, Circle,
} from "lucide-react";
import { toast } from "sonner";
import { getScenarios, toggleScenario } from "../../api/ai";
import { requestScenarioLicense } from "../../api/license";
import { friendlyError } from "../../lib/utils";

const ICONS = { "scan-face": ScanFace, "hard-hat": HardHat, search: Search };

// The four lifecycle stages a plugin moves through. The current stage is the
// last one whose predicate is satisfied.
const STAGES = [
  { key: "install", label: "Installed", done: (s) => s.registered },
  { key: "license", label: "Licensed", done: (s) => s.licensed },
  { key: "enable", label: "Enabled", done: (s) => s.enabled },
  { key: "cameras", label: "Cameras", done: (s) => (s.active_camera_count || 0) > 0 },
];

const stageIndex = (s) => {
  let idx = -1;
  STAGES.forEach((st, i) => {
    if (st.done(s)) idx = i;
  });
  return idx;
};

const Pipeline = ({ scenario }) => {
  const current = stageIndex(scenario);
  return (
    <div className="flex items-center gap-1">
      {STAGES.map((st, i) => {
        const done = st.done(scenario);
        const isNext = i === current + 1;
        const Icon = done ? CircleCheck : isNext ? CircleDot : Circle;
        return (
          <React.Fragment key={st.key}>
            <div className="flex items-center gap-1" title={st.label}>
              <Icon
                className="h-3 w-3"
                style={{
                  color: done
                    ? "var(--console-accent)"
                    : isNext
                    ? "var(--console-text)"
                    : "var(--console-muted)",
                }}
              />
              <span
                className="font-telemetry text-[9px] uppercase tracking-wide"
                style={{
                  color: done
                    ? "var(--console-accent)"
                    : isNext
                    ? "var(--console-text)"
                    : "var(--console-muted)",
                }}
              >
                {st.label}
              </span>
            </div>
            {i < STAGES.length - 1 && (
              <div
                className="h-px w-3"
                style={{ background: "var(--console-border)" }}
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
};

const Toggle = ({ checked, disabled, onChange }) => (
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    disabled={disabled}
    onClick={() => onChange(!checked)}
    className="relative inline-flex h-[20px] w-[36px] items-center rounded-full transition-colors disabled:opacity-40"
    style={{ background: checked ? "var(--console-accent)" : "var(--console-border)" }}
  >
    <span
      className="inline-block h-[14px] w-[14px] rounded-full bg-white transition-transform"
      style={{ transform: checked ? "translateX(19px)" : "translateX(3px)" }}
    />
  </button>
);

const PluginCard = ({ scenario, onOpen, onToggle, onRequestLicense, pending }) => {
  const Icon = ICONS[scenario.icon] || Cpu;
  const cap = scenario.camera_limit || 0;
  const used = scenario.active_camera_count || 0;
  const caps = scenario.capabilities || [];
  const operable = scenario.registered && scenario.licensed;
  return (
    <div
      className="rounded p-4 flex flex-col gap-3"
      style={{
        background: "var(--console-panel)",
        border: "1px solid var(--console-border)",
        opacity: scenario.registered ? 1 : 0.6,
      }}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2.5">
          <div
            className="h-10 w-10 rounded flex items-center justify-center"
            style={{ background: "var(--console-raised)" }}
          >
            <Icon className="h-5 w-5" style={{ color: "var(--console-accent)" }} />
          </div>
          <div>
            <div
              className="font-telemetry text-[13px] font-semibold uppercase tracking-wide"
              style={{ color: "var(--console-text)" }}
            >
              {scenario.name}
            </div>
            <div
              className="font-telemetry text-[10px] uppercase tracking-widest flex items-center gap-1.5"
              style={{ color: "var(--console-muted)" }}
            >
              {scenario.category || scenario.slug}
              {scenario.version && <span style={{ opacity: 0.7 }}>v{scenario.version}</span>}
            </div>
          </div>
        </div>
        {scenario.licensed ? (
          <Toggle
            checked={scenario.enabled}
            disabled={pending || !scenario.registered}
            onChange={(v) => onToggle(scenario, v)}
          />
        ) : (
          <span
            className="inline-flex items-center gap-1 font-telemetry text-[10px] px-1.5 py-0.5 rounded border"
            style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}
          >
            <Lock className="h-3 w-3" /> Locked
          </span>
        )}
      </div>

      <p
        className="font-telemetry text-[11px] leading-relaxed line-clamp-2"
        style={{ color: "var(--console-muted)" }}
      >
        {scenario.description || "AI scenario plugin"}
      </p>

      {caps.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {caps.slice(0, 5).map((c) => (
            <span
              key={c}
              className="rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wide font-telemetry"
              style={{ background: "var(--console-raised)", color: "var(--console-muted)" }}
            >
              {c}
            </span>
          ))}
        </div>
      )}

      <Pipeline scenario={scenario} />

      <div
        className="flex items-center justify-between mt-auto pt-2 gap-2"
        style={{ borderTop: "1px solid var(--console-border)" }}
      >
        <span className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
          {used}{cap > 0 ? ` / ${cap}` : ""} cams
          {scenario.enabled && (
            <Check className="inline h-3 w-3 ml-1" style={{ color: "var(--console-accent)" }} />
          )}
        </span>
        <div className="flex items-center gap-1.5">
          {!scenario.licensed && (
            <button
              type="button"
              onClick={() => onRequestLicense(scenario)}
              className="inline-flex items-center gap-1 font-telemetry text-[10px] uppercase tracking-wide px-2 py-1 rounded border"
              style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-accent)" }}
            >
              <KeyRound className="h-3 w-3" /> Request
            </button>
          )}
          {operable && (
            <button
              type="button"
              onClick={() => onOpen(scenario)}
              className="inline-flex items-center gap-1 font-telemetry text-[10px] uppercase tracking-wide px-2 py-1 rounded"
              style={{ background: "var(--console-accent)", color: "#000" }}
            >
              Open <ArrowRight className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

const RequestLicenseModal = ({ scenario, data, loading, onClose }) => {
  const copy = async (text, label) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(`${label} copied`);
    } catch {
      toast.error("Copy failed — select and copy manually");
    }
  };
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.6)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded p-5 flex flex-col gap-4"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="font-telemetry text-[13px] font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
              Request License — {scenario.name}
            </div>
            <div className="font-telemetry text-[10px] uppercase tracking-widest mt-0.5" style={{ color: "var(--console-muted)" }}>
              Send this request to your provider to unlock {scenario.slug}
            </div>
          </div>
          <button type="button" onClick={onClose} style={{ color: "var(--console-muted)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>

        {loading ? (
          <p className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
            Generating request…
          </p>
        ) : data ? (
          <>
            <div className="flex flex-col gap-1.5">
              <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                Machine fingerprint
              </span>
              <code className="font-telemetry text-[11px] break-all p-2 rounded" style={{ background: "var(--console-raised)", color: "var(--console-text)" }}>
                {data.fingerprint}
              </code>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                License request blob
              </span>
              <textarea
                readOnly
                value={data.request}
                rows={4}
                className="font-telemetry text-[11px] break-all p-2 rounded resize-none"
                style={{ background: "var(--console-raised)", color: "var(--console-text)", border: "1px solid var(--console-border)" }}
                onFocus={(e) => e.target.select()}
              />
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => copy(data.request, "Request")}
                className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-wide px-3 py-1.5 rounded"
                style={{ background: "var(--console-accent)", color: "#000" }}
              >
                <Copy className="h-3 w-3" /> Copy request
              </button>
              <button
                type="button"
                onClick={() => copy(data.fingerprint, "Fingerprint")}
                className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-wide px-3 py-1.5 rounded border"
                style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-text)" }}
              >
                <Copy className="h-3 w-3" /> Copy fingerprint
              </button>
            </div>
            <p className="font-telemetry text-[10px] leading-relaxed" style={{ color: "var(--console-muted)" }}>
              Your provider returns a signed <code>.lic</code> file. Upload it under
              Settings · License to activate {scenario.name}.
            </p>
          </>
        ) : (
          <p className="font-telemetry text-[11px]" style={{ color: "var(--console-rec)" }}>
            Couldn't generate the request. Try again.
          </p>
        )}
      </div>
    </div>
  );
};

const Marketplace = () => {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [reqScenario, setReqScenario] = useState(null);
  const [reqData, setReqData] = useState(null);

  const { data: scenarios = [], isLoading } = useQuery({
    queryKey: ["ai-scenarios"],
    queryFn: getScenarios,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }) => toggleScenario(id, enabled),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ["ai-scenarios"] });
      toast.success(`Plugin ${vars.enabled ? "enabled" : "disabled"}`);
    },
    onError: (e) => {
      const detail = e?.response?.data?.detail;
      const status = e?.response?.status;
      toast.error(
        status === 400 && typeof detail === "string" && detail
          ? detail
          : friendlyError(e, "Couldn't update the plugin."),
      );
    },
  });

  const reqMut = useMutation({
    mutationFn: (slug) => requestScenarioLicense(slug),
    onSuccess: (data) => setReqData(data),
    onError: (e) => {
      toast.error(friendlyError(e, "Couldn't generate the license request."));
      setReqScenario(null);
    },
  });

  const onToggle = (s, enabled) => toggleMut.mutate({ id: s.id, enabled });
  const onOpen = (s) => navigate(`/ai/${s.slug}`);
  const onRequestLicense = (s) => {
    setReqScenario(s);
    setReqData(null);
    reqMut.mutate(s.slug);
  };

  return (
    <div className="p-6 w-full">
      <div className="mb-6">
        <h1
          className="font-telemetry text-[16px] font-semibold uppercase tracking-wide"
          style={{ color: "var(--console-text)" }}
        >
          AI Marketplace
        </h1>
        <p
          className="font-telemetry text-[11px] uppercase tracking-widest mt-1"
          style={{ color: "var(--console-muted)" }}
        >
          Install · License · Activate AI scenario plugins
        </p>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="rounded h-[200px] animate-pulse"
              style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
            />
          ))}
        </div>
      ) : scenarios.length === 0 ? (
        <div
          className="rounded p-10 flex flex-col items-center justify-center text-center gap-3"
          style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
        >
          <div className="h-12 w-12 rounded flex items-center justify-center" style={{ background: "var(--console-raised)" }}>
            <Cpu className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
          </div>
          <p className="font-telemetry text-[12px] font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
            No plugins available
          </p>
          <p className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
            Start a scenario plugin so it registers in the marketplace.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {scenarios.map((s) => (
            <PluginCard
              key={s.id}
              scenario={s}
              pending={toggleMut.isPending}
              onOpen={onOpen}
              onToggle={onToggle}
              onRequestLicense={onRequestLicense}
            />
          ))}
        </div>
      )}

      {reqScenario && (
        <RequestLicenseModal
          scenario={reqScenario}
          data={reqData}
          loading={reqMut.isPending}
          onClose={() => {
            setReqScenario(null);
            setReqData(null);
          }}
        />
      )}
    </div>
  );
};

export default Marketplace;
