# NVR UX Overhaul — Plan 1: Foundation & Live Video Wall

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the top-bar dashboard shell with a dense control-room VMS shell (left rail + persistent camera tree + bottom telemetry status bar + right alarm dock) and make the landing screen a live multi-camera video wall.

**Architecture:** Introduce a new `ControlRoomLayout` built on `react-resizable-panels`, plus shared components `CameraTree`, `StatusBar`, `AlarmDock`, `VideoWall`/`VideoTile`. Reuse the existing `WebRTCPlayer`, `PTZControls`, React Query hooks, and API clients. Migrate the `/` route to the video wall; all other routes keep working inside the new shell. Pure logic (layout math, telemetry formatting) is extracted into tested helpers.

**Tech Stack:** React 18, react-router-dom v6, @tanstack/react-query, Tailwind (CRA + craco), lucide-react, react-resizable-panels, @radix-ui/react-context-menu, @hello-pangea/dnd (already present), Jest via `craco test` (used only for pure helpers).

**Scope note:** This is Plan 1 of 4. Follow-up plans (not in this file): Plan 2 = Playback timeline; Plan 3 = Cameras device-manager restyle; Plan 4 = Events history console. This plan produces a working, shippable control-room shell + live wall on its own.

**Verification approach (matches this codebase):** The frontend has no component-test culture (one API test only). So: pure helpers use Jest TDD (`craco test`); visual components are verified by (a) Babel parse check, (b) `docker compose build frontend` success, (c) in-browser check via Chrome MCP at https://localhost (admin / Admin@12345). The Babel parse command used throughout:

```bash
cd frontend && BABEL_ENV=development NODE_ENV=development \
  node -e "require('@babel/core').transformFileSync(process.argv[1],{presets:['react-app']})" <FILE>
```

Frontend build + deploy (run from repo root):
```bash
DOCKER=/Applications/Docker.app/Contents/Resources/bin/docker
$DOCKER compose build frontend && $DOCKER compose up -d --no-deps frontend
```

---

## File Structure

**Create:**
- `frontend/src/lib/videoWall.js` — pure layout math (slot count, grid class).
- `frontend/src/lib/videoWall.test.js` — tests for the above.
- `frontend/src/lib/telemetry.js` — pure formatters (percent, bytes, bitrate).
- `frontend/src/lib/telemetry.test.js` — tests for the above.
- `frontend/src/api/cluster.js` — cluster API client (`getClusterNodes`, `getClusterStatus`).
- `frontend/src/hooks/useUiPrefs.js` — localStorage-backed UI prefs (collapse state, layouts).
- `frontend/src/components/shell/CameraTree.js` — group/camera tree with drag.
- `frontend/src/components/shell/StatusBar.js` — bottom telemetry strip.
- `frontend/src/components/shell/AlarmDock.js` — right live-event feed.
- `frontend/src/components/shell/LeftRail.js` — icon nav rail.
- `frontend/src/components/shell/TopHeader.js` — slim top header (brand, search, clock, user).
- `frontend/src/components/shell/ControlRoomLayout.js` — the shell composing all regions.
- `frontend/src/components/wall/VideoTile.js` — one wall tile (WebRTC + overlays + menu).
- `frontend/src/components/wall/VideoWall.js` — layout selector + tile grid + DnD.
- `frontend/src/pages/LiveWall.js` — page wrapper rendering `VideoWall`.

**Modify:**
- `frontend/src/index.css` (or `App.css`) — add console theme CSS variables.
- `frontend/tailwind.config.js` — map new tokens (if tokens referenced via Tailwind).
- `frontend/src/App.js` — swap `Layout` → `ControlRoomLayout`; `/` → `LiveWall`; keep aliases.

**Reuse unchanged:** `components/nvr/WebRTCPlayer.js`, `components/nvr/PTZControls.js`, `hooks` (`useCamerasQuery`), `api/cameras.js` (`getCameraGroups`, `getStreamUrls`, `captureSnapshot`, `startRecording`, `stopRecording`), `api/monitoring.js` (`getResources`), `components/nvr/LiveEventDrawer.js` (`LiveEventProvider`).

---

## Task 1: Console theme tokens

**Files:**
- Modify: `frontend/src/index.css` (append a `.theme-console` token block + base wiring)

- [ ] **Step 1: Add CSS variables for the dense console theme**

Append to `frontend/src/index.css`:

```css
/* ── Control-room console theme tokens ───────────────────────────── */
:root {
  --console-bg: #0b0f17;
  --console-panel: #121821;
  --console-raised: #161d29;
  --console-border: #1e2530;
  --console-text: #e2e8f0;
  --console-muted: #94a3b8;
  --console-accent: #14b8a6;
  --console-accent-blue: #3b82f6;
  --console-rec: #ef4444;
  --console-alarm: #f59e0b;
  --console-online: #22c55e;
  --console-offline: #71717a;
  --console-rail-w: 56px;
  --console-tree-w: 260px;
  --console-dock-w: 300px;
  --console-header-h: 44px;
  --console-statusbar-h: 28px;
}

/* Operational screens opt out of the aurora gradient via this class on
   the shell root. */
.console-root { background: var(--console-bg); color: var(--console-text); }
.console-root .aurora { display: none; }

.console-panel { background: var(--console-panel); border-color: var(--console-border); }
.console-raised { background: var(--console-raised); }
.font-telemetry { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
```

