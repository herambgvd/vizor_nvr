# ONVIF Client-Side Compliance Audit

**NVR role:** ONVIF client (talks TO cameras). This document audits our coverage
of ONVIF Profile S, Profile T, Profile G, and Profile M capabilities as a client.

Last updated: 2026-06-14  
Reference code: `backend/app/cameras/onvif_service.py`, `backend/app/cameras/router.py`

Current product focus is NVR-first. AI scenario modules are parked until NVR
recording, playback, camera management, and ONVIF S/G/T/M support are complete.
See `docs/NVR_ONVIF_COMPLETION_PLAN.md` for the implementation plan.

---

## Profile S — Streaming (mandatory for all ONVIF devices)

| Capability | Status | Notes / File:Line |
|---|---|---|
| WS-Discovery (device discovery) | ✅ | `onvif_service.py` `discover()` — multicast + TCP fallback |
| GetDeviceInformation | ✅ | `get_device_info()` L322 |
| GetCapabilities | ✅ | `get_capabilities()` L759 |
| GetProfiles (Media1) | ✅ | `get_stream_uris()` L449, `enumerate_channels()` L1174 |
| GetStreamUri (RTSP unicast) | ✅ | `get_stream_uris()` L449 |
| GetSnapshotUri | ✅ | `get_snapshot_uri()` L371 |
| GetVideoSources | ✅ | Used in `get_imaging_settings()` L922 |
| PTZ — ContinuousMove | ✅ | `continuous_move()` L506 |
| PTZ — Stop | ✅ | `stop()` L537 |
| PTZ — GetPresets / GotoPreset | ✅ | `get_presets()` L558, `goto_preset()` L579 |
| PTZ — SetPreset / RemovePreset | ✅ | `set_preset()` L604, `delete_preset()` L630 |
| Imaging — GetImagingSettings | ✅ | `get_imaging_settings()` L922 — brightness, contrast, saturation, sharpness, WDR, BLC, exposure |
| Imaging — SetImagingSettings | ✅ | `set_imaging_settings()` L1017 |
| Imaging — GetOptions | ✅ | `get_imaging_options()` L985 |
| Imaging — Move (focus) | ✅ | `move_focus()` L1064 |
| ONVIF Events — PullPoint subscription | ✅ | `onvif_event_service.py` — per-camera PullPoint workers |
| ONVIF Events — Base notification (WS-BaseNotification push) | ⚠ partial | PullPoint only. Cameras that push events (rather than waiting for pull) are not handled. TODO: add BaseNotification receiver. |
| Relay outputs (digital I/O) | ✅ | `get_relay_outputs()` L1094, `set_relay_output_state()` L1121 |
| Digital inputs | ✅ | `get_digital_inputs()` L1145 |
| SystemReboot | ✅ | `reboot_camera()` L878 |
| SetSystemDateAndTime (time sync) | ✅ | `sync_camera_time()` L851 |
| GetSystemDateAndTime | ✅ | `get_camera_time()` L823 |
| SetSystemFactoryDefault | ✅ | `factory_default()` L896 |
| UpgradeSystemFirmware | ✅ | `upgrade_firmware()` — modern path first, SystemReboot fallback |
| SetUser (credential rotation) | ✅ | `set_user_password()` |
| GetNetworkInterfaces | ✅ | Called inside `get_device_info()` for MAC address |
| Audio output (backchannel URI) | ✅ | `get_audio_output_uri()` L1363; FFmpeg-based session in `twoway_audio_service.py` |

---

## Profile T — Advanced Streaming (H.265, modern cameras)

