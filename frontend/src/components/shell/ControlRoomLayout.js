import React from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { LiveEventProvider } from "../nvr/LiveEventDrawer";
import LeftRail from "./LeftRail";
import TopHeader from "./TopHeader";
import StatusBar from "./StatusBar";
import AlarmDock from "./AlarmDock";
import CameraTree from "./CameraTree";
import { useUiPrefs } from "../../hooks";

const TITLES = [
  { match: (p) => p === "/", title: "Live" },
  { match: (p) => p.startsWith("/playback"), title: "Playback" },
  { match: (p) => p.startsWith("/cameras"), title: "Cameras" },
  { match: (p) => p.startsWith("/events"), title: "Events" },
  { match: (p) => p.startsWith("/bookmarks"), title: "Bookmarks" },
  { match: (p) => p.startsWith("/settings"), title: "Settings" },
];

export default function ControlRoomLayout() {
  const location = useLocation();
  const [prefs, setPrefs] = useUiPrefs();

  const title = TITLES.find((t) => t.match(location.pathname))?.title || "GVD Pro";
  const showTree =
    location.pathname === "/" || location.pathname.startsWith("/playback");

  const fillFirstEmpty = (cam) => {
    const tiles = Array.isArray(prefs.wallTiles) ? prefs.wallTiles.slice() : [];
    const count = prefs.wallLayout || 4;
    while (tiles.length < count) tiles.push(null);
    const idx = tiles.findIndex((t) => !t);
    if (idx === -1) tiles[0] = cam.id;
    else tiles[idx] = cam.id;
    setPrefs({ wallTiles: tiles });
  };

  return (
    <LiveEventProvider>
      <div className="console-root h-screen w-screen flex flex-col overflow-hidden">
        <TopHeader title={title} />
        <div className="flex-1 min-h-0 flex">
          <LeftRail />
          <div className="flex-1 min-w-0">
            <PanelGroup direction="horizontal">
              {showTree && (
                <>
                  <Panel defaultSize={18} minSize={12} maxSize={30} order={1}>
                    <CameraTree onActivate={fillFirstEmpty} />
                  </Panel>
                  <PanelResizeHandle
                    className="w-px hover:w-1 transition-all"
                    style={{ background: "var(--console-border)" }}
                  />
                </>
              )}
              <Panel order={2}>
                <main className="h-full overflow-auto">
                  <Outlet />
                </main>
              </Panel>
            </PanelGroup>
          </div>
          <AlarmDock
            open={prefs.dockOpen}
            onToggle={() => setPrefs({ dockOpen: !prefs.dockOpen })}
          />
        </div>
        <StatusBar />
      </div>
    </LiveEventProvider>
  );
}
