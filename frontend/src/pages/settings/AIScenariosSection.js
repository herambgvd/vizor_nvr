// =============================================================================
// Settings · License · AI Scenarios
// =============================================================================
// One card per AI scenario (FRS, PPE, …). Shows license state, camera cap +
// usage, and an enable toggle. Licensing comes from the signed .lic file
// (features[]); operators can only enable a scenario the license unlocks.
// =============================================================================

import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ScanFace, HardHat, Cpu, Lock, Check, KeyRound, Copy, X } from "lucide-react";
import { toast } from "sonner";
import { getScenarios, toggleScenario } from "../../api/ai";
import { requestScenarioLicense } from "../../api/license";
import { friendlyError } from "../../lib/utils";

const ICONS = { "scan-face": ScanFace, "hard-hat": HardHat };

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

const ScenarioCard = ({ scenario, onToggle, onRequestLicense, pending }) => {
  const Icon = ICONS[scenario.icon] || Cpu;
  const cap = scenario.camera_limit || 0;
  const used = scenario.active_camera_count || 0;
  return (
    <div
      className="rounded p-4 flex flex-col gap-3"
      style={{
        background: "var(--console-panel)",
        border: "1px solid var(--console-border)",
        opacity: scenario.licensed ? 1 : 0.6,
      }}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2.5">
          <div
            className="h-9 w-9 rounded flex items-center justify-center"
            style={{ background: "var(--console-raised)" }}
          >
            <Icon className="h-4.5 w-4.5" style={{ color: "var(--console-accent)" }} />
          </div>
          <div>
            <div
              className="font-telemetry text-[12px] font-semibold uppercase tracking-wide"
              style={{ color: "var(--console-text)" }}
            >
              {scenario.name}
            </div>
            <div
              className="font-telemetry text-[10px] uppercase tracking-widest flex items-center gap-1.5"
              style={{ color: "var(--console-muted)" }}
            >
              {scenario.slug}
              {scenario.version && <span style={{ opacity: 0.7 }}>v{scenario.version}</span>}
              {scenario.registered === false && (
                <span style={{ color: "var(--console-rec)" }}>· not installed</span>
              )}
            </div>
          </div>
        </div>
        {!scenario.registered ? (
          <span
            className="inline-flex items-center gap-1 font-telemetry text-[10px] px-1.5 py-0.5 rounded border"
            style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}
          >
            <Lock className="h-3 w-3" /> {scenario.licensed ? "Awaiting install" : "Not installed"}
          </span>
        ) : scenario.licensed ? (
          <Toggle
            checked={scenario.enabled}
            disabled={pending}
            onChange={(v) => onToggle(scenario, v)}
          />
        ) : (
          <span
            className="inline-flex items-center gap-1 font-telemetry text-[10px] px-1.5 py-0.5 rounded border"
            style={{
              background: "var(--console-raised)",
              borderColor: "var(--console-border)",
              color: "var(--console-muted)",
            }}
          >
            <Lock className="h-3 w-3" /> Not licensed
          </span>
        )}
      </div>

      <p className="font-telemetry text-[11px] leading-relaxed" style={{ color: "var(--console-muted)" }}>
        {scenario.description}
      </p>

      {!scenario.licensed && (
        <button
          type="button"
          onClick={() => onRequestLicense(scenario)}
          className="inline-flex items-center gap-1.5 self-start font-telemetry text-[10px] uppercase tracking-wide px-2 py-1 rounded border transition-colors"
          style={{
            background: "var(--console-raised)",
            borderColor: "var(--console-border)",
            color: "var(--console-accent)",
          }}
        >
          <KeyRound className="h-3 w-3" /> Request License
        </button>
      )}

      <div
        className="flex items-center justify-between mt-auto pt-2"
        style={{ borderTop: "1px solid var(--console-border)" }}
      >
        <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          Cameras
        </span>
        <span className="font-telemetry text-[11px]" style={{ color: "var(--console-text)" }}>
          {used}{cap > 0 ? ` / ${cap}` : ""}
          {scenario.enabled && (
            <Check className="inline h-3 w-3 ml-1.5" style={{ color: "var(--console-accent)" }} />
          )}
        </span>
      </div>
    </div>
  );
};

// Modal: shows the portable license-request blob for one scenario. The operator
// copies it and emails it to the vendor, who signs a fingerprint-bound .lic.
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

const AIScenariosSection = () => {
  const qc = useQueryClient();
  const [reqScenario, setReqScenario] = useState(null);
  const [reqData, setReqData] = useState(null);
  const { data: scenarios = [], isLoading } = useQuery({
    queryKey: ["ai-scenarios"],
    queryFn: getScenarios,
  });

  const reqMut = useMutation({
    mutationFn: (slug) => requestScenarioLicense(slug),
    onSuccess: (data) => setReqData(data),
    onError: (e) => {
      toast.error(friendlyError(e, "Couldn't generate the license request."));
      setReqScenario(null);
    },
  });

  const onRequestLicense = (scenario) => {
    setReqScenario(scenario);
    setReqData(null);
    reqMut.mutate(scenario.slug);
  };

  const mut = useMutation({
    mutationFn: ({ id, enabled }) => toggleScenario(id, enabled),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ["ai-scenarios"] });
      toast.success(`Scenario ${vars.enabled ? "enabled" : "disabled"}`);
    },
    onError: (e) => {
      // Licensing/availability rejections come back as a clean 400 detail
      // string ("This scenario isn't included in your license"); surface those
      // directly, otherwise fall back to a generic operator-safe message.
      const detail = e?.response?.data?.detail;
      const status = e?.response?.status;
      toast.error(
        status === 400 && typeof detail === "string" && detail
          ? detail
          : friendlyError(e, "Couldn't update the scenario."),
      );
    },
  });

  const onToggle = (scenario, enabled) =>
    mut.mutate({ id: scenario.id, enabled });

  if (isLoading) {
    return (
      <p
        className="font-telemetry text-[11px]"
        style={{ color: "var(--console-muted)" }}
      >
        Loading scenarios…
      </p>
    );
  }
  if (!scenarios.length) {
    return (
      <div
        className="rounded p-6 text-center"
        style={{
          background: "var(--console-panel)",
          border: "1px solid var(--console-border)",
        }}
      >
        <Cpu
          className="h-6 w-6 mx-auto mb-2"
          style={{ color: "var(--console-muted)" }}
        />
        <p
          className="font-telemetry text-xs font-semibold uppercase tracking-wide mb-1"
          style={{ color: "var(--console-text)" }}
        >
          No AI scenarios available
        </p>
        <p
          className="font-telemetry text-[11px]"
          style={{ color: "var(--console-muted)" }}
        >
          AI scenarios are unlocked by your license. Contact your provider to add
          facial recognition, PPE detection, or other AI features.
        </p>
      </div>
    );
  }

  return (
    <div>
      <p
        className="font-telemetry text-[10px] uppercase tracking-widest mb-3"
        style={{ color: "var(--console-muted)" }}
      >
        AI Scenarios
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {scenarios.map((s) => (
          <ScenarioCard
            key={s.id}
            scenario={s}
            pending={mut.isPending}
            onToggle={onToggle}
            onRequestLicense={onRequestLicense}
          />
        ))}
      </div>
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

export default AIScenariosSection;
