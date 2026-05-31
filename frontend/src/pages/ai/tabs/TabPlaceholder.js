// =============================================================================
// AI · tab placeholder — shared shell for scenario tabs not yet implemented.
// =============================================================================
// The generic ScenarioWorkspace lazy-loads one component per module tab. Until
// each tab's real UI lands, it renders this consistent, on-brand placeholder so
// navigation, routing and the shell are fully wired and testable.
// =============================================================================

import React from "react";
import { Construction } from "lucide-react";

const TabPlaceholder = ({ title, description }) => (
  <div className="p-6">
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
        <Construction className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
      </div>
      <p
        className="font-telemetry text-[12px] font-semibold uppercase tracking-wide"
        style={{ color: "var(--console-text)" }}
      >
        {title}
      </p>
      {description && (
        <p
          className="font-telemetry text-[11px] max-w-[420px]"
          style={{ color: "var(--console-muted)" }}
        >
          {description}
        </p>
      )}
    </div>
  </div>
);

export default TabPlaceholder;