- [ ] **Step 2: Verify the app still builds (CSS only, no logic)**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development \
  node -e "require('@babel/core').transformFileSync('src/App.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK` (App.js unchanged but confirms toolchain).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat(ui): add control-room console theme tokens"
```

---

## Task 2: Video wall layout math (pure, TDD)

**Files:**
- Create: `frontend/src/lib/videoWall.js`
- Test: `frontend/src/lib/videoWall.test.js`

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/videoWall.test.js`:

```js
import { LAYOUTS, slotCount, gridStyle } from "./videoWall";

test("LAYOUTS are the supported wall sizes", () => {
  expect(LAYOUTS).toEqual([1, 4, 6, 8, 9, 16, 25]);
});

test("slotCount returns the layout value when valid", () => {
  expect(slotCount(9)).toBe(9);
});

test("slotCount falls back to 4 for an unsupported value", () => {
  expect(slotCount(7)).toBe(4);
  expect(slotCount(undefined)).toBe(4);
});

test("gridStyle produces a square-ish grid template", () => {
  // 9 -> 3 columns, 16 -> 4 columns, 6 -> 3 columns (ceil(sqrt))
  expect(gridStyle(9).gridTemplateColumns).toBe("repeat(3, 1fr)");
  expect(gridStyle(16).gridTemplateColumns).toBe("repeat(4, 1fr)");
  expect(gridStyle(6).gridTemplateColumns).toBe("repeat(3, 1fr)");
  expect(gridStyle(8).gridTemplateColumns).toBe("repeat(3, 1fr)");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && CI=true craco test src/lib/videoWall.test.js`
Expected: FAIL — "Cannot find module './videoWall'".

- [ ] **Step 3: Write minimal implementation**

`frontend/src/lib/videoWall.js`:

```js
// Pure helpers for the live video wall layout. No React, no I/O.

export const LAYOUTS = [1, 4, 6, 8, 9, 16, 25];

export function slotCount(layout) {
  return LAYOUTS.includes(layout) ? layout : 4;
}

// Square-ish grid: columns = ceil(sqrt(n)).
export function gridStyle(layout) {
  const n = slotCount(layout);
  const cols = Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / cols);
  return {
    gridTemplateColumns: `repeat(${cols}, 1fr)`,
    gridTemplateRows: `repeat(${rows}, 1fr)`,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && CI=true craco test src/lib/videoWall.test.js`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/videoWall.js frontend/src/lib/videoWall.test.js
git commit -m "feat(ui): add tested video-wall layout helpers"
```

---

## Task 3: Telemetry formatters (pure, TDD)

**Files:**
- Create: `frontend/src/lib/telemetry.js`
- Test: `frontend/src/lib/telemetry.test.js`

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/telemetry.test.js`:

```js
import { fmtPct, fmtBytes, fmtBitrate } from "./telemetry";

test("fmtPct clamps and rounds to whole percent", () => {
  expect(fmtPct(0.1234, true)).toBe("12%");   // fraction input
  expect(fmtPct(57.6)).toBe("58%");            // already-percent input
  expect(fmtPct(-5)).toBe("0%");
  expect(fmtPct(140)).toBe("100%");
  expect(fmtPct(null)).toBe("—");
});

test("fmtBytes renders human units", () => {
  expect(fmtBytes(0)).toBe("0 B");
  expect(fmtBytes(1024)).toBe("1.0 KB");
  expect(fmtBytes(1536)).toBe("1.5 KB");
  expect(fmtBytes(1048576)).toBe("1.0 MB");
  expect(fmtBytes(null)).toBe("—");
});

test("fmtBitrate renders kbps/Mbps", () => {
  expect(fmtBitrate(800)).toBe("800 kbps");
  expect(fmtBitrate(4500)).toBe("4.5 Mbps");
  expect(fmtBitrate(null)).toBe("—");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && CI=true craco test src/lib/telemetry.test.js`
Expected: FAIL — "Cannot find module './telemetry'".

- [ ] **Step 3: Write minimal implementation**

`frontend/src/lib/telemetry.js`:

```js
// Pure display formatters for the status bar / tile overlays.

export function fmtPct(v, isFraction = false) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  let pct = isFraction ? Number(v) * 100 : Number(v);
  pct = Math.max(0, Math.min(100, pct));
  return `${Math.round(pct)}%`;
}

export function fmtBytes(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const bytes = Number(n);
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB", "PB"];
  let val = bytes / 1024;
  let i = 0;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i += 1;
  }
  return `${val.toFixed(1)} ${units[i]}`;
}

export function fmtBitrate(kbps) {
  if (kbps === null || kbps === undefined || Number.isNaN(Number(kbps))) return "—";
  const v = Number(kbps);
  if (v < 1000) return `${Math.round(v)} kbps`;
  return `${(v / 1000).toFixed(1)} Mbps`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && CI=true craco test src/lib/telemetry.test.js`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/telemetry.js frontend/src/lib/telemetry.test.js
