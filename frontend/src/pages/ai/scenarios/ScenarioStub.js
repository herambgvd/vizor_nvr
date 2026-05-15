// =============================================================================
// ScenarioStub — temporary placeholder for tabs not yet built
// =============================================================================

import React from "react";
import { useOutletContext, useLocation } from "react-router-dom";
import { Construction } from "lucide-react";

const ScenarioStub = () => {
  const ctx = useOutletContext();
  const loc = useLocation();
  const tab = loc.pathname.split("/").filter(Boolean)[3] || "";
  return (
    <div className="p-6 md:p-10 max-w-2xl mx-auto text-center">
      <Construction className="h-10 w-10 text-muted-foreground/40 mx-auto mb-3" />
      <h2 className="text-lg font-semibold">
        {ctx?.scenario?.name} · {tab}
      </h2>
      <p className="text-sm text-muted-foreground mt-2">
        This section is part of the active build plan. Phase 2 wires Live,
        Events, and Analytics. Per-scenario specialized tabs follow.
      </p>
    </div>
  );
};

export default ScenarioStub;
