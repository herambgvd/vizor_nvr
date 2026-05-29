# Plan: Cameras Device Manager (Plan 3 — NVR UX Overhaul)

**Date:** 2026-05-29
**Branch:** feature/nvr-ux-control-room (worktree)
**Spec ref:** docs/superpowers/specs/2026-05-29-nvr-ux-overhaul-design.md §7

## Goal
Restyle `frontend/src/pages/Cameras.js` as a dense console-themed *device manager*.
Keep ALL existing features. Add card/grid view toggle with localStorage persistence.

## Tasks

### T1 — Add console CSS variables to index.css
**File:** `frontend/src/index.css`
Append after the existing `@layer utilities` block:
```css
/* Console theme tokens (OLED dark, matches Plan 1 / Plan 2) */
:root {
  --console-bg: #000000;
  --console-panel: #0a0a0a;
  --console-raised: #141414;
  --console-border: #1f1f1f;
  --console-text: #e2e8f0;
  --console-muted: #8a8f98;
  --console-accent: #14b8a6;
  --console-accent-blue: #3b82f6;
  --console-rec: #ef4444;
  --console-alarm: #f59e0b;
  --console-online: #22c55e;
  --console-offline: #71717a;
}
.console-panel { background: var(--console-panel); border-color: var(--console-border); }
.console-raised { background: var(--console-raised); }
.font-telemetry { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
```

### T2 — Add useUiPrefs hook
**File:** `frontend/src/hooks/useUiPrefs.js` (new)
Port from main repo's implementation. Add `camerasView: "table"` to DEFAULTS.
Export from `frontend/src/hooks/index.js`.

### T3 — Restyle Cameras.js (main task)
**File:** `frontend/src/pages/Cameras.js`

#### Changes:
1. **Import `useUiPrefs`** from `../hooks/useUiPrefs`
2. **Import `LayoutGrid`, `List` icons** from lucide-react (view toggle)
3. **Page wrapper**: change outer `<div>` to use console theme:
   - `style={{ background: "var(--console-bg)", color: "var(--console-text)" }}`
4. **Page header**: add a `<header>` bar with:
   - "CAMERAS" title (monospace, uppercase, teal accent left border)
   - Camera count badge (font-telemetry)
   - View toggle buttons (List / LayoutGrid icons) wired to `camerasView` pref
5. **Toolbar strip**: restyle the existing toolbar with console-panel background,
   border-bottom using `--console-border`. Inputs/selects/buttons adopt dark console style.
6. **Table view**: restyle with console panel background, borders using CSS vars.
   - `HealthCell`: already monospace — update tone classes to match console palette
   - Selected row highlight: use `--console-accent` at low opacity
7. **Grid/Card view** (NEW): shown when `camerasView === "grid"`. Dense card grid:
   - `grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2`
   - Each card: `console-raised` bg, 1px border at `--console-border`
   - Top: `CameraThumbnail` (full width, aspect-video)
   - Overlay on thumbnail: top-left status dot + rec dot; top-right checkbox
   - Bottom strip: camera name (truncate), health kbps·fps (font-telemetry, muted)
   - Right-click opens same `contextMenu`; checkbox for bulk select
   - Drag-to-reorder: same `draggable` / `onDragStart` / `onDrop` logic as table
   - Actions: same `DropdownMenu` (MoreVertical) as in table
8. **Pagination**: unchanged logic; restyle row-count selector and nav buttons
9. **Mobile view**: keep existing mobile cards as-is (they already work well)
10. **All dialogs/modals**: unchanged (they're already dark)
11. **Preview modal**: unchanged
12. **RTSP URL masking**: NOT TOUCHED — existing masking is preserved since we
    don't change how URLs are displayed (they're still just shown from `camera.main_stream_url`)

### T4 — Verify & test
- Babel parse check: `cd frontend && export BABEL_ENV=development NODE_ENV=development && node -e "require('@babel/core').transformFileSync('src/pages/Cameras.js',{presets:['react-app']})" && echo PARSE_OK`
- Lib tests: `cd frontend && CI=true npx react-scripts test --watchAll=false src/lib/`
- Build: `cd frontend && npx react-scripts build`

### T5 — Commit
Conventional commits:
- `feat(theme): add console CSS variables to index.css`
- `feat(hooks): add useUiPrefs with camerasView pref`
- `feat(cameras): restyle as dense console device manager with grid/table toggle`

## Non-goals (explicitly NOT done)
- No backend changes
- No routing changes
- No change to RTSP credential display logic
- No change to other pages
