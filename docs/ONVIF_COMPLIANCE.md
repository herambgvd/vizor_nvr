# ONVIF Client-Side Compliance Audit

**NVR role:** ONVIF client (talks TO cameras). This document audits our coverage
of ONVIF Profile S, Profile T, and Profile G capabilities as a client.

Last updated: 2026-05-28  
Reference code: `backend/app/cameras/onvif_service.py`, `backend/app/cameras/router.py`

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
| Media2 GetAudioEncoderConfigurations | ⚠ partial | Not yet queried explicitly. `get_stream_uris_media2()` reads VideoEncoderConfiguration; no dedicated audio encoder query. TODO. |
| H.265 live playback | ✅ | go2rtc handles transcoding from H.265 RTSP to WebRTC |
| Metadata streaming (video analytics events) | ❌ | Not implemented as a client. ONVIF metadata streaming requires dedicated MetadataStreamUri + RTSP channel parsing. Out of scope for this batch. |
| Rule Engine (analytics rules via ONVIF) | ❌ | Out of scope. |
| PTZ Relative/Absolute move (Profile T extension) | ⚠ partial | Only ContinuousMove implemented. RelativeMove / AbsoluteMove not yet supported. |

---

## Profile G — Recording (onboard camera storage)

| Capability | Status | Notes / File:Line |
|---|---|---|
| Recording service (camera-side) | ❌ | Out of scope for this batch. The NVR is the recorder; we do not act as a Recording Search client against camera-onboard SD card recordings. Future work. |
| Replay service | ❌ | Out of scope. |
| Search service | ❌ | Out of scope. |

---

## Summary

- **Profile S**: ✅ Full coverage except BaseNotification push (partial).
- **Profile T**: ✅ Media2 + H.265 streaming. ⚠ Audio encoder config + analytics metadata not yet implemented.
- **Profile G**: ❌ Out of scope (NVR is the recorder, not a camera-storage search client).

### Known Gaps & TODOs

1. **BaseNotification push receiver** — Cameras that push events rather than waiting for PullPoint subscription. Would require adding a WS-BaseNotification HTTP listener endpoint.
2. **Media2 GetAudioEncoderConfigurations** — Add explicit query to `get_stream_uris_media2()`.
3. **PTZ RelativeMove / AbsoluteMove** — Profile T cameras may expose these. Implement in `onvif_service.py`.
4. **WebRTC publish / go2rtc backchannel** — Full browser-to-camera WebRTC two-way audio requires go2rtc `?backchannel=1` source URL. Currently using FFmpeg-based RTSP fallback. Backend endpoint `/audio/backchannel/start` is ready; WebRTC publish client not yet wired.
