# AI Integration Plan

## Goal

Keep the current product as a complete NVR first, then add AI as optional scenario modules without destabilizing live view, recording, playback, ONVIF, storage, or events.

## Current Position

- Backend AI routers and models exist but are opt-in behind `ENABLE_AI_MODULES=false`.
- Frontend AI routes are effectively disabled by redirecting `/ai/*` to the NVR home.
- NVR event ingestion already supports `source_service` and `detection_type`, so AI can publish into the same event pipeline.
- Camera records already have `detect_stream_url`, which can be used for lower-bitrate AI processing separate from recording streams.

## Principles

1. AI must never block NVR recording, playback, camera monitoring, or ONVIF control.
2. AI scenarios run as optional external services. The NVR owns configuration, auth, event display, and audit.
3. Every AI event must be explainable: scenario, camera, timestamp, confidence, snapshot, metadata.
4. GPU/CPU limits must be explicit per scenario and globally visible in Resources.
5. If AI service is down, NVR should show degraded AI status but continue normal NVR operation.

## Phase 1 - Integration Foundation

- Add an AI Integrations page under Settings.
- Keep `ENABLE_AI_MODULES` as the backend gate.
- Add a visible AI status card:
  - enabled/disabled
  - bridge URL
  - service health
  - GPU availability
  - active AI streams
- Add scenario registry UI:
  - scenario name
  - version
  - status
  - licensed/enabled
  - camera limit
- Verify event ingestion accepts scenario events with:
  - `source_service`
  - `detection_type`
  - `confidence`
  - `bbox`
  - `track_id`
  - `person_id`
  - snapshot reference

## Phase 2 - Camera Assignment

- Add per-camera AI tab or section:
  - choose scenario
  - use main/sub/detect stream
  - FPS limit
  - confidence threshold
  - region of interest
  - schedule
- Add batch assignment from Cameras page.
- Validate camera count limits from license before assignment.
- Show per-camera AI state:
  - not assigned
  - starting
  - running
  - degraded
  - stopped

## Phase 3 - Events And Playback

- Add AI event filters to Event Log only when AI is enabled.
- Standardize event types:
  - `face_recognized`
  - `unknown_face`
  - `ppe_violation`
  - `ppe_compliant`
  - future scenario-defined types
- Link each AI event to:
  - camera
  - snapshot
  - playback timestamp
  - scenario details
- Add false alarm / acknowledge flow for AI events.
- Avoid cluttering Event Log with normal AI lifecycle messages.

## Phase 4 - First Scenarios

### FRS

- Person gallery: groups, persons, enrollment photos.
- Live recognition events.
- Attendance/reporting views.
- Investigation search by face image.
- Cross-camera transit timeline.

### PPE

- PPE compliance checks on image/video/live stream.
- Violation event ingestion.
- Camera-level PPE rule configuration.
- Reports by camera, time, and violation type.

## Phase 5 - Reliability And Operations

- Add AI health metrics to Resources:
  - GPU memory
  - model load status
  - active streams
  - inference FPS
  - dropped frames
  - queue depth
- Add restart/reconnect behavior for bridge failures.
- Add audit logs for:
  - scenario enable/disable
  - camera assignment changes
  - person enrollment changes
  - rule changes
- Add backups for AI configuration, excluding large model/vector data.

## Phase 6 - Testing Checklist

- NVR continues recording when AI bridge is stopped.
- Camera online/offline status unaffected by AI failures.
- AI event ingestion cannot create unbounded event noise.
- Per-scenario camera limits enforced.
- GPU visible in Resources with and without AI active.
- FRS and PPE can be disabled independently.
- License gate blocks unlicensed scenarios.
- Events link correctly to playback timestamps.

## Recommended Next Step

Start with Phase 1 only:

1. Enable backend AI modules in a controlled dev run.
2. Verify existing AI endpoints do not break startup.
3. Build Settings > Integrations > AI status page.
4. Add bridge health check and scenario registry read-only view.
5. Only after that, expose camera assignment.
