import React from "react";

const ScenarioSettingsTab = ({ scenario }) => (
  <div className="p-6 max-w-[980px] space-y-4">
    <div>
      <h2 className="font-telemetry text-[14px] font-semibold uppercase tracking-wide text-zinc-100">
        Scenario Settings
      </h2>
      <p className="font-telemetry text-[11px] text-zinc-500 mt-1">
        Manifest-driven plugin metadata exposed by the NVR core.
      </p>
    </div>
    <div
      className="rounded p-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-[12px]"
      style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
    >
      <div><span className="text-zinc-500">Slug:</span> <span className="text-zinc-200">{scenario.slug}</span></div>
      <div><span className="text-zinc-500">Version:</span> <span className="text-zinc-200">{scenario.version || "-"}</span></div>
      <div><span className="text-zinc-500">Licensed:</span> <span className="text-zinc-200">{scenario.licensed ? "yes" : "no"}</span></div>
      <div><span className="text-zinc-500">Enabled:</span> <span className="text-zinc-200">{scenario.enabled ? "yes" : "no"}</span></div>
      <div className="md:col-span-2"><span className="text-zinc-500">Service:</span> <span className="text-zinc-200">{scenario.service_url || "-"}</span></div>
    </div>
    <pre
      className="rounded p-4 overflow-auto text-[12px] leading-relaxed text-zinc-300"
      style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
    >
{JSON.stringify({
  capabilities: scenario.capabilities || [],
  tabs: scenario.tabs || scenario.module_tabs || [],
  event_types: scenario.event_types || [],
  proxy_routes: scenario.proxy_routes || [],
  resource_requirements: scenario.resource_requirements || {},
}, null, 2)}
    </pre>
  </div>
);

export default ScenarioSettingsTab;

