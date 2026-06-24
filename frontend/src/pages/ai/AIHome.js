// =============================================================================
// AI · Home — landing grid of registered AI scenario plugins.
// =============================================================================
// Each card opens the generic ScenarioWorkspace at /ai/{slug}. The card shows
// registered/licensed/enabled state so plugin outages never look like NVR loss.
// =============================================================================

import React from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ScanFace, HardHat, Cpu, ChevronRight, Search, Store } from "lucide-react";
import { getScenarios } from "../../api/ai";

const ICONS = { "scan-face": ScanFace, "hard-hat": HardHat, search: Search };

const ScenarioCard = ({ scenario, onOpen }) => {
  const Icon = ICONS[scenario.icon] || Cpu;
  const cap = scenario.camera_limit || 0;
  const used = scenario.active_camera_count || 0;
  const disabled = !scenario.registered;
  return (
    <button
      type="button"
      onClick={() => onOpen(scenario)}
      disabled={disabled}
      className="group text-left rounded p-4 flex flex-col gap-3 transition-colors"
      style={{
        background: "var(--console-panel)",
        border: "1px solid var(--console-border)",
        opacity: disabled ? 0.55 : 1,
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
              className="font-telemetry text-[10px] uppercase tracking-widest"
              style={{ color: "var(--console-muted)" }}
            >
              {scenario.category || scenario.slug}
            </div>
          </div>
        </div>
        <ChevronRight
          className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
          style={{ color: "var(--console-muted)" }}
        />
      </div>

      <p
        className="font-telemetry text-[11px] leading-relaxed line-clamp-3"
        style={{ color: "var(--console-muted)" }}
      >
        {scenario.description || "Plugin scenario"}
      </p>

      <div className="flex flex-wrap gap-1.5">
        <span className="rounded px-2 py-1 text-[10px] uppercase tracking-wide font-telemetry border border-white/10">
          {scenario.registered ? "Registered" : "Missing"}
        </span>
        <span className="rounded px-2 py-1 text-[10px] uppercase tracking-wide font-telemetry border border-white/10">
          {scenario.licensed ? "Licensed" : "Unlicensed"}
        </span>
        <span className="rounded px-2 py-1 text-[10px] uppercase tracking-wide font-telemetry border border-white/10">
          {scenario.enabled ? "Enabled" : "Disabled"}
        </span>
      </div>

      <div
        className="flex items-center justify-between mt-auto pt-2"
        style={{ borderTop: "1px solid var(--console-border)" }}
      >
        <span
          className="font-telemetry text-[10px] uppercase tracking-widest"
          style={{ color: "var(--console-muted)" }}
        >
          {scenario.version ? `v${scenario.version}` : "Cameras"}
        </span>
        <span className="font-telemetry text-[11px]" style={{ color: "var(--console-text)" }}>
          {scenario.version ? `${used}${cap > 0 ? ` / ${cap}` : ""} cams` : `${used}${cap > 0 ? ` / ${cap}` : ""}`}
        </span>
      </div>
    </button>
  );
};

const AIHome = () => {
  const navigate = useNavigate();
  const { data: scenarios = [], isLoading } = useQuery({
    queryKey: ["ai-scenarios", "active"],
    queryFn: getScenarios,
  });

  const visibleScenarios = scenarios.filter((s) => s.service_url || (s.proxy_routes || []).length > 0);
  const open = (s) => navigate(`/ai/${s.slug}`);

  return (
    <div className="p-6 w-full">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1
            className="font-telemetry text-[16px] font-semibold uppercase tracking-wide"
            style={{ color: "var(--console-text)" }}
          >
            AI Scenarios
          </h1>
          <p
            className="font-telemetry text-[11px] uppercase tracking-widest mt-1"
            style={{ color: "var(--console-muted)" }}
          >
            Plugin-based intelligence scenarios
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate("/ai/marketplace")}
          className="inline-flex items-center gap-1.5 font-telemetry text-[11px] uppercase tracking-wide px-3 py-1.5 rounded border transition-colors"
          style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-accent)" }}
        >
          <Store className="h-3.5 w-3.5" /> Marketplace
        </button>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="rounded h-[180px] animate-pulse"
              style={{
                background: "var(--console-panel)",
                border: "1px solid var(--console-border)",
              }}
            />
          ))}
        </div>
      ) : visibleScenarios.length === 0 ? (
        <div
          className="rounded p-10 flex flex-col items-center justify-center text-center gap-3"
          style={{
            background: "var(--console-panel)",
            border: "1px solid var(--console-border)",
          }}
        >
          <div
            className="h-12 w-12 rounded flex items-center justify-center"
            style={{ background: "var(--console-raised)" }}
          >
            <Cpu className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
          </div>
          <p
            className="font-telemetry text-[12px] font-semibold uppercase tracking-wide"
            style={{ color: "var(--console-text)" }}
          >
            No AI scenario plugins registered
          </p>
          <p
            className="font-telemetry text-[11px]"
            style={{ color: "var(--console-muted)" }}
          >
            License and enable a plugin in the Marketplace to get started.
          </p>
          <button
            type="button"
            onClick={() => navigate("/ai/marketplace")}
            className="inline-flex items-center gap-1.5 font-telemetry text-[11px] uppercase tracking-wide px-3 py-1.5 rounded mt-1"
            style={{ background: "var(--console-accent)", color: "#000" }}
          >
            <Store className="h-3.5 w-3.5" /> Open Marketplace
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {visibleScenarios.map((s) => (
            <ScenarioCard key={s.id} scenario={s} onOpen={open} />
          ))}
        </div>
      )}
    </div>
  );
};

export default AIHome;
