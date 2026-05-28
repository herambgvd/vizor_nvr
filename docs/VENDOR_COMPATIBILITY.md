# Camera Vendor Compatibility Matrix — GVD NVR

> **Legend**:  
> ✅ verified — tested against GVD NVR in the lab  
> 🟡 expected — standard ONVIF Profile S/T behaviour; not lab-tested against GVD NVR  
> ❓ untested — no data available

---

## Compatibility Matrix

| Vendor | Model | Verified Firmware | ONVIF Discovery | Live View (RTSP) | PTZ | Audio | Backchannel | Events | Imaging | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| **CTOCAM** | GV-3602-K | 3.x | ✅ verified | ✅ verified | ✅ verified | ✅ verified | ✅ verified | ✅ verified | ✅ verified | Primary reference device; all features tested |
| **Hikvision** | DS-2CD2143G2-I | 5.7.x | 🟡 expected | 🟡 expected | 🟡 expected | 🟡 expected | ❓ untested | 🟡 expected | 🟡 expected | Uses ONVIF Profile S+T; ISAPI also available. Digest auth required. Set ONVIF auth mode to "digest" in camera web UI |
| **Hikvision** | DS-2CD2347G2-LU | 5.7.x | 🟡 expected | 🟡 expected | 🟡 expected | 🟡 expected | ❓ untested | 🟡 expected | 🟡 expected | Colour night vision variant; same ONVIF behaviour as DS-2CD series |
| **Dahua** | IPC-HFW2849S-S-IL | V2.82x | 🟡 expected | 🟡 expected | 🟡 expected | 🟡 expected | ❓ untested | 🟡 expected | 🟡 expected | Smart Dual Light. Requires HTTP digest. Default ONVIF port 80 |
| **Dahua** | IPC-HFW3849H-ZAS-PV | V2.82x | 🟡 expected | 🟡 expected | 🟡 expected | 🟡 expected | ❓ untested | 🟡 expected | 🟡 expected | Active deterrence; same ONVIF as IPC-HFW line |
| **Axis** | M3106-L Mk II | 9.x | 🟡 expected | 🟡 expected | ❓ untested | 🟡 expected | ❓ untested | 🟡 expected | 🟡 expected | ONVIF Profile S/G. VAPIX API available alongside ONVIF |
| **Axis** | Q3517-LV | 9.x | 🟡 expected | 🟡 expected | ❓ untested | 🟡 expected | ❓ untested | 🟡 expected | 🟡 expected | Fixed dome; Q-series has strong ONVIF compliance |
| **Bosch** | FLEXIDOME 5100i | 8.x | 🟡 expected | 🟡 expected | 🟡 expected | ❓ untested | ❓ untested | 🟡 expected | 🟡 expected | ONVIF Profile S/T/M. May need manual ONVIF service enable in camera web UI |
| **Pelco** | Sarix IBE329-1I | 1.x | 🟡 expected | 🟡 expected | 🟡 expected | 🟡 expected | ❓ untested | 🟡 expected | 🟡 expected | Sarix Enhanced; Profile S compliant. Some models need port 8080 for ONVIF |
| **Hanwha (Samsung) Wisenet** | QNV-8080R | 2.x | 🟡 expected | 🟡 expected | 🟡 expected | 🟡 expected | ❓ untested | 🟡 expected | 🟡 expected | **Known quirk**: some Wisenet models use port 8080 instead of 80 for ONVIF. Set `onvif_port=8080` when adding camera |
| **Hanwha (Samsung) Wisenet** | XNO-8080R | 2.x | 🟡 expected | 🟡 expected | ❓ untested | 🟡 expected | ❓ untested | 🟡 expected | 🟡 expected | X-series outdoor dome; same ONVIF quirk as QNV line |
| **Uniview** | IPC3614SB-ADF40KM-I0 | 4.x | 🟡 expected | 🟡 expected | ❓ untested | ❓ untested | ❓ untested | 🟡 expected | 🟡 expected | Profile S. ONVIF enabled by default |
| **Vivotek** | IB9367-EHT | AISDK 0.x | 🟡 expected | 🟡 expected | ❓ untested | ❓ untested | ❓ untested | 🟡 expected | 🟡 expected | Smart motion detection via ONVIF events. Dual-band RTSP |
| **Reolink** | RLC-810A | 3.1.x | 🟡 expected | 🟡 expected | ❓ untested | ❓ untested | ❓ untested | ❓ untested | ❓ untested | **Known quirk**: older Reolink firmware has partial ONVIF implementation; disable WS-Discovery if auto-discovery fails. Recommend firmware >= 3.1.0.956 |
| **Amcrest** | IP8M-2493EW | 2.6x.x | 🟡 expected | 🟡 expected | ❓ untested | 🟡 expected | ❓ untested | 🟡 expected | 🟡 expected | OEM Dahua; ONVIF behaviour mirrors Dahua IPC line |
| **Tapo (TP-Link)** | C320WS | 2.x | ❓ untested | ❓ untested | ❓ untested | ❓ untested | ❓ untested | ❓ untested | ❓ untested | **Caution**: consumer-grade; ONVIF support varies by model and is not always enabled by default. Requires Tapo app to enable ONVIF in camera settings. Profile S only |

---

## How to Add a New Vendor

To formally verify a new camera model against GVD NVR, follow these steps and update the matrix above:

### Step 1 — ONVIF Discovery

```bash
# Trigger auto-discovery (ensure NVR and camera are on the same subnet)
curl -X POST https://localhost/api/cameras/discover \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"subnet": "192.168.1.0/24"}' -k
```

Confirm: camera appears in discovery results with correct IP and device info.

### Step 2 — Add Camera and Test Live View

1. Add the discovered camera via UI or API with ONVIF credentials.
2. Open Live View — verify RTSP stream plays without errors.
3. Check go2rtc logs: `docker compose logs go2rtc` — no `RTSP error` lines.

### Step 3 — Test PTZ (if supported)

```bash
curl -X POST https://localhost/api/cameras/{id}/ptz \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "move", "pan": 0.5, "tilt": 0.0, "zoom": 0.0}' -k
```

Confirm: camera physically moves and returns to home position.

### Step 4 — Capture Snapshot

```bash
curl -X POST https://localhost/api/cameras/{id}/snapshot \
  -H "Authorization: Bearer <admin-token>" -k -o /tmp/snapshot.jpg
```

Confirm: JPEG snapshot is valid and timestamped correctly.

### Step 5 — Record 60 Seconds

1. Set recording mode to `manual`.
2. Trigger recording start via UI or `POST /api/cameras/{id}/recording/start`.
3. Wait 60 seconds, stop recording.
4. Verify the recording appears in Playback with correct duration and is playable.

### Step 6 — Verify Event Subscription

1. Enable ONVIF events in camera settings (Imaging → ONVIF Events tab).
2. Trigger a motion alarm in the camera's field of view.
3. Check: `docker compose logs backend | grep onvif_event` — confirm `MotionAlarm` event received.

### Step 7 — Update the Matrix

Once all applicable steps pass:
- Mark cells with **✅ verified** and fill in the confirmed firmware version.
- Add any known quirks to the Notes column.
- Submit a PR with the matrix update.

---

## Notes on ONVIF Profiles

| Profile | Capability |
|---|---|
| Profile S | Streaming (Live RTSP, snapshot, PTZ basics) |
| Profile T | Advanced streaming (H.265, metadata, analytics) |
| Profile G | Storage/recording on-camera |
| Profile M | Analytics and metadata |
| Profile A | Access control |

GVD NVR targets **Profile S** as the minimum baseline and **Profile T** for analytics events.
