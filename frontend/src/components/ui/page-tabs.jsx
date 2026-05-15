// =============================================================================
// PageTabs — underline tab row used across Storage / Settings / Notifications
// =============================================================================
// Dark-theme teal accent, consistent typography. Accepts a `tabs` array of
// { id, label, icon? } plus controlled value + onValueChange. Pure
// presentation — caller renders the active panel content.
// =============================================================================

import React from "react";
import { cn } from "../../lib/utils";

const PageTabs = ({ tabs = [], value, onValueChange, className }) => (
  <div
    className={cn(
      "flex gap-1 border-b border-border overflow-x-auto",
      className,
    )}
    role="tablist"
  >
    {tabs.map((t) => {
      const Icon = t.icon;
      const active = value === t.id;
      return (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={active}
          onClick={() => onValueChange?.(t.id)}
          className={cn(
            "relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors",
            "outline-none focus:outline-none focus-visible:outline-none ring-0 focus:ring-0 focus-visible:ring-0",
            active
              ? "text-white"
              : "text-muted-foreground hover:text-zinc-200",
          )}
        >
          {Icon && <Icon className="h-4 w-4" />}
          {t.label}
          {active && (
            <span className="absolute left-2 right-2 -bottom-px h-[2px] rounded-full bg-gradient-to-r from-teal-400 to-blue-400" />
          )}
        </button>
      );
    })}
  </div>
);

export default PageTabs;
export { PageTabs };
