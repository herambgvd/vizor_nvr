import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, ChevronDown, Search, Video } from "lucide-react";
import { useCamerasQuery } from "../../hooks";
import { getCameraGroups } from "../../api/cameras";
import { cn } from "../../lib/utils";

function StatusDot({ status }) {
  const color =
    status === "online" ? "var(--console-online)" : "var(--console-offline)";
  return (
    <span
      className="inline-block h-2 w-2 rounded-full flex-shrink-0"
      style={{ background: color }}
    />
  );
}

export default function CameraTree({ onActivate }) {
  const { data: cameras = [] } = useCamerasQuery();
  const { data: groups = [] } = useQuery({
    queryKey: ["camera-groups"],
    queryFn: getCameraGroups,
    staleTime: 30000,
  });
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState({});

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return cameras;
    return cameras.filter((c) => (c.name || "").toLowerCase().includes(q));
  }, [cameras, query]);

  const buckets = useMemo(() => {
    const byGroup = new Map();
    for (const g of groups) byGroup.set(g.id, { group: g, cams: [] });
    byGroup.set("__ungrouped__", { group: { id: "__ungrouped__", name: "Ungrouped" }, cams: [] });
    for (const c of filtered) {
      const gid = c.group_id && byGroup.has(c.group_id) ? c.group_id : "__ungrouped__";
      byGroup.get(gid).cams.push(c);
    }
    return Array.from(byGroup.values()).filter((b) => b.cams.length > 0);
  }, [groups, filtered]);

  const toggle = (id) => setCollapsed((p) => ({ ...p, [id]: !p[id] }));

  const onDragStart = (e, cam) => {
    e.dataTransfer.setData("text/nvr-camera-id", cam.id);
    e.dataTransfer.effectAllowed = "copy";
  };

  return (
    <div
      className="flex flex-col h-full console-panel border-r"
      style={{ borderColor: "var(--console-border)" }}
    >
      <div className="p-2 border-b" style={{ borderColor: "var(--console-border)" }}>
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search cameras…"
            className="w-full pl-7 pr-2 py-1.5 text-xs rounded bg-black/30 border text-zinc-200 placeholder:text-zinc-600 outline-none focus:border-teal-500"
            style={{ borderColor: "var(--console-border)" }}
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {buckets.map(({ group, cams }) => {
          const isCollapsed = collapsed[group.id];
          return (
            <div key={group.id}>
              <button
                onClick={() => toggle(group.id)}
                className="w-full flex items-center gap-1 px-2 py-1.5 text-[11px] uppercase tracking-wider text-zinc-500 hover:text-zinc-300"
              >
                {isCollapsed ? (
                  <ChevronRight className="h-3 w-3" />
                ) : (
                  <ChevronDown className="h-3 w-3" />
                )}
                {group.name}
                <span className="ml-auto text-zinc-600">{cams.length}</span>
              </button>
              {!isCollapsed &&
                cams.map((cam) => (
                  <div
                    key={cam.id}
                    draggable
                    onDragStart={(e) => onDragStart(e, cam)}
                    onDoubleClick={() => onActivate?.(cam)}
                    className={cn(
                      "flex items-center gap-2 pl-6 pr-2 py-1.5 text-xs cursor-grab",
                      "text-zinc-300 hover:bg-white/5",
                    )}
                    title={cam.name}
                  >
                    <StatusDot status={cam.status} />
                    <Video className="h-3.5 w-3.5 text-zinc-500 flex-shrink-0" />
                    <span className="truncate">{cam.name}</span>
                  </div>
                ))}
            </div>
          );
        })}
        {buckets.length === 0 && (
          <p className="px-3 py-4 text-xs text-zinc-600">No cameras.</p>
        )}
      </div>
    </div>
  );
}
