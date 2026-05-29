import React, { useMemo, useState, useEffect, useRef } from "react";
import { LayoutGrid, Grid3x3, Eraser, Play, Pause } from "lucide-react";
import { useCamerasQuery, useUiPrefs } from "../../hooks";
import {
  LAYOUTS,
  slotCount,
  gridStyle,
  fitLayout,
  tourPages,
} from "../../lib/videoWall";
import VideoTile from "./VideoTile";

const TOUR_DWELLS = [5, 10, 15, 30];

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

  // ── Tour: auto-cycle the wall through every camera in dwell-second steps ──
  const [tourOn, setTourOn] = useState(false);
  const [tourSec, setTourSec] = useState(10);
  const tourIdxRef = useRef(0);

  // Online cameras first. The joined signature lets the tour effect ignore the
  // periodic camera refetch unless the set/order actually changed (otherwise
  // the tour would reset to page 1 every 10s).
  const orderedIds = useMemo(
    () =>
      [...cameras]
        .sort((a, b) => {
          const ao = a.status === "online" ? 0 : 1;
          const bo = b.status === "online" ? 0 : 1;
          return ao - bo;
        })
        .map((c) => c.id),
    [cameras],
  );
  const orderedSig = orderedIds.join(",");

  useEffect(() => {
    if (!tourOn) return undefined;
    const pages = tourPages(orderedIds, count);
    if (pages.length === 0) return undefined;
    if (tourIdxRef.current >= pages.length) tourIdxRef.current = 0;
    setPrefs({ wallTiles: pages[tourIdxRef.current] });
    if (pages.length === 1) return undefined; // single page → nothing to cycle
    const timer = setInterval(() => {
      tourIdxRef.current = (tourIdxRef.current + 1) % pages.length;
      setPrefs({ wallTiles: pages[tourIdxRef.current] });
    }, tourSec * 1000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tourOn, tourSec, count, orderedSig]);

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
          onClick={() => setTourOn((v) => !v)}
          disabled={cameras.length === 0}
          title={tourOn ? "Stop camera tour" : "Auto-cycle through all cameras"}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded font-telemetry uppercase tracking-wide transition-opacity disabled:opacity-40"
          style={
            tourOn
              ? { background: "var(--console-accent)", color: "#06231f" }
              : {
                  background: "transparent",
                  border: "1px solid var(--console-border)",
                  color: "var(--console-muted)",
                }
          }
        >
          {tourOn ? (
            <Pause className="h-3.5 w-3.5" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
          Tour
        </button>
        {tourOn && (
          <select
            value={tourSec}
            onChange={(e) => setTourSec(Number(e.target.value))}
            title="Dwell time per page"
            className="h-[26px] px-1 text-xs rounded font-telemetry outline-none"
            style={{
              background: "var(--console-panel)",
              border: "1px solid var(--console-border)",
              color: "var(--console-muted)",
            }}
          >
            {TOUR_DWELLS.map((s) => (
              <option key={s} value={s}>
                {s}s
              </option>
            ))}
          </select>
        )}

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
