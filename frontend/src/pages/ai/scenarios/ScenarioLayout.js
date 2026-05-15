// =============================================================================
// ScenarioLayout — wrapper for /ai/modules/:slug/*
// =============================================================================
// Reads scenario metadata (incl. module_tabs) from backend, renders the
// header + PageTabs nav, hosts <Outlet/> for sub-routes.
// =============================================================================

import React from "react";
import {
  Outlet,
  useParams,
  useLocation,
  useNavigate,
  Link,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Sparkles, RefreshCw } from "lucide-react";
import apiClient from "../../../api/client";
import { Button } from "../../../components/ui/button";
import PageTabs from "../../../components/ui/page-tabs";

const TAB_META = {
  live: "Live",
  events: "Events",
  analytics: "Analytics",
  persons: "Persons",
  attendance: "Attendance",
  investigate: "Investigate",
  groups: "Groups",
  reports: "Reports",
};

const fetchScenario = async (slug) => {
  const r = await apiClient.get(`/ai/scenarios/${slug}`);
  return r.data;
};

const ScenarioLayout = () => {
  const params = useParams();
  const location = useLocation();
  const navigate = useNavigate();

  // Explicit routes like /ai/modules/frs don't bind ":slug" — fall back to
  // the third URL segment (/ai/modules/<slug>).
  const slug =
    params.slug || location.pathname.split("/").filter(Boolean)[2] || "";

  const { data: scenario, isLoading } = useQuery({
    queryKey: ["ai-scenario", slug],
    queryFn: () => fetchScenario(slug),
    enabled: !!slug,
  });

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <RefreshCw className="h-6 w-6 text-muted-foreground animate-spin" />
      </div>
    );
  }

  if (!scenario) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3">
        <p className="text-sm text-muted-foreground">Scenario not found</p>
        <Button variant="outline" size="sm" onClick={() => navigate("/ai/modules")}>
          Back to AI Modules
        </Button>
      </div>
    );
  }

  const tabs = (scenario.module_tabs || ["live", "events", "analytics"]).map(
    (id) => ({ id, label: TAB_META[id] || id }),
  );

  // Detect active tab from URL path /ai/modules/:slug/:tab
  const segments = location.pathname.split("/").filter(Boolean);
  const activeTab = segments[3] || tabs[0]?.id;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <header className="flex-shrink-0 flex items-center gap-3 px-4 md:px-6 h-14 border-b border-border bg-card/30">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 -ml-2"
          onClick={() => navigate("/ai/modules")}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <Sparkles className="h-5 w-5 text-teal-300" />
        <h1 className="text-base md:text-lg font-semibold truncate">
          {scenario.name}
        </h1>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground border border-white/10 rounded px-1.5 py-0.5">
          {scenario.tier}
        </span>
      </header>

      <div className="flex-shrink-0 px-4 md:px-6 border-b border-border bg-card/20">
        <PageTabs
          tabs={tabs}
          value={activeTab}
          onValueChange={(v) => navigate(`/ai/modules/${slug}/${v}`)}
        />
      </div>

      <main className="flex-1 min-h-0 overflow-y-auto">
        <Outlet context={{ scenario }} />
      </main>
    </div>
  );
};

export default ScenarioLayout;