| Capability | Status | Notes / File:Line |
|---|---|---|
| Media2 service detection | ✅ | `get_capabilities()` checks `GetServices` namespace for `media/2` |
| Media2 GetProfiles | ✅ | `get_stream_uris_media2()` L678 |
| Media2 GetStreamUri (H.265) | ✅ | `get_stream_uris_media2()` L678 — codec detected from profile |
| Media2 → Media1 fallback | ✅ | `get_stream_uris_with_media2_fallback()` L746 — Media2 first, Media1 fallback |
| Media2 GetAudioEncoderConfigurations | ✅ | `get_stream_uris_media2()` queries audio encoder configs and returns normalized encoding/bitrate/sample-rate fields. |
| H.265 live playback | ✅ | go2rtc handles transcoding from H.265 RTSP to WebRTC |
| Metadata configuration discovery | ✅ | `get_stream_uris_media2()` queries metadata configurations and exposes whether camera metadata is supported. |
| Metadata stream URI discovery | ✅ | `get_metadata_stream_uri()` discovers metadata-capable Media2/Media1 profiles and is exposed by `GET /api/cameras/{id}/onvif/metadata-stream`. |
| Metadata streaming (video analytics events) | ⚠ partial | `onvif_metadata.py` parses ONVIF metadata XML frames/notifications into generic `onvif_metadata` events. Live RTSP packet extraction from camera streams still needs lab validation. |
| Rule Engine (analytics rules via ONVIF) | ❌ | Target for Profile M interoperability where cameras expose rules/events. |
| PTZ Relative/Absolute move (Profile T extension) | ⚠ partial | Only ContinuousMove implemented. RelativeMove / AbsoluteMove not yet supported. |

---

## Profile G — Recording (onboard camera storage)

| Capability | Status | Notes / File:Line |
|---|---|---|
| Recording service (camera-side) | ⚠ partial | `search_recordings()` uses `GetRecordings()` for recording inventory when available. Exposed by `GET /api/cameras/{id}/onvif/recordings` and ONVIF page Edge tab; conformance coverage still pending. |
| Replay service | ⚠ partial | `get_replay_uri()` calls Profile G Replay `GetReplayUri()` for a recording token. Exposed by `POST /api/cameras/{id}/onvif/replay-uri`; Edge tab can resolve/copy replay URIs. |
| Search service | ⚠ partial | `search_recordings()` uses Search service `FindRecordings()` + `GetRecordingSearchResults()` fallback for ANR/edge recording backfill and UI/API listing. |

---

## Profile M — Metadata and Events

| Capability | Status | Notes / File:Line |
|---|---|---|
| Metadata configuration discovery | ✅ | Media2 metadata configs are normalized during stream discovery. |
| Metadata stream URI retrieval | ✅ | Metadata-capable Media2/Media1 profile URI discovery is implemented and visible in the Events tab. |
| Event/property mapping | ⚠ partial | PullPoint events exist in `onvif_event_service.py`; known alarm topics map to NVR event types and unknown analytics/rule topics are stored as generic `onvif_metadata` events with JSON-safe source/data/element payloads. |
| Rule and analytics metadata client support | ⚠ partial | XML parser preserves object IDs, bounding boxes, classifications, topics, source items, and data items as generic metadata. Internal AI inference remains deferred. |

---

## Summary

- **Profile S**: ✅ Strong coverage except BaseNotification push (partial).
- **Profile T**: ✅ Media2 + H.265 streaming and audio/metadata configuration discovery. ⚠ Metadata RTSP parsing not yet implemented.
- **Profile G**: ⚠ Client-side recording inventory/search/replay helpers, backend APIs, and Edge tab UI exist for ANR/edge storage; vendor conformance coverage is still pending.
- **Profile M**: ⚠ PullPoint foundation, generic analytics metadata preservation, metadata stream URI discovery, and XML metadata parser exist; live RTSP extraction requires vendor lab validation.

### Known Gaps & TODOs

1. **BaseNotification push receiver** — Cameras that push events rather than waiting for PullPoint subscription. Would require adding a WS-BaseNotification HTTP listener endpoint.
2. **PTZ RelativeMove / AbsoluteMove** — Profile T cameras may expose these. Implement in `onvif_service.py`.
3. **Profile G Recording/Search/Replay hardening** — Add vendor conformance coverage and lab validation for camera-side edge recordings.
4. **Profile M metadata client** — Validate live RTSP metadata extraction against cameras that emit Profile M/T metadata.
5. **WebRTC publish / go2rtc backchannel** — Full browser-to-camera WebRTC two-way audio requires go2rtc `?backchannel=1` source URL. Currently using FFmpeg-based RTSP fallback. Backend endpoint `/audio/backchannel/start` is ready; WebRTC publish client not yet wired.
