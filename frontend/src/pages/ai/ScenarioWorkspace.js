// =============================================================================
// AI · ScenarioWorkspace — generic shell for any AI scenario.
// =============================================================================
// Reads :slug from the route, resolves the scenario from the catalog, and
// renders a tab bar driven by scenario.module_tabs. Each tab lazy-loads a
// component from a PER-SCENARIO registry (SCENARIO_TABS) keyed by slug → tab.
// This keeps every scenario's data tabs fully isolated under
// ./scenarios/<slug>/, so editing one scenario's UI can never affect another.
// The video core (Cameras / Live) stays shared from ./tabs/. The active tab is
// reflected in the URL (/ai/{slug}/{tab}) so tabs are deep-linkable and
// back/forward works.
// =============================================================================

import React, { lazy, Suspense, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ScanFace,
  HardHat,
  Cpu,
  Video,
  PlaySquare,
  Bell,
  Users,
  FolderTree,
  CalendarClock,
  BarChart3,
  Search,
  Briefcase,
  SlidersHorizontal,
  ArrowLeftRight,
  Route,
  Info,
  Car,
  ListChecks,
} from "lucide-react";
import { getScenarioBySlug } from "../../api/ai";

const SCENARIO_ICONS = { "scan-face": ScanFace, "hard-hat": HardHat };

// Tab metadata — label + icon. Order on screen follows scenario.module_tabs.
const TAB_META = {
  cameras: { label: "Cameras", icon: Video },
  live: { label: "Live", icon: PlaySquare },
  events: { label: "Events", icon: Bell },
  persons: { label: "Persons", icon: Users },
  groups: { label: "Groups", icon: FolderTree },
  recognize: { label: "Recognize", icon: ScanFace },
  ppe_detect: { label: "Detect", icon: HardHat },
  plates: { label: "Plates", icon: Car },
  lists: { label: "Lists", icon: ListChecks },
  investigate: { label: "Investigate", icon: Search },
  transit: { label: "Transit", icon: ArrowLeftRight },
  tour: { label: "Tour", icon: Route },
  attendance: { label: "Attendance", icon: CalendarClock },
  reports: { label: "Reports", icon: BarChart3 },
  search: { label: "Search", icon: Search },
  jobs: { label: "Jobs", icon: Briefcase },
  settings: { label: "Settings", icon: SlidersHorizontal },
  info: { label: "Info", icon: Info },
};

// Video core stays SHARED for every scenario — pure infra (config-schema +
// WebRTC player driven), so all scenarios point cameras/live at ./tabs/.
const sharedCameras = () => import("./tabs/CamerasTab");
const sharedLive = () => import("./tabs/LiveTab");

// Per-scenario tab registry: slug → { tabKey: lazy(component) }. Every data tab
// lives under ./scenarios/<slug>/ and is fully isolated. Keys must match the
// scenario's module_tabs values. Unknown slugs / tabs simply don't resolve and
// are dropped from the tab bar (see `tabs` memo below).
const SCENARIO_TABS = {
  frs: {
    cameras: lazy(sharedCameras),
    live: lazy(sharedLive),
    events: lazy(() => import("./scenarios/frs/EventsTab")),
    groups: lazy(() => import("./scenarios/frs/GroupsTab")),
    persons: lazy(() => import("./scenarios/frs/PersonsTab")),
    recognize: lazy(() => import("./scenarios/frs/RecognizeTab")),
    investigate: lazy(() => import("./scenarios/frs/InvestigateTab")),
    transit: lazy(() => import("./scenarios/frs/TransitTab")),
    attendance: lazy(() => import("./scenarios/frs/AttendanceTab")),
    tour: lazy(() => import("./scenarios/frs/TourTab")),
    reports: lazy(() => import("./scenarios/frs/ReportsTab")),
    settings: lazy(() => import("./scenarios/frs/SettingsTab")),
  },
  ppe: {
    cameras: lazy(sharedCameras),
    live: lazy(sharedLive),
    ppe_detect: lazy(() => import("./scenarios/ppe/DetectTab")),
    events: lazy(() => import("./scenarios/ppe/EventsTab")),
    reports: lazy(() => import("./scenarios/ppe/ReportsTab")),
    settings: lazy(() => import("./scenarios/ppe/SettingsTab")),
  },
  anpr: {
    cameras: lazy(sharedCameras),
    live: lazy(sharedLive),
    plates: lazy(() => import("./scenarios/anpr/PlatesTab")),
    lists: lazy(() => import("./scenarios/anpr/ListsTab")),
    events: lazy(() => import("./scenarios/anpr/EventsTab")),
    reports: lazy(() => import("./scenarios/anpr/ReportsTab")),
    settings: lazy(() => import("./scenarios/anpr/SettingsTab")),
  },
  "suspect-search": {
    cameras: lazy(sharedCameras),
    search: lazy(() => import("./scenarios/suspect-search/SearchTab")),
    jobs: lazy(() => import("./scenarios/suspect-search/JobsTab")),
    // Suspect Search's manifest uses "info" for its settings/info surface.
    info: lazy(() => import("./scenarios/suspect-search/SettingsTab")),
    settings: lazy(() => import("./scenarios/suspect-search/SettingsTab")),
  },
};