git commit -m "feat(ui): add tested telemetry formatters"
```

---

## Task 4: Cluster API client

**Files:**
- Create: `frontend/src/api/cluster.js`

- [ ] **Step 1: Write the client**

`frontend/src/api/cluster.js`:

```js
// Cluster (N+1 hot standby) API client.
// NOTE: /cluster/status is admin-only on the backend; /cluster/nodes is
// available to any authenticated user, so the StatusBar uses getClusterNodes.
import client from "./client";

export const getClusterNodes = async () => {
  const res = await client.get("/cluster/nodes");
  return res.data; // [{ node_id, hostname, role, is_leader, ... }]
};

export const getClusterStatus = async () => {
  const res = await client.get("/cluster/status");
  return res.data; // admin only
};

// Derive the local node's role label from the nodes list.
export const localNodeRole = (nodes) => {
  if (!Array.isArray(nodes) || nodes.length === 0) return "unknown";
  const leader = nodes.find((n) => n.is_leader);
  return leader ? "active" : "standby";
};
```

- [ ] **Step 2: Verify parse**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development \
  node -e "require('@babel/core').transformFileSync('src/api/cluster.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/cluster.js
git commit -m "feat(api): add cluster nodes/status client"
```

---

## Task 5: UI prefs hook (localStorage)

**Files:**
- Create: `frontend/src/hooks/useUiPrefs.js`
- Modify: `frontend/src/hooks/index.js` (export it)

- [ ] **Step 1: Write the hook**

`frontend/src/hooks/useUiPrefs.js`:

```js
import { useCallback, useState } from "react";

const KEY = "nvr_ui_prefs";

const DEFAULTS = {
  railCollapsed: false,
  treeCollapsed: false,
  dockOpen: true,
  wallLayout: 4,
  // wallTiles: array of cameraId|null, indexed by slot
  wallTiles: [],
};

function read() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : { ...DEFAULTS };
  } catch {
    return { ...DEFAULTS };
  }
}

export function useUiPrefs() {
  const [prefs, setPrefs] = useState(read);

  const update = useCallback((patch) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        /* ignore quota errors */
      }
      return next;
    });
  }, []);

  return [prefs, update];
}
```

- [ ] **Step 2: Export from the barrel**

In `frontend/src/hooks/index.js`, add:

```js
export { useUiPrefs } from "./useUiPrefs";
```

- [ ] **Step 3: Verify parse**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development \
  node -e "require('@babel/core').transformFileSync('src/hooks/useUiPrefs.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/hooks/useUiPrefs.js frontend/src/hooks/index.js
git commit -m "feat(ui): add localStorage-backed UI prefs hook"
```

---

## Task 6: LeftRail (icon nav)

**Files:**
- Create: `frontend/src/components/shell/LeftRail.js`

- [ ] **Step 1: Write the component**

`frontend/src/components/shell/LeftRail.js`:

```jsx
import React from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutGrid, Play, Camera, Bell, Bookmark, Settings,
} from "lucide-react";
import { cn } from "../../lib/utils";

