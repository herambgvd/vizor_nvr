import React, { useMemo, useState } from "react";
import { LayoutGrid } from "lucide-react";
import { useCamerasQuery, useUiPrefs } from "../../hooks";
import { LAYOUTS, slotCount, gridStyle } from "../../lib/videoWall";
import VideoTile from "./VideoTile";

export default function VideoWall() {
  const { data: cameras = [] } = useCamerasQuery();
  const [prefs, setPrefs] = useUiPrefs();
  const [maximized, setMaximized] = useState(null);

  const count = slotCount(prefs.wallLayout);
  const byId = useMemo(() => {
    const m = new Map();
    for (const c of cameras) m.set(c.id, c);
    return m;
  }, [cameras]);

  const tiles = useMemo(() => {
    const t = Array.isArray(prefs.wallTiles) ? prefs.wallTiles.slice(0, count) : [];
    while (t.length < count) t.push(null);
    return t;
  }, [prefs.wallTiles, count]);

  const setTiles = (next) => setPrefs({ wallTiles: next });

  const assign = (slot, cameraId) => {
    const next = tiles.slice();
    next[slot] = cameraId;
    setTiles(next);
  };
  const clear = (slot) => {
    const next = tiles.slice();
    next[slot] = null;
    setTiles(next);
  };
  const setLayout = (n) => {
    const next = tiles.slice(0, n);
    while (next.length < n) next.push(null);
    setPrefs({ wallLayout: n, wallTiles: next });
  };

  if (maximized) {
    return (
      <div className="h-full p-1">
        <VideoTile
          camera={maximized}
          onMaximize={() => setMaximized(null)}
          onClear={() => setMaximized(null)}
        />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-1 px-2 h-9 border-b console-panel" style={{ borderColor: "var(--console-border)" }}>
        <LayoutGrid className="h-4 w-4 text-zinc-500 mr-1" />
        {LAYOUTS.map((n) => (
          <button
            key={n}
            onClick={() => setLayout(n)}
            className="px-2 py-1 text-xs rounded font-telemetry"
            style={{
              background: count === n ? "var(--console-accent)" : "transparent",
              color: count === n ? "#06231f" : "var(--console-muted)",
            }}
          >
            {n}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 p-1">
        <div className="grid gap-1 h-full" style={gridStyle(count)}>
          {tiles.map((cid, slot) => (
            <VideoTile
              key={slot}
              camera={cid ? byId.get(cid) : null}
              onAssign={(id) => assign(slot, id)}
              onClear={() => clear(slot)}
              onMaximize={(cam) => setMaximized(cam)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
