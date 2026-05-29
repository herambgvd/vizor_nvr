# Plan: Events Page → Historical Events Console

**Branch:** feature/nvr-ux-control-room  
**Date:** 2026-05-29  
**File to restyle:** `frontend/src/pages/Events.js`

## Goal
Restyle Events.js into a console-themed **historical events console** with:
- Prominent filter/search bar at the top
- Master-detail layout: scrollable event list (left) + detail panel (right)
- Thumbnails in detail panel
- Jump-to-playback action navigating `/playback?camera=<cameraId>`
- Full preservation of all existing functionality

All styling uses the established theme tokens from `frontend/src/index.css`
(deep-navy bg, graphite cards, teal accent, etc.) matching the existing shell
in `frontend/src/pages/Layout.js`.

## API Data Shape
`getEvents(params)` returns `response.data` directly (not wrapped). The
current Events.js reads `data?.events` and `data?.total`, so the shape is:
```json
{ "events": [...], "total": 123 }
```

## Jump-to-Playback
`/playback?camera=<cameraId>` seeds MultiPlayback (see MultiPlayback.js line 469).

## Tasks

### T1 — Console filter/search bar
Replace the existing wrapping `<div className="p-6 md:p-8 space-y-6">` shell
with a full-height console layout (`min-h-screen bg-background`). Render a
sticky header bar containing:
- Page title: `<Bell>  EVENT LOG` in monospace-caps + teal accent
- Severity stat chips (info/warning/critical/alarm counts from stats query)
- Unacknowledged count badge
- Action buttons: Acknowledge All, Export CSV, Delete Filtered / Delete Bulk
  (all existing logic untouched)

Below header, a filter bar panel (dark panel bg, border) containing:
- Search input (free-text, client-side filter on title/camera name)
- Event type select
- Severity select
- Camera select
- Acknowledged status select
- Start/end datetime inputs
- All existing filter state + setPage(1) resets preserved

### T2 — Master-detail split layout
Replace the current three-column hero + table layout with a
`grid grid-cols-1 lg:grid-cols-[400px_1fr]` or
`flex` two-panel layout:

**Left panel** (fixed-width, scrollable):
- Header row: checkbox (select all) + column labels
- Scrollable list of event rows
- Each row: left-edge severity color accent bar (4px), type icon, title,
  camera name, timestamp (date-fns `MMM dd HH:mm:ss`), status badge
- Row states: selected (teal bg tint), unacknowledged (subtle red tint),
  active/selected border highlight
- Bulk selection checkbox per row
- Click row → sets selectedEvent
- Pagination bar at bottom of list

**Right panel** (takes remaining width):
- When no event selected: empty state with Bell icon + "Select an event"
- When event selected: full detail panel (see T3)

### T3 — Detail panel with thumbnail + actions
The right detail panel renders:

**Thumbnail section** (top, aspect-video):
- Fetches latest snapshot for `selectedEvent.camera_id` (reuses existing
  `recSnapUrl` / `snapLoading` state logic verbatim)
- Shows camera name overlay and event timestamp overlay
- "No snapshot" placeholder when unavailable

**Metadata section** (below thumbnail):
Grid of key-value pairs:
- Event Type, Severity (colored badge), Date/Time, Camera, Title, ID, Status

**Action buttons** (bottom):
- Acknowledge (if not acknowledged) — existing `ackMutation`
- False Alarm (if not acknowledged) — existing `falseAlarmMutation`
- **Jump to Playback** — `useNavigate` to `/playback?camera=${selectedEvent.camera_id}`
  (new addition; only shown when `selectedEvent.camera_id` is set)
- **View Live** — opens WebRTCPlayer in a Dialog (reuses existing live-view
  Dialog pattern from Events.js, currently `open={false}` — restore this
  properly as an opt-in dialog triggered by button click)
- Delete — opens `confirmDelete` dialog

### T4 — Remove dead Dialog + clean up
The old `Dialog open={false}` (event detail dialog) is dead code. Remove it.
The live-view Dialog is currently buried; wire it to a state toggle
`[liveOpen, setLiveOpen]`. Keep the delete confirmation Dialog.

### T5 — Parse + build verify
Run:
```bash
cd frontend && export BABEL_ENV=development NODE_ENV=development && \
  node -e "require('@babel/core').transformFileSync('src/pages/Events.js',{presets:['react-app']})" && \
  echo PARSE_OK
```
Then: `cd frontend && CI=true npx react-scripts test --watchAll=false src/__tests__/`
Then: `cd frontend && npx react-scripts build`

## Files modified
- `frontend/src/pages/Events.js` — full restyle (only file changed)

## Files NOT touched
- `frontend/src/App.js` (routing unchanged)
- `frontend/src/pages/Layout.js`
- `frontend/src/api/events.js`
- `frontend/src/api/cameras.js`
- Any backend file
