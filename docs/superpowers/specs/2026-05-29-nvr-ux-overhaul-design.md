# NVR UX Overhaul — Control-Room VMS Design

**Date:** 2026-05-29
**Status:** Approved (design), pending implementation plan
**Owner:** Frontend

## 1. Problem & Goal

Client feedback: the product "doesn't feel like an NVR." The current UI reads
like a generic web admin dashboard — horizontal top-bar nav, a card-grid
"Dashboard" as the home screen, a glassy aurora-gradient theme, and a
slider-based playback. It lacks the dense, operations-console character of a
professional video management system (VMS).

**Goal:** Re-shell and restyle the frontend so it feels like a serious
surveillance operator console in the style of **Milestone XProtect /
Hikvision iVMS**, while reusing the existing players, API layer, and
business logic. Scope is a **full overhaul** across the app shell, Live video
wall, Playback timeline, Cameras, and Events.

### Non-goals
- No backend API changes beyond what's already exposed (monitoring, cluster,
  cameras, recordings, events, PTZ). New endpoints are out of scope; if a view
  needs data not yet served, note it as a follow-up.
- No new authn/permission model. Existing RBAC (`isAdmin`, `usePermissions`)
  is reused as-is.
- No change to streaming transport — keep the existing WebRTC pipeline.

## 2. Reference Feel & Principles

- **Reference:** Milestone / Hikvision iVMS — dense, panel-heavy operator
  console, info-rich tiles, compact controls, "serious surveillance" tone.
- **Density over whitespace:** ~12–13px base type, tight padding, 4–6px radii,
  thin 1px dividers. Monospace for telemetry (fps, kbps, timestamps).
- **Color discipline:** dark near-black slate base; teal/blue accent reserved
  for active/selected state only; **recording = red**, **alarm = amber/red**,
  **online = green**, **offline = zinc/red**.
- **Reuse, don't rewrite:** wrap existing `WebRTCPlayer`, `PTZControls`, API
  hooks (`useCamerasQuery`, `useCameraMutations`), monitoring & cluster APIs.
- **Migrate page-by-page:** the app must never be broken mid-overhaul.

## 3. App Shell — `ControlRoomLayout`

Replaces the horizontal-top-bar `Layout`. Regions:

| Region | Size | Purpose |
|---|---|---|
| Left icon rail | ~56px | Primary nav: Live, Playback, Cameras, Events, Bookmarks, Settings. Icon + tiny label. Collapsible. |
| Camera tree panel | ~260px | Persistent on Live & Playback. Groups → cameras, live status dots, search/filter, drag handles. Collapsible/dockable. |
| Top header | ~44px | Brand mark, page title/breadcrumb, global camera search, layout presets, live NVR clock, cluster/connection badge, user menu. |
| Main content | flex | The active view (video wall, timeline, tables…). |
| Right alarm dock | ~300px | Collapsible live event/alarm feed, severity-colored, click → jump to camera/playback. |
| Bottom status bar | ~28px | CPU/RAM/disk, active recordings, online/offline counts, retention, node role (active/standby), system time. |

### Shared components introduced
- `ControlRoomLayout` — the shell with all regions and collapse state.
- `CameraTree` — group/camera tree; emits `onSelect`, `onActivate`
  (double-click), and supports HTML5 drag of a camera payload.
- `StatusBar` — bottom telemetry strip; polls monitoring + cluster APIs.
- `AlarmDock` — right live-event feed (reuses existing live-event source from
  `LiveEventProvider`/`LiveEventDrawer`).
- `VideoWall` — tile grid + layout engine (see §5).
- `Timeline` — multi-track recording/event timeline (see §6).

State that must persist per user (localStorage first; backend later if needed):
tree collapse, rail collapse, alarm dock open/closed, last Live layout + tile
assignments, saved layout presets.

## 4. Visual Language (theme tokens)

Centralize as CSS variables / Tailwind tokens so density and color live in one
place:
- Base background `#0b0f17`, panel `#121821`, raised `#161d29`, border
  `#1e2530`.
