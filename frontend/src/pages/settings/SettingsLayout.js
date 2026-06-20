// =============================================================================
// SettingsLayout — shell for all /settings sub-pages
// =============================================================================
// Configuration / Notifications / Resources / Storage / Audit Log all
// live as siblings in the left nav. No nested dropdown in the top bar.
// =============================================================================

import React from "react";
import { Outlet, Link, useLocation } from "react-router-dom";
import {
  Settings as SettingsIcon,
  BellRing,
  Activity,
  HardDrive,
  Shield,
  KeyRound,
  Clock,
  Network,
  BookOpen,
  Plug,
  Users,
  Cpu,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { useAuth } from "../../context/AuthContext";

const BASE_NAV = [
  { path: "configuration", label: "Configuration", icon: SettingsIcon },
  { path: "notifications", label: "Notifications", icon: BellRing },
  { path: "resources", label: "Resources", icon: Activity },
  { path: "storage", label: "Storage", icon: HardDrive },
];

const SettingsLayout = () => {
  const location = useLocation();
  const { isAdmin } = useAuth();
  const NAV = isAdmin
    ? [
        ...BASE_NAV,
        { path: "users", label: "Users", icon: Users },
        { path: "time", label: "Time & NTP", icon: Clock },
        { path: "network", label: "Network", icon: Network },
        { path: "integrations", label: "Integrations", icon: Plug },
        { path: "ai-scenarios", label: "AI Scenarios", icon: Cpu },
        { path: "license", label: "License", icon: KeyRound },
        { path: "audit", label: "Audit Log", icon: Shield },
        { path: "__api_docs__", label: "API Docs", icon: BookOpen, external: "/api/docs" },
      ]
    : BASE_NAV;
  const isActive = (item) =>
    item.absolute
      ? location.pathname === item.path
      : location.pathname.endsWith(`/${item.path}`);

  return (
    <div
      className="flex flex-col h-full overflow-hidden"
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
            Settings
          </span>
        </div>
        <div className="flex-1" />
      </div>

      <div className="flex-1 min-h-0 flex">
        {/* Desktop left sidebar nav */}
        <aside
          className="w-[200px] flex-shrink-0 border-r hidden md:flex flex-col py-1"
          style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
        >
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = isActive(item);
            if (item.external) {
              return (
                <a
                  key={item.path}
                  href={item.external}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="relative flex items-center gap-2 px-4 py-2 font-telemetry text-xs transition-colors hover:bg-white/5"
                  style={{ color: "var(--console-muted)" }}
                >
                  <Icon className="h-3.5 w-3.5 flex-shrink-0" />
                  {item.label}
                </a>
              );
            }
            return (
              <Link
                key={item.path}
                to={item.path}
                className="relative flex items-center gap-2 px-4 py-2 font-telemetry text-xs transition-colors"
                style={
                  active
                    ? {
                        background: "var(--console-raised)",
                        color: "var(--console-text)",
                      }
                    : { color: "var(--console-muted)" }
                }
                onMouseEnter={(e) => {
                  if (!active) e.currentTarget.style.background = "rgba(255,255,255,0.04)";
                }}
                onMouseLeave={(e) => {
                  if (!active) e.currentTarget.style.background = "transparent";
                }}
              >
                {active && (
                  <span
                    className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r-full"
                    style={{ background: "var(--console-accent)" }}
                  />
                )}
                <Icon className="h-3.5 w-3.5 flex-shrink-0" />
                {item.label}
              </Link>
            );
          })}
        </aside>

        {/* Mobile horizontal nav */}
        <div
          className="md:hidden w-full flex-shrink-0 border-b overflow-x-auto"
          style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
        >
          <div className="flex gap-1 px-2 py-1.5">
            {NAV.map((item) => {
              const Icon = item.icon;
              const active = isActive(item);
              if (item.external) {
                return (
                  <a
                    key={item.path}
                    href={item.external}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded font-telemetry text-xs whitespace-nowrap transition-colors hover:bg-white/5"
                    style={{ color: "var(--console-muted)" }}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {item.label}
                  </a>
                );
              }
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded font-telemetry text-xs whitespace-nowrap transition-colors"
                  style={
                    active
                      ? {
                          background: "var(--console-raised)",
                          color: "var(--console-text)",
                          borderBottom: `2px solid var(--console-accent)`,
                        }
                      : { color: "var(--console-muted)" }
                  }
                >
                  <Icon className="h-3.5 w-3.5" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        </div>

        <main className="flex-1 min-w-0 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default SettingsLayout;
