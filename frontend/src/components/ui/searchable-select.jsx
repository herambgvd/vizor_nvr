// =============================================================================
// SearchableSelect — console-themed combobox with type-to-filter.
// Built on Radix Popover + plain React state (no extra deps). Drop-in
// replacement for a native <select> when the option list is long
// (timezones, action types, …).
// =============================================================================

import * as React from "react";
import { Check, ChevronsUpDown, Search } from "lucide-react";

import { Popover, PopoverTrigger, PopoverContent } from "./popover";

// Normalize "foo" | { value, label } → { value, label }
const normalize = (opt) =>
  typeof opt === "string" || typeof opt === "number"
    ? { value: String(opt), label: String(opt) }
    : { value: String(opt.value), label: opt.label ?? String(opt.value) };

const SearchableSelect = ({
  value,
  onChange,
  options = [],
  placeholder = "Select…",
  searchPlaceholder = "Search…",
  emptyText = "No matches",
  disabled = false,
  className = "",
}) => {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [activeIdx, setActiveIdx] = React.useState(0);
  const listRef = React.useRef(null);

  const items = React.useMemo(() => options.map(normalize), [options]);
  const selected = items.find((o) => o.value === String(value));

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((o) => o.label.toLowerCase().includes(q));
  }, [items, query]);

  // Reset transient state whenever the popover opens.
  React.useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIdx(0);
    }
  }, [open]);

  // Keep the highlighted row in view.
  React.useEffect(() => {
    const node = listRef.current?.children?.[activeIdx];
    if (node) node.scrollIntoView({ block: "nearest" });
  }, [activeIdx]);

  const commit = (opt) => {
    if (!opt) return;
    onChange?.(opt.value);
    setOpen(false);
  };

  const onKeyDown = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      commit(filtered[activeIdx]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-expanded={open}
          className={`w-full inline-flex items-center justify-between rounded font-telemetry text-xs h-[30px] px-2 border outline-none focus:ring-1 disabled:opacity-50 ${className}`}
          style={{
            background: "var(--console-raised)",
            border: "1px solid var(--console-border)",
            color: selected ? "var(--console-text)" : "var(--console-muted)",
            "--tw-ring-color": "var(--console-accent)",
          }}
        >
          <span className="truncate">{selected ? selected.label : placeholder}</span>
          <ChevronsUpDown className="h-3.5 w-3.5 ml-2 flex-shrink-0 opacity-60" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={4}
        onOpenAutoFocus={(e) => {
          // Focus the search input rather than the first row.
          e.preventDefault();
        }}
        className="p-0 w-[var(--radix-popover-trigger-width)] border-0"
        style={{
          background: "var(--console-raised)",
          border: "1px solid var(--console-border)",
          color: "var(--console-text)",
        }}
      >
        <div className="flex flex-col overflow-hidden rounded">
          <div
            className="flex items-center gap-2 px-2 border-b"
            style={{ borderColor: "var(--console-border)" }}
          >
            <Search className="h-3.5 w-3.5 flex-shrink-0 opacity-50" />
            <input
              autoFocus
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActiveIdx(0);
              }}
              onKeyDown={onKeyDown}
              placeholder={searchPlaceholder}
              className="flex h-[32px] w-full bg-transparent py-2 font-telemetry text-xs outline-none placeholder:opacity-60"
              style={{ color: "var(--console-text)" }}
            />
          </div>
          <div ref={listRef} className="max-h-[260px] overflow-y-auto p-1">
            {filtered.length === 0 ? (
              <div
                className="py-4 text-center font-telemetry text-[11px]"
                style={{ color: "var(--console-muted)" }}
              >
                {emptyText}
              </div>
            ) : (
              filtered.map((opt, idx) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => commit(opt)}
                  onMouseEnter={() => setActiveIdx(idx)}
                  className="w-full relative flex cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-1.5 font-telemetry text-xs outline-none text-left"
                  style={{
                    color: "var(--console-text)",
                    background: idx === activeIdx ? "rgba(255,255,255,0.08)" : "transparent",
                  }}
                >
                  <Check
                    className="h-3.5 w-3.5 flex-shrink-0"
                    style={{
                      color: "var(--console-accent)",
                      opacity: opt.value === String(value) ? 1 : 0,
                    }}
                  />
                  <span className="truncate">{opt.label}</span>
                </button>
              ))
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default SearchableSelect;
export { SearchableSelect };