- Accent teal `#14b8a6` / blue `#3b82f6` for active/selected only.
- Semantic: rec `#ef4444`, alarm `#f59e0b`, online `#22c55e`, offline
  `#71717a`.
- Type scale shifted down one step from current; monospace family for
  telemetry.
- **Remove the aurora gradient** on operational screens (Live, Playback,
  Cameras, Events). Keep it only on Login. (Confirmed with stakeholder.)

## 5. Live Video Wall (landing `/`)

The home route becomes the live wall — the app "boots into monitoring."

- **Layouts:** 1 / 4 / 6 / 8 / 9 / 16 / 25 + custom; user-saved presets.
- **Tiles:** WebRTC via existing `WebRTCPlayer`. Empty tile shows a
  "drop camera here" target.
- **Tile overlays:** top-left name + status dot; top-right rec● + PTZ icon;
  bottom footer fps/bitrate/codec (monospace); hover toolbar (snapshot,
  mic/audio, maximize, settings, go-to-playback).
- **Interactions:** double-click → maximize (ESC restores); drag camera from
  tree → assign to focused/next empty tile; per-tile right-click context menu
  (snapshot, start/stop recording, open playback @ now, camera settings).
- **PTZ:** overlay on hover for PTZ-capable cameras, reusing `PTZControls`.
- Sequence/patrol auto-cycle is a **follow-up**, not this pass (YAGNI for v1).

## 6. Playback (timeline-centric)

Replace the slider in `MultiPlayback` with a real timeline:
- **Multi-track horizontal timeline:** one track per selected camera; recording
  segments rendered as bars; event markers (motion/alarm) as ticks.
- **Playhead:** draggable, zoomable (hour ↔ day), with a calendar/date jump.
- **Sync:** all cameras scrub together; speeds 0.25–8× plus frame step.
- **Export:** select a time range → existing export flow.
- Same `CameraTree` on the left to add/remove cameras from the review set.
- Keep the existing UTC parsing (`parseUtc`) and grid logic where still useful.

## 7. Cameras & Events

- **Cameras** — restyle dense as a *device manager* (not the home). Keep the
  existing table, bulk actions, search, drag-reorder, health; add a card/grid
  view toggle. Visually align with the console theme.
- **Events** — a searchable history console: filter bar, list + detail,
  thumbnail, jump-to-playback. The right **AlarmDock** is the *live* feed;
  the Events page is the *historical* record.

## 8. Implementation Strategy

1. Add theme tokens (CSS vars / Tailwind) — no visual change yet beyond palette.
2. Build `ControlRoomLayout` + `CameraTree` + `StatusBar` + `AlarmDock` as new
   components; wire them behind the existing routes via a new layout element.
3. Migrate **Live** first (new `VideoWall` as `/`), then **Playback**
   (`Timeline`), then **Cameras**, then **Events**. Each migration is
   independently shippable; old pages stay until replaced.
4. Reuse `WebRTCPlayer`, `PTZControls`, `useCamerasQuery`,
   `useCameraMutations`, monitoring/cluster API clients.
5. Keep route aliases working (legacy `/dashboard` etc. redirect into the new
   shell) so nothing 404s.

## 9. Risks & Open Questions

- **Performance:** 16/25 simultaneous WebRTC tiles may stress the browser/
  go2rtc. Mitigation: lazy-start tiles, substream/low-res for wall tiles if
  available, cap concurrent high-res. Verify during Live migration.
- **Timeline data:** confirm the recordings API can return per-camera segment
  lists + event markers for an arbitrary date range efficiently; if not, that's
  a backend follow-up.
- **Saved layouts:** v1 stores presets in localStorage; a backend
  `user_layouts` store is a possible follow-up if cross-device sync is wanted.
- **Status bar metrics:** node role from cluster API, resources from monitoring
  API; both already exist. Poll interval ~5s.

## 10. Success Criteria

- Logging in lands on a live multi-camera wall with a persistent camera tree.
- The bottom status bar shows real system/cluster telemetry.
- Playback uses a scrubbing multi-track timeline, not a slider.
- The theme reads as a dense dark operator console; aurora gone from
  operational screens.
- No regression: all existing actions (record, PTZ, export, manage cameras,
  events, settings) still work.
