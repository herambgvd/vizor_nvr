import React from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { LiveEventProvider } from "../nvr/LiveEventDrawer";
import ErrorBoundary from "../ErrorBoundary";
import TopHeader from "./TopHeader";
import StatusBar from "./StatusBar";
import AlarmDock from "./AlarmDock";
import CameraTree from "./CameraTree";
import { useUiPrefs } from "../../hooks";

// Localized fallback for a crashed routed page. Keeps nav + alarm dock +
// status bar alive; offers a retry that re-renders the route in place.
const RouteErrorFallback = (error, reset) => (
  <div
    className="h-full flex flex-col items-center justify-center gap-3 text-center px-6"
    style={{ color: "var(--console-muted)" }}
  >
    <AlertTriangle className="h-10 w-10" style={{ color: "var(--console-alarm)" }} />
    <p className="text-sm font-semibold" style={{ color: "var(--console-text)" }}>
      This view ran into a problem
    </p>
    {error?.message && (
      <pre
        className="text-[11px] max-w-md overflow-auto rounded p-2 border"
        style={{
          background: "var(--console-raised)",
          borderColor: "var(--console-border)",
          color: "var(--console-muted)",
        }}
      >
        {error.message}
      </pre>
    )}
    <button
      onClick={reset}
      className="inline-flex items-center gap-1.5 h-8 px-3 rounded text-xs font-semibold"
      style={{ background: "var(--console-accent)", color: "#06231f" }}
    >
      <RefreshCw className="h-3.5 w-3.5" /> Retry
    </button>
    <p className="text-[11px]">Or pick another view from the navigation.</p>
  </div>
);

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

  const title = TITLES.find((t) => t.match(location.pathname))?.title || "Vizor";
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

  const togglePlaybackCamera = (cam) => {
    const set = Array.isArray(prefs.playbackCameras) ? prefs.playbackCameras.slice() : [];
    const idx = set.indexOf(cam.id);
    if (idx === -1) set.push(cam.id);
    else set.splice(idx, 1);
    setPrefs({ playbackCameras: set });
  };

  const onTreeActivate = location.pathname.startsWith("/playback")
    ? togglePlaybackCamera
    : fillFirstEmpty;

  return (
    <LiveEventProvider>
      <div className="console-root h-screen w-screen flex flex-col overflow-hidden">
        <TopHeader title={title} />
        <div className="flex-1 min-h-0 flex">
          <div className="flex-1 min-w-0">
            <PanelGroup direction="horizontal">
              {showTree && (
                <>
                  <Panel defaultSize={18} minSize={12} maxSize={30} order={1}>
                    <CameraTree onActivate={onTreeActivate} />
                  </Panel>
                  <PanelResizeHandle
                    className="w-px hover:w-1 transition-all"
                    style={{ background: "var(--console-border)" }}
                  />
                </>
              )}
              <Panel order={2}>
                <main className="h-full overflow-auto">
                  {/* Localized boundary: a single page crash keeps the nav,
                      alarm dock and status bar alive. resetKey=pathname so
                      navigating away clears the error automatically. */}
                  <ErrorBoundary
                    resetKey={location.pathname}
                    fallback={RouteErrorFallback}
                  >
                    <Outlet />
                  </ErrorBoundary>
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
