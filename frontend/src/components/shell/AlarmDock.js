import React from "react";
import { useNavigate } from "react-router-dom";
import { Bell, ChevronRight } from "lucide-react";
import { useLiveEvents } from "../nvr/LiveEventDrawer";

const sevColor = (sev) => {
  if (sev === "critical") return "var(--console-rec)";
  if (sev === "warning" || sev === "alarm") return "var(--console-alarm)";
  return "var(--console-accent-blue)";
};

export default function AlarmDock({ open, onToggle }) {
  const navigate = useNavigate();
  const { events = [] } = useLiveEvents();

  if (!open) {
    return (
      <button
        onClick={onToggle}
        className="w-7 flex items-center justify-center console-panel border-l text-zinc-400 hover:text-white"
        style={{ borderColor: "var(--console-border)" }}
        title="Show alarms"
      >
        <Bell className="h-4 w-4" />
      </button>
    );
  }

  return (
    <aside
      className="flex flex-col console-panel border-l"
      style={{ width: "var(--console-dock-w)", borderColor: "var(--console-border)" }}
    >
      <div className="flex items-center gap-2 px-3 h-9 border-b" style={{ borderColor: "var(--console-border)" }}>
        <Bell className="h-4 w-4 text-amber-400" />
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-300">Live Alarms</span>
        <button onClick={onToggle} className="ml-auto text-zinc-500 hover:text-white">
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {events.length === 0 && (
          <p className="px-3 py-4 text-xs text-zinc-600">No recent alarms.</p>
        )}
        {events.map((ev, i) => (
          <button
            key={ev.id || i}
            onClick={() => ev.camera_id && navigate(`/playback?camera=${ev.camera_id}`)}
            className="w-full text-left px-3 py-2 border-b hover:bg-white/5"
            style={{ borderColor: "var(--console-border)" }}
          >
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ background: sevColor(ev.severity) }} />
              <span className="text-xs font-medium text-zinc-200 truncate">{ev.title || ev.event_type}</span>
            </div>
            <p className="text-[11px] text-zinc-500 truncate mt-0.5">{ev.description}</p>
          </button>
        ))}
      </div>
    </aside>
  );
}
