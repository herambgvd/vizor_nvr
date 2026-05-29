import React, { useMemo, useState } from "react";
import { LayoutGrid, Grid3x3, Eraser } from "lucide-react";
import { useCamerasQuery, useUiPrefs } from "../../hooks";
import { LAYOUTS, slotCount, gridStyle, fitLayout } from "../../lib/videoWall";
import VideoTile from "./VideoTile";

export default function VideoWall() {
  const { data: cameras = [] } = useCamerasQuery();
  const [prefs, setPrefs] = useUiPrefs();
  // Store the maximized camera by id (not a snapshot) so the maximized tile
  // tracks live status/recording updates from the cameras query.
  const [maximizedId, setMaximizedId] = useState(null);

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

  // One-shot: auto-size the grid and populate every camera in a single click,
  // so the user doesn't have to drag cameras one at a time. Online cameras are
  // placed first so the most useful tiles are visible without scrolling.
  const fillAll = () => {
    const ordered = [...cameras].sort((a, b) => {
      const ao = a.status === "online" ? 0 : 1;
      const bo = b.status === "online" ? 0 : 1;
      return ao - bo;
    });
    const ids = ordered.map((c) => c.id);
    const layout = fitLayout(ids.length);
    const next = ids.slice(0, layout);
    while (next.length < layout) next.push(null);
    setPrefs({ wallLayout: layout, wallTiles: next });
  };

  const clearAll = () => {
    setPrefs({ wallTiles: Array(count).fill(null) });
  };

  const maximized = maximizedId ? byId.get(maximizedId) : null;
  if (maximizedId && maximized) {
    return (
      <div className="h-full p-1">
        <VideoTile
          camera={maximized}
          onMaximize={() => setMaximizedId(null)}
          onClear={() => setMaximizedId(null)}
        />
      </div>
    );
  }
  // The maximized camera disappeared (deleted/removed) — fall back to the grid.

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

        <div className="flex-1" />

        <button
          onClick={fillAll}
          disabled={cameras.length === 0}
          title="Auto-size grid and show all cameras"
          className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded font-telemetry uppercase tracking-wide transition-opacity disabled:opacity-40"
          style={{ background: "var(--console-accent)", color: "#06231f" }}
        >
          <Grid3x3 className="h-3.5 w-3.5" />
          Fill all
        </button>
        <button
          onClick={clearAll}
          title="Clear all tiles"
          className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded font-telemetry uppercase tracking-wide border transition-colors hover:bg-white/5"
          style={{ background: "transparent", borderColor: "var(--console-border)", color: "var(--console-muted)" }}
        >
          <Eraser className="h-3.5 w-3.5" />
          Clear
        </button>
      </div>

      <div className="flex-1 min-h-0 p-1">
        <div className="grid gap-1 h-full" style={gridStyle(count)}>
          {tiles.map((cid, slot) => (
            <VideoTile
              key={slot}
              camera={cid ? byId.get(cid) : null}
              onAssign={(id) => assign(slot, id)}
              onClear={() => clear(slot)}
              onMaximize={(cam) => setMaximizedId(cam.id)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
