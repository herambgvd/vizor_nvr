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
        { path: "time", label: "Time & NTP", icon: Clock },
        { path: "network", label: "Network", icon: Network },
        { path: "license", label: "License", icon: KeyRound },
        { path: "audit", label: "Audit Log", icon: Shield },
      ]
    : BASE_NAV;
  const isActive = (sub) => location.pathname.endsWith(`/${sub}`);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <header className="flex-shrink-0 flex items-center gap-3 px-4 md:px-6 h-14 border-b border-border bg-card/30">
        <SettingsIcon className="h-5 w-5" />
        <h1 className="text-base md:text-lg font-semibold">Settings</h1>
      </header>

      <div className="flex-1 min-h-0 flex">
        <aside className="w-[220px] flex-shrink-0 border-r border-border bg-card/30 hidden md:flex flex-col py-2">
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.path);
            return (
              <Link
                key={item.path}
                to={item.path}
                className={cn(
                  "relative flex items-center gap-2 px-4 py-2.5 text-sm transition-colors",
                  active
                    ? "text-white bg-card"
                    : "text-zinc-400 hover:text-white hover:bg-card/60",
                )}
              >
                {active && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r-full bg-gradient-to-b from-teal-400 to-blue-400" />
                )}
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </aside>

        {/* Mobile horizontal nav */}
        <div className="md:hidden flex-shrink-0 border-b border-border overflow-x-auto">
          <div className="flex gap-1 px-2 py-1.5">
            {NAV.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.path);
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={cn(
                    "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium whitespace-nowrap",
                    active
                      ? "bg-card text-white"
                      : "text-zinc-400 hover:text-white hover:bg-card/60",
                  )}
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