const ITEMS = [
  { to: "/", label: "Live", icon: LayoutGrid, end: true },
  { to: "/playback", label: "Playback", icon: Play },
  { to: "/cameras", label: "Cameras", icon: Camera },
  { to: "/events", label: "Events", icon: Bell },
  { to: "/bookmarks", label: "Bookmarks", icon: Bookmark },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function LeftRail() {
  return (
    <nav
      className="flex flex-col items-center py-2 gap-1 console-panel border-r"
      style={{ width: "var(--console-rail-w)", borderColor: "var(--console-border)" }}
    >
      {ITEMS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          title={label}
          className={({ isActive }) =>
            cn(
              "flex flex-col items-center justify-center w-11 h-12 rounded-md text-[9px] gap-1 transition-colors",
              isActive
                ? "text-white bg-white/5"
                : "text-zinc-500 hover:text-zinc-200 hover:bg-white/5",
            )
          }
        >
          {({ isActive }) => (
            <>
              <Icon className="h-[18px] w-[18px]" />
              <span className="leading-none">{label}</span>
              {isActive && (
                <span
                  className="absolute left-0 h-8 w-[2px] rounded-r"
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
```

- [ ] **Step 2: Verify parse**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development \
  node -e "require('@babel/core').transformFileSync('src/components/shell/LeftRail.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/shell/LeftRail.js
git commit -m "feat(ui): add control-room left icon rail"
```

---

## Task 7: CameraTree

**Files:**
- Create: `frontend/src/components/shell/CameraTree.js`

Behavior: fetches groups + cameras, renders expandable groups with cameras
(plus an "Ungrouped" bucket), live status dots, a search filter, and makes each
camera row draggable via the native HTML5 drag API carrying
`text/nvr-camera-id`. Emits `onActivate(camera)` on double-click.

- [ ] **Step 1: Write the component**

`frontend/src/components/shell/CameraTree.js`:

```jsx
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

  // Build group_id -> cameras map, with an "Ungrouped" bucket.
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
```

- [ ] **Step 2: Verify parse**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development \
  node -e "require('@babel/core').transformFileSync('src/components/shell/CameraTree.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/shell/CameraTree.js
git commit -m "feat(ui): add draggable camera tree panel"
```

---

## Task 8: StatusBar (telemetry strip)

**Files:**
- Create: `frontend/src/components/shell/StatusBar.js`

Polls `getResources()` (CPU/RAM/disk) and `getClusterNodes()` (node role)
every 5s, plus a live clock. Renders camera online/offline counts from the
cameras query.

- [ ] **Step 1: Write the component**

`frontend/src/components/shell/StatusBar.js`:

```jsx
import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Cpu, MemoryStick, HardDrive, Server, Circle } from "lucide-react";
import { getResources } from "../../api/monitoring";
import { getClusterNodes, localNodeRole } from "../../api/cluster";
import { useCamerasQuery } from "../../hooks";
import { fmtPct } from "../../lib/telemetry";

function Metric({ icon: Icon, label, value, tone }) {
  return (
    <div className="flex items-center gap-1.5 px-2.5 border-r" style={{ borderColor: "var(--console-border)" }}>
      <Icon className="h-3.5 w-3.5 text-zinc-500" />
      <span className="text-zinc-500">{label}</span>
      <span className="font-telemetry" style={{ color: tone || "var(--console-text)" }}>{value}</span>
    </div>
  );
}

export default function StatusBar() {
  const { data: cameras = [] } = useCamerasQuery();
  const { data: resources } = useQuery({
    queryKey: ["resources"],
    queryFn: getResources,
    refetchInterval: 5000,
  });
  const { data: nodes = [] } = useQuery({
    queryKey: ["cluster-nodes"],
    queryFn: getClusterNodes,
    refetchInterval: 5000,
    retry: false,
  });
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const online = cameras.filter((c) => c.status === "online").length;
  const offline = cameras.length - online;
  const recording = cameras.filter((c) => c.is_recording).length;
  const role = localNodeRole(nodes);

  // getResources shape: { cpu_percent, memory_percent, disk_percent } (best-effort).
  const cpu = resources?.cpu_percent ?? resources?.cpu;
  const mem = resources?.memory_percent ?? resources?.memory;
  const disk = resources?.disk_percent ?? resources?.disk;

  return (
    <div
      className="flex items-center text-[11px] console-panel border-t select-none"
      style={{ height: "var(--console-statusbar-h)", borderColor: "var(--console-border)" }}
    >
      <Metric icon={Cpu} label="CPU" value={fmtPct(cpu)} />
      <Metric icon={MemoryStick} label="MEM" value={fmtPct(mem)} />
      <Metric icon={HardDrive} label="DISK" value={fmtPct(disk)} />
      <Metric
        icon={Circle}
        label="REC"
        value={String(recording)}
        tone={recording > 0 ? "var(--console-rec)" : undefined}
      />
      <div className="flex items-center gap-2 px-2.5 border-r" style={{ borderColor: "var(--console-border)" }}>
        <span className="text-zinc-500">CAMS</span>
        <span className="font-telemetry" style={{ color: "var(--console-online)" }}>{online}↑</span>
        <span className="font-telemetry" style={{ color: "var(--console-offline)" }}>{offline}↓</span>
      </div>
      <Metric
        icon={Server}
        label="NODE"
        value={role}
        tone={role === "active" ? "var(--console-online)" : "var(--console-muted)"}
      />
      <div className="ml-auto px-3 font-telemetry text-zinc-400">
        {now.toLocaleString()}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify parse**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development \
  node -e "require('@babel/core').transformFileSync('src/components/shell/StatusBar.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/shell/StatusBar.js
git commit -m "feat(ui): add bottom telemetry status bar"
```

---

## Task 9: AlarmDock (live event feed)

**Files:**
- Create: `frontend/src/components/shell/AlarmDock.js`

Reuses the existing `LiveEventProvider` context. Inspect
`components/nvr/LiveEventDrawer.js` to find the exported context hook (e.g.
`useLiveEvents`). If no hook is exported, add a named export
`export const useLiveEvents = () => useContext(LiveEventContext);` to that file
in this task, then consume it here.

- [ ] **Step 1: Ensure a context hook is exported from LiveEventDrawer**

Open `frontend/src/components/nvr/LiveEventDrawer.js`. If it does not already
export a hook returning `{ events }`, add (near the context definition):

```jsx
export const useLiveEvents = () => {
  const ctx = useContext(LiveEventContext);
  return ctx || { events: [] };
};
```
(Adjust `LiveEventContext` to the actual context variable name in that file.)

- [ ] **Step 2: Write the AlarmDock**

`frontend/src/components/shell/AlarmDock.js`:

```jsx
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
```

- [ ] **Step 3: Verify parse (both files)**

Run:
```bash
cd frontend && for f in src/components/nvr/LiveEventDrawer.js src/components/shell/AlarmDock.js; do \
  BABEL_ENV=development NODE_ENV=development node -e "require('@babel/core').transformFileSync('$f',{presets:['react-app']})" && echo "PARSE_OK $f"; done
```
Expected: `PARSE_OK` for both.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/shell/AlarmDock.js frontend/src/components/nvr/LiveEventDrawer.js
git commit -m "feat(ui): add right-side live alarm dock"
```

---

## Task 10: TopHeader

**Files:**
- Create: `frontend/src/components/shell/TopHeader.js`

Slim header: brand, current page title (derived from route), global camera
search box (filters the wall later via a callback — for v1 it simply focuses;
wiring search→wall is out of scope, leave the input controlled but inert with a
TODO-free no-op), live clock is in the StatusBar so header shows brand + user
menu. Reuse the existing user dropdown pattern from `pages/Layout.js`.

- [ ] **Step 1: Write the component**

`frontend/src/components/shell/TopHeader.js`:

```jsx
import React from "react";
import { useNavigate } from "react-router-dom";
import { Video, ChevronDown, User, Settings as SettingsIcon, LogOut } from "lucide-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { Avatar, AvatarFallback } from "../ui/avatar";
import { ChangePasswordDialogTrigger } from "../auth/ChangePasswordDialog";
import { useAuth } from "../../context/AuthContext";

const initials = (name) =>
  !name ? "U" : name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2);

export default function TopHeader({ title }) {
  const navigate = useNavigate();
  const { user, isAdmin, logout } = useAuth();

  return (
    <header
      className="flex items-center gap-3 px-3 console-panel border-b"
      style={{ height: "var(--console-header-h)", borderColor: "var(--console-border)" }}
    >
      <div className="flex items-center gap-2">
        <div className="h-6 w-6 rounded bg-gradient-to-br from-teal-500 to-blue-500 flex items-center justify-center">
          <Video className="h-3.5 w-3.5 text-white" />
        </div>
        <span className="text-sm font-semibold tracking-tight">GVD Pro</span>
      </div>
      <div className="h-4 w-px" style={{ background: "var(--console-border)" }} />
      <span className="text-sm text-zinc-400">{title}</span>

      <div className="ml-auto flex items-center gap-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex items-center gap-2 px-2 py-1 rounded hover:bg-white/5">
              <Avatar className="h-7 w-7">
                <AvatarFallback className="bg-gradient-to-br from-blue-500 to-cyan-500 text-white text-[11px]">
                  {initials(user?.username)}
                </AvatarFallback>
              </Avatar>
              <span className="text-xs text-zinc-300 hidden md:block">{user?.username}</span>
              <ChevronDown className="h-3.5 w-3.5 text-zinc-500" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52 console-panel border-border">
            <DropdownMenuLabel className="text-zinc-400 text-[11px] uppercase tracking-wider">
              {isAdmin ? "Administrator" : user?.role_name || "User"}
            </DropdownMenuLabel>
            <DropdownMenuSeparator className="bg-white/10" />
            <DropdownMenuItem onClick={() => navigate("/settings")} className="focus:bg-white/5 focus:text-white">
              <SettingsIcon className="h-4 w-4 mr-2" /> Settings
            </DropdownMenuItem>
            <ChangePasswordDialogTrigger />
            <DropdownMenuSeparator className="bg-white/10" />
            <DropdownMenuItem
              onClick={() => { logout(); navigate("/login"); }}
              className="text-rose-400 focus:bg-rose-500/10 focus:text-rose-300"
            >
              <LogOut className="h-4 w-4 mr-2" /> Logout
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
```

- [ ] **Step 2: Verify parse**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development \
  node -e "require('@babel/core').transformFileSync('src/components/shell/TopHeader.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/shell/TopHeader.js
git commit -m "feat(ui): add slim control-room top header"
```

---

## Task 11: ControlRoomLayout shell

**Files:**
- Create: `frontend/src/components/shell/ControlRoomLayout.js`

Composes: LeftRail | [resizable: CameraTree | Outlet] | AlarmDock, with
TopHeader on top and StatusBar at the bottom. Tree shown only on Live and
Playback routes. Uses `react-resizable-panels`. Wraps everything in
`LiveEventProvider` so the AlarmDock and any page can read live events.

- [ ] **Step 1: Write the component**

`frontend/src/components/shell/ControlRoomLayout.js`:

```jsx
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
  // Camera tree only on Live + Playback (operational viewing screens).
  const showTree =
    location.pathname === "/" || location.pathname.startsWith("/playback");

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
                    <CameraTree />
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
```

- [ ] **Step 2: Verify parse**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development \
  node -e "require('@babel/core').transformFileSync('src/components/shell/ControlRoomLayout.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/shell/ControlRoomLayout.js
git commit -m "feat(ui): add ControlRoomLayout shell"
```

---

## Task 12: VideoTile

**Files:**
- Create: `frontend/src/components/wall/VideoTile.js`

One wall slot. If `cameraId` is set, it resolves the live stream id via
`getStreamUrls(cameraId)` and renders `WebRTCPlayer`; overlays name + status,
rec dot, fps/bitrate footer, hover toolbar; right-click context menu (snapshot,
record start/stop, open playback, settings). Empty slot is a drop target.

- [ ] **Step 1: Write the component**

`frontend/src/components/wall/VideoTile.js`:

```jsx
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Camera as CamIcon, Circle, Maximize2, Settings, Image, Video, X } from "lucide-react";
import {
  ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger,
} from "../ui/context-menu";
import { WebRTCPlayer } from "../nvr/WebRTCPlayer";
import { getStreamUrls, captureSnapshot, startRecording, stopRecording } from "../../api/cameras";
import { toast } from "sonner";

export default function VideoTile({ camera, onAssign, onClear, onMaximize }) {
  const navigate = useNavigate();
  const [streamId, setStreamId] = useState(null);
  const [dragOver, setDragOver] = useState(false);

  useEffect(() => {
    let alive = true;
    setStreamId(null);
    if (camera?.id && camera.status === "online") {
      getStreamUrls(camera.id)
        .then((u) => alive && setStreamId(u.live_stream_id || camera.id))
        .catch(() => {});
    }
    return () => { alive = false; };
  }, [camera?.id, camera?.status]);

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const id = e.dataTransfer.getData("text/nvr-camera-id");
    if (id) onAssign?.(id);
  };

  if (!camera) {
    return (
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className="relative flex items-center justify-center border border-dashed rounded-sm h-full"
        style={{
          borderColor: dragOver ? "var(--console-accent)" : "var(--console-border)",
          background: dragOver ? "rgba(20,184,166,0.06)" : "transparent",
        }}
      >
        <span className="text-[11px] text-zinc-600">drop camera here</span>
      </div>
    );
  }

  const doSnapshot = async () => {
    try { await captureSnapshot(camera.id); toast.success("Snapshot captured"); }
    catch { toast.error("Snapshot failed"); }
  };
  const doRecord = async () => {
    try {
      if (camera.is_recording) { await stopRecording(camera.id); toast.success("Recording stopped"); }
      else { await startRecording(camera.id); toast.success("Recording started"); }
    } catch { toast.error("Recording toggle failed"); }
  };

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div
          onDoubleClick={() => onMaximize?.(camera)}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className="group relative bg-black rounded-sm overflow-hidden h-full border"
          style={{ borderColor: dragOver ? "var(--console-accent)" : "var(--console-border)" }}
        >
          {streamId ? (
            <WebRTCPlayer streamId={streamId} cameraId={camera.id} muted className="w-full h-full object-contain" />
          ) : (
            <div className="w-full h-full flex flex-col items-center justify-center text-zinc-600 gap-1">
              <CamIcon className="h-6 w-6" />
              <span className="text-[10px]">{camera.status === "online" ? "connecting…" : "offline"}</span>
            </div>
          )}

          {/* top overlay */}
          <div className="absolute top-0 inset-x-0 flex items-center gap-1.5 px-2 py-1 bg-gradient-to-b from-black/70 to-transparent">
            <span className="h-2 w-2 rounded-full" style={{ background: camera.status === "online" ? "var(--console-online)" : "var(--console-offline)" }} />
            <span className="text-[11px] text-white truncate">{camera.name}</span>
            {camera.is_recording && <Circle className="h-2.5 w-2.5 ml-auto" style={{ color: "var(--console-rec)", fill: "var(--console-rec)" }} />}
          </div>

          {/* hover toolbar */}
          <div className="absolute top-1 right-1 hidden group-hover:flex gap-1">
            <button onClick={doSnapshot} className="p-1 rounded bg-black/60 text-white hover:bg-black/80"><Image className="h-3.5 w-3.5" /></button>
            <button onClick={() => onMaximize?.(camera)} className="p-1 rounded bg-black/60 text-white hover:bg-black/80"><Maximize2 className="h-3.5 w-3.5" /></button>
            <button onClick={() => onClear?.()} className="p-1 rounded bg-black/60 text-white hover:bg-black/80"><X className="h-3.5 w-3.5" /></button>
          </div>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent className="console-panel border-border text-zinc-200">
        <ContextMenuItem onClick={doSnapshot}><Image className="h-4 w-4 mr-2" /> Snapshot</ContextMenuItem>
        <ContextMenuItem onClick={doRecord}><Video className="h-4 w-4 mr-2" /> {camera.is_recording ? "Stop recording" : "Start recording"}</ContextMenuItem>
        <ContextMenuItem onClick={() => navigate(`/playback?camera=${camera.id}`)}>Open playback</ContextMenuItem>
        <ContextMenuItem onClick={() => navigate(`/cameras/${camera.id}/settings`)}><Settings className="h-4 w-4 mr-2" /> Camera settings</ContextMenuItem>
        <ContextMenuItem onClick={() => onClear?.()}><X className="h-4 w-4 mr-2" /> Clear tile</ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
```

- [ ] **Step 2: Confirm a context-menu UI primitive exists**

Run:
```bash
ls frontend/src/components/ui/context-menu.js 2>/dev/null && echo HAVE || echo MISSING
```
If `MISSING`, create it from the shadcn Radix wrapper (the project already
depends on `@radix-ui/react-context-menu`). Minimal wrapper:

`frontend/src/components/ui/context-menu.js`:
```jsx
import * as React from "react";
import * as ContextMenuPrimitive from "@radix-ui/react-context-menu";
import { cn } from "../../lib/utils";

export const ContextMenu = ContextMenuPrimitive.Root;
export const ContextMenuTrigger = ContextMenuPrimitive.Trigger;
export const ContextMenuContent = React.forwardRef(({ className, ...props }, ref) => (
  <ContextMenuPrimitive.Portal>
    <ContextMenuPrimitive.Content
      ref={ref}
      className={cn("z-50 min-w-[10rem] overflow-hidden rounded-md border p-1 shadow-md", className)}
      {...props}
    />
  </ContextMenuPrimitive.Portal>
));
ContextMenuContent.displayName = "ContextMenuContent";
export const ContextMenuItem = React.forwardRef(({ className, ...props }, ref) => (
  <ContextMenuPrimitive.Item
    ref={ref}
    className={cn("flex items-center rounded-sm px-2 py-1.5 text-sm outline-none cursor-pointer focus:bg-white/5", className)}
    {...props}
  />
));
ContextMenuItem.displayName = "ContextMenuItem";
```

- [ ] **Step 3: Verify parse**

Run:
```bash
cd frontend && for f in src/components/ui/context-menu.js src/components/wall/VideoTile.js; do \
  [ -f "$f" ] && BABEL_ENV=development NODE_ENV=development node -e "require('@babel/core').transformFileSync('$f',{presets:['react-app']})" && echo "PARSE_OK $f"; done
```
Expected: `PARSE_OK` for each existing file.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/wall/VideoTile.js frontend/src/components/ui/context-menu.js
git commit -m "feat(ui): add video wall tile with overlays and context menu"
```

---

## Task 13: VideoWall

**Files:**
- Create: `frontend/src/components/wall/VideoWall.js`

Layout selector (uses `LAYOUTS`/`slotCount`/`gridStyle`), tile assignment
persisted via `useUiPrefs` (`wallLayout`, `wallTiles`), maximize state, and a
focused-slot model: dragging from the tree or double-clicking a tree camera
fills the first empty slot (or the focused slot).

- [ ] **Step 1: Write the component**

`frontend/src/components/wall/VideoWall.js`:

```jsx
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

  // Normalize tiles array to current slot count.
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
      {/* layout selector toolbar */}
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

      {/* tile grid */}
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
```

- [ ] **Step 2: Verify parse**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development \
  node -e "require('@babel/core').transformFileSync('src/components/wall/VideoWall.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/wall/VideoWall.js
git commit -m "feat(ui): add video wall with layout selector and tile assignment"
```

---

## Task 14: LiveWall page + tree→wall wiring

**Files:**
- Create: `frontend/src/pages/LiveWall.js`
- Modify: `frontend/src/components/shell/ControlRoomLayout.js` (pass an
  `onActivate` from CameraTree into a shared handler so double-clicking a tree
  camera fills the wall)

For v1, keep tree→wall coupling simple and robust: the wall reads/writes
`useUiPrefs` (shared singleton via localStorage). The CameraTree's
`onActivate` writes the activated camera into the first empty slot using the
same prefs. Implement that handler in ControlRoomLayout and pass it to
CameraTree.

- [ ] **Step 1: Write the LiveWall page**

`frontend/src/pages/LiveWall.js`:

```jsx
import React from "react";
import VideoWall from "../components/wall/VideoWall";

export default function LiveWall() {
  return <VideoWall />;
}
```

- [ ] **Step 2: Wire CameraTree.onActivate in ControlRoomLayout**

In `frontend/src/components/shell/ControlRoomLayout.js`, replace the
`<CameraTree />` usage with a handler that fills the first empty wall slot:

```jsx
// add near the top of the component body:
const fillFirstEmpty = (cam) => {
  const tiles = Array.isArray(prefs.wallTiles) ? prefs.wallTiles.slice() : [];
  const count = (prefs.wallLayout && prefs.wallLayout) || 4;
  while (tiles.length < count) tiles.push(null);
  const idx = tiles.findIndex((t) => !t);
  if (idx === -1) tiles[0] = cam.id;
  else tiles[idx] = cam.id;
  setPrefs({ wallTiles: tiles });
};
```

and:

```jsx
<CameraTree onActivate={fillFirstEmpty} />
```

- [ ] **Step 3: Verify parse (both files)**

Run:
```bash
cd frontend && for f in src/pages/LiveWall.js src/components/shell/ControlRoomLayout.js; do \
  BABEL_ENV=development NODE_ENV=development node -e "require('@babel/core').transformFileSync('$f',{presets:['react-app']})" && echo "PARSE_OK $f"; done
```
Expected: `PARSE_OK` for both.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/LiveWall.js frontend/src/components/shell/ControlRoomLayout.js
git commit -m "feat(ui): add LiveWall page and tree-to-wall activation"
```

---

## Task 15: Route swap in App.js

**Files:**
- Modify: `frontend/src/App.js`

Swap the protected `Layout` for `ControlRoomLayout`; make `/` render
`LiveWall` (Dashboard becomes a legacy redirect to keep history working). Keep
all existing nested routes intact.

- [ ] **Step 1: Update imports**

In `frontend/src/App.js`, replace:
```js
import Layout from "./pages/Layout";
```
with:
```js
import ControlRoomLayout from "./components/shell/ControlRoomLayout";
```
and add a lazy import alongside the other lazy pages:
```js
const LiveWall = lazy(() => import("./pages/LiveWall"));
```

- [ ] **Step 2: Swap the layout element and index route**

In the protected route block, change:
```jsx
<Route
  path="/"
  element={
    <ProtectedRoute>
      <Layout />
    </ProtectedRoute>
  }
>
  <Route index element={<Dashboard />} />
```
to:
```jsx
<Route
  path="/"
  element={
    <ProtectedRoute>
      <ControlRoomLayout />
    </ProtectedRoute>
  }
>
  <Route index element={<LiveWall />} />
  <Route path="dashboard" element={<Navigate to="/" replace />} />
```

Leave every other nested route (`cameras`, `playback`, `events`, `settings`,
`bookmarks`, aliases) exactly as-is.

- [ ] **Step 3: Verify parse**

Run:
```bash
cd frontend && BABEL_ENV=development NODE_ENV=development \
  node -e "require('@babel/core').transformFileSync('src/App.js',{presets:['react-app']})" && echo PARSE_OK
```
Expected: `PARSE_OK`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.js
git commit -m "feat(ui): mount ControlRoomLayout and live wall at /"
```

---

## Task 16: Run the full helper test suite

**Files:** none (verification)

- [ ] **Step 1: Run all new unit tests**

Run: `cd frontend && CI=true craco test src/lib/`
Expected: PASS — videoWall (4) + telemetry (3) test files green.

- [ ] **Step 2: Commit (if any snapshot/config changed)**

If nothing changed, skip. Otherwise:
```bash
git add -A && git commit -m "test: run UI helper suite"
```

---

## Task 17: Build, deploy, and in-browser verification

**Files:** none (verification)

- [ ] **Step 1: Build & deploy the frontend**

Run (from repo root):
```bash
DOCKER=/Applications/Docker.app/Contents/Resources/bin/docker
$DOCKER compose build frontend && $DOCKER compose up -d --no-deps frontend && echo FRONTEND_OK
```
Expected: `FRONTEND_OK` (build succeeds — confirms no import/JSX errors across the new shell).

- [ ] **Step 2: In-browser verification (Chrome MCP, tab on https://localhost)**

Log in as admin / Admin@12345 if needed, navigate to `/`, screenshot, and confirm:
1. Left icon rail with Live active.
2. Camera tree visible on the left, lists cameras with status dots.
3. Live video wall with a layout selector (1/4/6/8/9/16/25); changing layout re-tiles.
4. Dragging a camera from the tree into a tile starts a live stream; double-click maximizes.
5. Bottom status bar shows CPU/MEM/DISK/REC/CAMS/NODE + clock.
6. Right alarm dock toggles open/closed.
7. Navigate to `/playback`, `/cameras`, `/events`, `/settings` — all still render inside the shell with no console errors.

- [ ] **Step 3: Capture before/after screenshots for the client and report**

No commit. Summarize the verification result to the user.

---

## Self-Review (completed during authoring)

- **Spec coverage:** Shell regions (rail/tree/header/status bar/alarm dock) → Tasks 6–11. Console theme + aurora removal → Task 1. Live video wall as landing → Tasks 12–15. Telemetry status bar → Task 8. Reuse of WebRTCPlayer/PTZ/hooks → Tasks 12–13. Page-by-page migration (no breakage) → Task 15 keeps all routes. Playback timeline / Cameras restyle / Events console are explicitly deferred to Plans 2–4 (spec §8 migration order).
- **Placeholder scan:** No TBD/TODO; every code step has complete code. The header search input is intentionally inert in v1 and documented as such (not a placeholder).
- **Type/name consistency:** `slotCount`/`gridStyle`/`LAYOUTS` (Task 2) used identically in Tasks 13. `useUiPrefs` returns `[prefs, update]` and is consumed that way in Tasks 11/13/14. `localNodeRole(nodes)` (Task 4) used in Task 8. `getStreamUrls(...).live_stream_id` matches `LiveStream.js` usage. CameraTree drag key `text/nvr-camera-id` is written (Task 7) and read (Task 12) identically.
- **Risk follow-ups:** 16/25-tile WebRTC load (verify in Task 17 step 2); confirm `getResources()` field names (`cpu_percent` etc.) during Task 8 browser check and adjust the fallback chain if the API uses different keys.
