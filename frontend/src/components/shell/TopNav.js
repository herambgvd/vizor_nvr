import React from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutGrid, Camera, Bell, Settings, Search,
} from "lucide-react";
import { cn } from "../../lib/utils";

// Primary app navigation — a focused video-analytics surface: Live monitoring,
// Cameras, Events, AI scenarios, Settings. (Playback / Bookmarks / Recordings are
// NVR-domain features and live in the dedicated NVR product, not here.)
const ITEMS = [
  { to: "/", label: "Live", icon: LayoutGrid, end: true },
  { to: "/cameras", label: "Cameras", icon: Camera },
  { to: "/events", label: "Events", icon: Bell },
  { to: "/ai", label: "AI", icon: Search },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function TopNav() {
  const items = ITEMS;

  return (
    <nav className="flex items-center gap-1">
      {items.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          title={label}
          className={({ isActive }) =>
            cn(
              "relative flex items-center gap-1.5 px-2.5 h-8 rounded-md text-[12px] transition-colors",
              isActive
                ? "bg-[var(--console-hover)] text-[var(--console-text)]"
                : "text-[var(--console-muted)] hover:bg-[var(--console-hover)] hover:text-[var(--console-text)]",
            )
          }
        >
          {({ isActive }) => (
            <>
              <Icon className="h-[15px] w-[15px]" />
              <span className="leading-none hidden lg:block">{label}</span>
              {isActive && (
                <span
                  className="absolute bottom-0 left-2 right-2 h-[2px] rounded-t"
                  style={{ background: "var(--console-accent)" }}
                />
              )}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
