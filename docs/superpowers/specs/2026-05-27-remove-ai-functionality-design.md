# Remove AI Functionality — Design Spec

**Date:** 2026-05-27
**Status:** Approved (brainstorming)
**Goal:** Strip all AI/inference functionality from GVD NVR. Ship a focused, market-ready Network Video Recorder. Licensing module is retained for NVR seat/camera licensing; events ingest/SSE routers are repurposed for NVR (motion/ONVIF/system) events.

## Scope decisions (approved)

- **Full purge** of AI code, UI, DB tables, env vars, dependencies.
- **Keep** licensing module, strip AI entitlements.
- **Keep** events ingest + SSE routers; repurpose for NVR events (drop AI-specific fields).

## Backend removals

### Delete entirely
- `backend/app/ai/` (whole tree — frs/, people/, scenarios/, triton_client.py, qdrant_client.py, seed.py, models.py, frs_router.py, frs_photos_router.py, scenarios_router.py, __init__.py)
- `backend/app/services/metropolis_bridge.py`

### Edit `backend/app/main.py`
- Remove lines ~56–59: `seed_ai_scenarios` block
- Remove lines ~163–169: Metropolis bridge startup
- Remove lines ~173, ~208: `counts_writer` start/stop
- Remove lines ~335–339: AI router imports
- Remove lines ~359–364: AI router `include_router` calls

### Edit `backend/app/license/router.py`
- Remove `from app.ai.models import CameraAIConfig`
- Remove `ai_cam` count computation
- Simplify `_counts()` to return only camera total; update `svc.snapshot()` call sites

### Edit `backend/app/license/service.py`
- Drop `ai_camera_limit` and `scenarios` fields from license payload dataclass
- Remove from `from_dict`, logging, and snapshot
- License payload retains: tier, camera limit, expiry, fingerprint

### Edit `backend/app/config.py`
- Remove the "AI / Inference" block: `QDRANT_URL`, `TRITON_URL`, `METROPOLIS_BRIDGE_ENABLED`, `AI_EVENT_STREAM`, `AI_EVENT_GROUP`

### Edit `backend/app/events/sse_router.py`
- Drop `scenario` query param and the scenario filter
- Rename emitted event from `ai_event` → `event`
- Update docstring to describe NVR (motion/ONVIF/system) events only

### Edit `backend/app/events/ingest_router.py`
- Drop AI-specific fields: `person_id` (FRS), scenario-typed payloads
- Keep generic event ingestion: `source_service`, `event_type`, `camera_id`, `timestamp`, `payload`, `dedup_key`
- Update docstring; allow any internal NVR service to publish

### New Alembic migration `009_remove_ai_tables.py`
Drop AI tables (verify exact names by inspecting models before writing migration):
- `camera_ai_configs`
- `frs_persons`, `frs_groups`, `frs_person_groups`, `frs_recognitions`, `frs_attendance`, `frs_photos`
- `people_counts`, `people_count_events`
- `ai_scenarios` (seed table)
- Any FK-dependent rows in `events` referencing AI scenarios → either delete by scenario column or null it before dropping that column

Downgrade: re-create as empty tables (no data preserved).

### Dependencies (`backend/requirements.txt`)
- Remove `qdrant-client`, `tritonclient[*]`, any face-recognition libs (`insightface`, `onnxruntime`, etc.), `numpy`/`opencv` only if not used elsewhere — verify before removing.

## Frontend removals

### Delete entirely
- `frontend/src/pages/ai/` (all subdirs: scenarios/frs, scenarios/people-counting, scenarios/ppe, AIModulesIndex, ScenarioLayout, ScenarioStub)
- `frontend/src/pages/camera-detail/ai/` (CameraAILayout, CameraScenarioConfig)
- `frontend/src/components/camera/CameraAITab.js`
- `frontend/src/hooks/useLiveDetections.js`
- `frontend/src/api/ai.js`, `api/frs.js`, `api/people.js`

### Edit `frontend/src/App.js`
- Remove AI lazy imports (lines ~49–83)
- Remove AI routes (lines ~169, ~178–215)
- Remove the `cameras/:cameraId/ai` nested route

### Edit `frontend/src/pages/Layout.js`
- Update top comment from "5 primary nav items … AI Modules" → "4 primary nav items"
- Remove the AI Modules nav entry (path `/ai/modules`, label "AI Modules")
- Final nav: Dashboard, Cameras, Events, Settings

### Edit `frontend/src/pages/camera-detail/CameraDetailLayout.js`
- Remove the AI tab from camera detail tab bar (verify file)

### Edit `frontend/src/pages/settings/LicensePage.js`
- Hide/remove AI scenario list + `ai_camera_limit` display fields

### Edit `frontend/src/hooks/useLicense.js`
- Drop `ai_camera_limit` / `scenarios` consumers if present

## Out of scope
Recording, playback, ONVIF, motion events, IO/relay, notifications, monitoring, storage, bookmarks, multi-playback, retention, snapshots, go2rtc — untouched.

## Verification

**Backend**
- `pytest backend/` passes
- `uvicorn app.main:app` boots cleanly with no import errors
- `GET /api/health` returns 200
- `alembic upgrade head` runs from a fresh DB AND from a DB at revision 008 (existing install)
- `grep -r "app.ai\|metropolis_bridge\|TRITON_URL\|QDRANT_URL" backend/` returns empty

**Frontend**
- `npm run build` completes with no missing-import errors
- App loads, 4-item nav renders, no console errors on `/`, `/cameras`, `/events`, `/settings`
- `grep -r "pages/ai\|api/ai\|api/frs\|api/people\|CameraAITab\|useLiveDetections" frontend/src/` returns empty

**Manual smoke**
- Add camera → live view → record → playback → bookmark → notification → license activate. All work.

## Risks
- Existing installs with AI data: migration 009 destroys it. Acceptable per "full purge" decision; release notes must call this out.
- Hidden cross-imports from non-AI modules into `app.ai` — grep before deleting; fix or remove offending callers.
- License files in the wild may include `ai_camera_limit` / `scenarios` keys — `from_dict` must ignore unknown keys gracefully (already does via `.get` defaults; verify).
