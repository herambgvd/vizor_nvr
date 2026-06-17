# NVR-First ONVIF Completion Plan

This project now ships the core NVR first. AI scenario modules remain parked
behind `ENABLE_AI_MODULES=true` until the NVR is complete.

## Product Boundary

Current scope:

- Live view, recording, playback, export, events, storage, users/RBAC, license,
  monitoring, and ONVIF interoperability.
- ONVIF Profile S, G, T, and M readiness for camera integration and VMS
  compatibility.
- Profile M as generic metadata and analytics event transport only. No face,
  PPE, object, or custom AI inference is part of this phase.

Deferred scope:

- FRS, PPE, attendance, investigation, and scenario workspaces.
- AI scenario licensing and per-camera scenario enablement.
- AI-specific event interpretation beyond storing and displaying generic
  metadata payloads.

## ONVIF Profiles

### Profile S

Goal: reliable baseline camera interoperability.

- WS-Discovery and manual add.
- Device information and capabilities.
- Media1 profiles and RTSP stream URIs.
- Snapshot URI.
- PTZ presets, continuous move, stop, relative move, and absolute move.
- Imaging settings and focus controls.
- PullPoint events and BaseNotification push receiver.
- Digital inputs and relay outputs.
- Audio and two-way audio where cameras expose backchannel support.

### Profile T

Goal: modern streaming and event compatibility.

- Media2 service detection.
- H.265/H.264 stream profile selection.
- Main/sub-stream pairing.
- Media2 audio encoder configuration discovery.
- Metadata configuration discovery.
- Camera-side event topics for motion, tamper, line crossing, intrusion, and
  video loss.
- Browser playback via go2rtc with graceful H.265 handling.

### Profile G

Goal: recording, search, and replay interoperability in both directions.

- NVR-as-device Recording, Search, and Replay services for external VMS clients.
- NVR client support for camera-side recording search when a camera has SD-card
  or edge storage.
- Replay URI support for camera-side recordings when exposed by the camera.
- ANR backfill path that can use Profile G search/replay where available.
- Conformance script coverage for GetRecordings, FindRecordings,
  GetRecordingSearchResults, GetReplayUri, and replay configuration.

### Profile M

Goal: generic analytics metadata/event ingestion without AI inference.

- Discover analytics/metadata services and capabilities.
- Discover metadata configurations and metadata stream URI where available.
- Ingest ONVIF analytics events as generic NVR events.
- Store original topic, source, key/value data, bounding boxes, classifications,
  object IDs, and confidence when present.
- Display Profile M events in the Events console with raw metadata inspection.
- Expose Profile M metadata through API/SSE/WebSocket using the same event model.

Important boundary: Profile M support in this phase means "camera-generated
metadata in, normalized event out." It does not mean running internal AI models.

## Immediate Code Tasks

1. Keep AI disabled by default.
   - Backend routes and startup are gated by `ENABLE_AI_MODULES`.
   - Frontend AI routes and navigation are hidden.

2. Stabilize NVR security and licensing.
   - Use only the Ed25519 `.lic` license service for active license state.
   - Keep `/api/system/license/*` as compatibility wrappers only.
   - Keep route permissions enum-backed and scan for unknown permission names.

3. Finish ONVIF client Profile S/T gaps.
   - Add explicit Media2 audio encoder discovery.
   - Verify relative and absolute PTZ paths per vendor.
   - Add BaseNotification receiver tests for camera-pushed events.

4. Finish ONVIF client Profile G.
   - Camera-side recording search/replay service detection is implemented.
   - API and ONVIF page affordance for edge recordings are implemented.
   - Wire ANR to Profile G where possible, with fallback to existing behavior.

5. Add Profile M metadata foundation.
   - Generic ONVIF event metadata parser helpers are implemented.
   - Event normalization preserves ONVIF topic/source/data payloads.
   - Metadata stream URI discovery is implemented.
   - ONVIF metadata XML parser/ingestor is implemented.
   - Validate live RTSP packet extraction with Profile M/T cameras.
   - Add conformance smoke rows for MetadataConfigurations and analytics events.

6. Update vendor compatibility matrix from lab results.
   - Hikvision, Dahua, Axis, Bosch, Hanwha, Uniview, Vivotek, Reolink, Amcrest.
   - Track exact firmware, ONVIF port, auth mode, Profile G support, and
     Profile M event behavior.

## Verification Gates

Before calling the NVR complete:

- Backend tests pass.
- Frontend tests/build pass.
- ONVIF device conformance script passes for Profile S/T/G.
- Profile M metadata smoke test passes with at least one camera that emits
  analytics metadata.
- At least three vendor families are lab-verified for discovery, live,
  recording, playback, events, and time sync.
- License activation and unlicensed recovery work through both canonical and
  compatibility endpoints.
