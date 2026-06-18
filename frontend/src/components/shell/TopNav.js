import React from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutGrid, Play, Camera, Bell, Bookmark, Settings, Search,
} from "lucide-react";
import { cn } from "../../lib/utils";

// Primary app navigation — horizontal, lives in the TopHeader so the whole
// left gutter is freed for page content. (Replaces the old vertical LeftRail.)
const ITEMS = [
  { to: "/", label: "Live", icon: LayoutGrid, end: true },
  { to: "/playback", label: "Playback", icon: Play },
  { to: "/cameras", label: "Cameras", icon: Camera },
  { to: "/events", label: "Events", icon: Bell },
  { to: "/ai", label: "AI", icon: Search },
  { to: "/bookmarks", label: "Bookmarks", icon: Bookmark },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function TopNav() {
  return (
    <nav className="flex items-center gap-1">
      {ITEMS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          title={label}
          className={({ isActive }) =>
            cn(
              "relative flex items-center gap-1.5 px-2.5 h-8 rounded-md text-[12px] transition-colors",
              isActive
                ? "text-white bg-white/5"
                : "text-zinc-500 hover:text-zinc-200 hover:bg-white/5",
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