const TabSpinner = () => (
  <div className="flex items-center justify-center py-16">
    <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-teal-400" />
  </div>
);

const ScenarioWorkspace = () => {
  const { slug, tab } = useParams();
  const navigate = useNavigate();

  const {
    data: scenario,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["ai-scenario", "slug", slug],
    queryFn: () => getScenarioBySlug(slug),
    enabled: !!slug,
  });

  // Resolve this scenario's tab registry by slug. Unknown slugs fall back to an
  // empty registry so only the tabs that actually resolve are shown.
  const registry = SCENARIO_TABS[slug] || {};

  // Tabs that exist both in this scenario's manifest and its registry.
  const tabs = useMemo(() => {
    const declared = scenario?.tabs || scenario?.module_tabs || [];
    return declared.filter((t) => registry[t]);
  }, [scenario, registry]);

  const activeTab = tabs.includes(tab) ? tab : tabs[0];
  const ScenarioIcon = SCENARIO_ICONS[scenario?.icon] || Cpu;

  const selectTab = (t) => navigate(`/ai/${slug}/${t}`);

  if (isLoading) {
    return (
      <div className="p-6">
        <TabSpinner />
      </div>
    );
  }

  if (isError || !scenario) {
    return (
      <div className="p-6 max-w-[1200px] mx-auto">
        <div
          className="rounded p-10 flex flex-col items-center justify-center text-center gap-3"
          style={{
            background: "var(--console-panel)",
            border: "1px solid var(--console-border)",
          }}
        >
          <Cpu className="h-8 w-8" style={{ color: "var(--console-muted)" }} />
          <p
            className="font-telemetry text-[12px] font-semibold uppercase tracking-wide"
            style={{ color: "var(--console-text)" }}
          >
            Scenario not found
          </p>
          <p
            className="font-telemetry text-[11px]"
            style={{ color: "var(--console-muted)" }}
          >
            "{slug}" is not licensed or does not exist
          </p>
        </div>
      </div>
    );
  }

  const ActiveComponent = activeTab ? registry[activeTab] : null;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div
        className="px-6 pt-5 pb-0"
        style={{ borderBottom: "1px solid var(--console-border)" }}
      >
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => navigate("/ai")}
            title="Back to AI features"
            className="h-9 w-9 rounded flex items-center justify-center shrink-0 transition-colors"
            style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)", color: "var(--console-muted)" }}
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div
            className="h-10 w-10 rounded flex items-center justify-center"
            style={{ background: "var(--console-raised)" }}
          >
            <ScenarioIcon className="h-5 w-5" style={{ color: "var(--console-accent)" }} />
          </div>
          <div>
            <h1
              className="font-telemetry text-[15px] font-semibold uppercase tracking-wide"
              style={{ color: "var(--console-text)" }}
            >
              {scenario.name}
            </h1>
            <p
              className="font-telemetry text-[10px] uppercase tracking-widest"
              style={{ color: "var(--console-muted)" }}
            >
              {scenario.category || scenario.slug}
            </p>
          </div>
        </div>

        {/* Tab bar */}
        <nav className="flex items-center gap-1 mt-4 -mb-px overflow-x-auto">
          {tabs.map((t) => {
            const meta = TAB_META[t] || { label: t, icon: Cpu };
            const TabIcon = meta.icon;
            const active = t === activeTab;
            return (
              <button
                key={t}
                type="button"
                onClick={() => selectTab(t)}
                className="relative inline-flex items-center gap-2 px-3 h-9 text-[12px] font-medium font-telemetry uppercase tracking-wide transition-colors whitespace-nowrap"
                style={{
                  color: active
                    ? "var(--console-text)"
                    : "var(--console-muted)",
                }}
              >
                <TabIcon className="h-[14px] w-[14px]" />
                {meta.label}
                {active && (
                  <span
                    className="absolute left-0 right-0 -bottom-px h-[2px] rounded-full"
                    style={{ background: "var(--console-accent)" }}
                  />
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Tab content — tabs manage their own internal scroll, so this stays
          overflow-hidden to avoid a second page-level scrollbar. */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {ActiveComponent ? (
          <Suspense fallback={<TabSpinner />}>
            <ActiveComponent scenario={scenario} />
          </Suspense>
        ) : (
          <div className="p-6">
            <p
              className="font-telemetry text-[11px] uppercase tracking-widest"
              style={{ color: "var(--console-muted)" }}
            >
              No tabs configured for this scenario
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default ScenarioWorkspace;
