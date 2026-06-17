import React from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutGrid, Play, Camera, Bell, Bookmark, Settings, Search,
} from "lucide-react";
import { cn } from "../../lib/utils";

const ITEMS = [
  { to: "/", label: "Live", icon: LayoutGrid, end: true },
  { to: "/playback", label: "Playback", icon: Play },
  { to: "/cameras", label: "Cameras", icon: Camera },
  { to: "/events", label: "Events", icon: Bell },
  { to: "/ai", label: "AI", icon: Search },
  { to: "/bookmarks", label: "Bookmarks", icon: Bookmark },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function LeftRail() {
  return (
    <nav
      className="flex flex-col items-center py-2 gap-1 console-panel border-r"
      style={{ width: "var(--console-rail-w)", borderColor: "var(--console-border)" }}
    >
      {ITEMS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          title={label}
          className={({ isActive }) =>
            cn(
              "relative flex flex-col items-center justify-center w-11 h-12 rounded-md text-[9px] gap-1 transition-colors",
              isActive
                ? "text-white bg-white/5"
                : "text-zinc-500 hover:text-zinc-200 hover:bg-white/5",
            )
          }
        >
          {({ isActive }) => (
            <>
              <Icon className="h-[18px] w-[18px]" />
              <span className="leading-none">{label}</span>
              {isActive && (
                <span
                  className="absolute left-0 h-8 w-[2px] rounded-r"
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
