// =============================================================================
// Settings · AI Scenarios — /settings/ai-scenarios
// =============================================================================
// Page shell around AIScenariosSection so operators have a place to enable /
// disable licensed AI scenarios (FRS / PPE / suspect-search). Licensing comes
// from the signed .lic file; the section itself only renders scenarios the
// license unlocks.
// =============================================================================

import React from "react";
import AIScenariosSection from "./AIScenariosSection";

const AIScenariosPage = () => (
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
          AI Scenarios
        </span>
      </div>
    </div>

    <div className="flex-1 min-h-0 overflow-y-auto p-4 md:p-6">
      <AIScenariosSection />
    </div>
  </div>
);

export default AIScenariosPage;
