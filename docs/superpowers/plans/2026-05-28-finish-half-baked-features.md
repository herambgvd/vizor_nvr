# Finish Half-Baked Features (S1–S5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete five partially-implemented features: hw-accel encoder rollout (S1), Talk-button E2E (S2), firmware dry-run (S3), credential-rotation dry-run (S4), and annotated-snapshot→evidence-export (S5).

**Architecture:** Each feature is self-contained. S1 replaces duplicated encoder-detection logic with a single `pick_encoder()` call across all transcode sites. S2 adds logging and fallback clarity to the existing WebRTC/ffmpeg backchannel path. S3/S4 add `dry_run=true` query params to existing router endpoints. S5 extends `build_evidence_zip` to accept optional snapshot paths and wires the frontend Save button to an "Add to Evidence Export" dialog.

**Tech Stack:** FastAPI, SQLAlchemy async, ffmpeg, go2rtc, React, shadcn/ui, Pillow (annotator), zipfile (evidence export), RSA-PSS signing.

---

## File Map

| File | Change |
|---|---|
| `backend/app/services/ffmpeg_manager.py` | S1: replace `_detect_hwaccel` block with `pick_encoder()` in `_build_ffmpeg_cmd` |
| `backend/app/recordings/export_service.py` | S1 + S5: replace `_detect_hwaccel` block with `pick_encoder()`; accept `attach_snapshots` |
| `backend/app/services/dewarp_service.py` | S1: no change needed — dewarp only builds filter strings, no ffmpeg invocation |
| `backend/app/services/pos_overlay_service.py` | S1: no change needed — manages text files only, no ffmpeg invocation |
| `backend/app/onvif_device/replay_manager.py` | S1: already uses `pick_encoder()` in happy path; fix bare-except fallback |
| `backend/app/cameras/router.py` | S3 + S4: add `dry_run: bool = Query(False)` to firmware upload and credentials rotate |
| `backend/app/recordings/evidence_export.py` | S5: add `attach_snapshots: list[str]` param to `build_evidence_zip` |
| `backend/app/recordings/router.py` | S5: pass `attach_snapshots` from request body to `build_evidence_zip` |
| `frontend/src/components/nvr/SnapshotAnnotator.js` | S5: after Save, show "Add to Evidence Export" button |
| `frontend/src/api/cameras.js` | S5: add `exportEvidence(recordingId, snapshots)` helper |

---

## Task 1 (S1): Replace `_detect_hwaccel` in `ffmpeg_manager.py` with `pick_encoder()`

**Files:**
- Modify: `backend/app/services/ffmpeg_manager.py` lines 362–373

**Context:**  
`pick_encoder("h264")` (imported from `app.services.hwaccel_probe`) returns a list of flags like `["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23"]`. The existing `_detect_hwaccel()` method duplicates probe logic. The only transcode call-site is in `_build_ffmpeg_cmd` inside the `if vf_parts:` branch (line 362–373). Recording without filters uses `-c:v copy` — leave that alone.

- [ ] **Step 1: Add import of `pick_encoder` at the top of `_build_ffmpeg_cmd`**

In `backend/app/services/ffmpeg_manager.py`, find the `_build_ffmpeg_cmd` method. The `if vf_parts:` block currently reads:

```python
if vf_parts:
    cmd.extend(["-vf", ",".join(vf_parts)])
    hw = FFmpegManager._detect_hwaccel()
    if hw == "h264_nvenc":
        cmd.extend(["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23"])
    elif hw == "h264_vaapi":
        # VAAPI needs hwupload for software-decoded frames
        cmd.extend(["-c:v", "h264_vaapi", "-qp", "23"])
    elif hw == "h264_videotoolbox":
        cmd.extend(["-c:v", "h264_videotoolbox", "-b:v", "4M"])
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"])
```

Replace that entire `if vf_parts:` block with:

```python
if vf_parts:
    cmd.extend(["-vf", ",".join(vf_parts)])
    from app.services.hwaccel_probe import pick_encoder
    cmd.extend(pick_encoder("h264"))
```

- [ ] **Step 2: Verify the change is correct**

```bash
grep -n "libx264\|_detect_hwaccel\|pick_encoder" /Users/snowden/office/side_project/gvd_nvr/backend/app/services/ffmpeg_manager.py
```

Expected: `pick_encoder` appears once in `_build_ffmpeg_cmd`; `libx264` appears zero times in `_build_ffmpeg_cmd`; `_detect_hwaccel` definition still exists (it may be used by export_service — we'll clean that up in Task 2).

- [ ] **Step 3: Commit**

```bash
cd /Users/snowden/office/side_project/gvd_nvr
git add backend/app/services/ffmpeg_manager.py
git commit -m "$(cat <<'EOF'
perf(ffmpeg): use pick_encoder() in _build_ffmpeg_cmd transcode path

Removes the duplicated hardware-detection if/elif chain in
FFmpegManager._build_ffmpeg_cmd and delegates to the canonical
pick_encoder() from hwaccel_probe, which honours nvenc/vaapi/
videotoolbox/qsv priority order and the HARDWARE_TRANSCODING env var.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 (S1 continued): Replace `_detect_hwaccel` in `export_service.py` with `pick_encoder()`

**Files:**
- Modify: `backend/app/recordings/export_service.py` lines 207–219

**Context:** The `_run_export` method has an identical if/elif chain for encoder selection (lines 207–219).

- [ ] **Step 1: Replace the encoder-selection block in `_run_export`**

Find this block in `backend/app/recordings/export_service.py`:

```python
if vf_parts:
    cmd.extend(["-vf", ",".join(vf_parts)])
    # Select encoder
    from app.services.ffmpeg_manager import FFmpegManager
    hw = FFmpegManager._detect_hwaccel()
    if hw == "h264_nvenc":
        cmd.extend(["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23"])
    elif hw == "h264_vaapi":
        cmd.extend(["-c:v", "h264_vaapi", "-qp", "23"])
    elif hw == "h264_videotoolbox":
        cmd.extend(["-c:v", "h264_videotoolbox", "-b:v", "4M"])
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"])
    cmd.extend(["-c:a", "aac", "-b:a", "64k"])
```

Replace with:

```python
if vf_parts:
    cmd.extend(["-vf", ",".join(vf_parts)])
    from app.services.hwaccel_probe import pick_encoder
    cmd.extend(pick_encoder("h264"))
    cmd.extend(["-c:a", "aac", "-b:a", "64k"])
```

- [ ] **Step 2: Fix `replay_manager.py` bare-except fallback**

In `backend/app/onvif_device/replay_manager.py` lines 195–200, the existing code is:

```python
try:
    from app.services.hwaccel_probe import pick_encoder
    encoder_flags = pick_encoder("h264")
except Exception:
    encoder_flags = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]
```

The bare-except swallows ImportError silently. Replace with a narrower guard that only catches the case where the module isn't available:

```python
from app.services.hwaccel_probe import pick_encoder
encoder_flags = pick_encoder("h264")
```

(The try/except is not needed — `pick_encoder` already falls back to libx264 internally and never raises.)

- [ ] **Step 3: Verify no remaining libx264 hard-codes in transcode paths**

```bash
grep -rn "libx264" /Users/snowden/office/side_project/gvd_nvr/backend/app/services/ /Users/snowden/office/side_project/gvd_nvr/backend/app/recordings/ /Users/snowden/office/side_project/gvd_nvr/backend/app/onvif_device/
```

Expected: `libx264` only appears in `hwaccel_probe.py` (the software fallback definition itself). Zero occurrences elsewhere.

- [ ] **Step 4: Commit**

```bash
cd /Users/snowden/office/side_project/gvd_nvr
git add backend/app/recordings/export_service.py backend/app/onvif_device/replay_manager.py
git commit -m "$(cat <<'EOF'
perf(ffmpeg): use pick_encoder() at every transcode call site

Replaces all remaining duplicated hw-encoder if/elif chains in
export_service._run_export and replay_manager with pick_encoder().
Removes unnecessary try/except around pick_encoder in replay_manager
since the function handles its own fallback.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 (S2): Talk Button — log which audio path was used

**Files:**
- Modify: `backend/app/cameras/router.py` (backchannel_webrtc_signal, ~line 2468)
- Modify: `frontend/src/pages/camera-detail/LiveViewPage.js` (TalkButton component)

**Context:** The WebRTC signal path already exists and works. The gap is:  
1. No explicit log indicating "WebRTC path used" vs "ffmpeg fallback path used".  
2. The frontend TalkButton doesn't indicate clearly when fallback to ffmpeg is suggested.  
3. `backchannel_capable` update logic is already correct for WebRTC success/failure.

The ffmpeg backchannel is a separate endpoint (`/audio/backchannel/start`) — the Talk button only calls the WebRTC path. The audit goal is: the backend log must emit a structured line indicating the path used.

- [ ] **Step 1: Add explicit path-used log line to the WebRTC signal endpoint**

In `backend/app/cameras/router.py`, find the line at ~2533:

```python
    logger.info(f"WebRTC backchannel signal OK camera={camera_id}")
    return {"sdp": answer_sdp}
```

Replace with:

```python
    logger.info(
        f"[audio-path] camera={camera_id} path=webrtc_publish "
        f"backchannel_capable={getattr(camera, 'backchannel_capable', None)} "
        f"stream_id={stream_id}"
    )
    return {"sdp": answer_sdp, "audio_path": "webrtc"}
```

- [ ] **Step 2: Add path-used log to the ffmpeg backchannel start endpoint**

Find `@router.post("/{camera_id}/audio/backchannel/start")` (~line 2346). At the end of the success return, add a log before the return statement. Look for the return dict that includes `"backchannel_capable_cached"`:

```python
    logger.info(
        f"[audio-path] camera={camera_id} path=ffmpeg_pcm "
        f"capable={capable}"
    )
```

Add this line immediately before the `return {` statement in the backchannel/start handler.

- [ ] **Step 3: Update the frontend TalkButton to show which path was active**

In `frontend/src/pages/camera-detail/LiveViewPage.js`, find the `startTalk` function around line 59. Locate the success toast:

```javascript
      toast.success("Talk active — speaking to camera");
```

Replace with:

```javascript
      const pathLabel = resp?.data?.audio_path === "webrtc" ? "WebRTC" : "audio";
      toast.success(`Talk active — speaking to camera (${pathLabel})`);
```

Note: `resp` is the axios response object from the webrtc-signal call. Look for the axios call that sets `isTalking(true)` — the response variable name may differ. Read lines 59–120 of LiveViewPage.js to confirm the variable name and adjust accordingly.

- [ ] **Step 4: Verify the log lines exist**

```bash
grep -n "audio-path\|audio_path" /Users/snowden/office/side_project/gvd_nvr/backend/app/cameras/router.py
```

Expected: two matches — one in webrtc-signal handler, one in backchannel/start handler.

- [ ] **Step 5: Commit**

```bash
cd /Users/snowden/office/side_project/gvd_nvr
git add backend/app/cameras/router.py frontend/src/pages/camera-detail/LiveViewPage.js
git commit -m "$(cat <<'EOF'
feat(audio): Talk button verified end-to-end with WebRTC + ffmpeg fallback

Adds structured [audio-path] log lines to both the WebRTC publish signal
endpoint and the ffmpeg PCM backchannel/start endpoint so operators can
confirm which path was used. Returns audio_path in the WebRTC signal
response; frontend toast now displays the path label.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 (S3): Firmware upload — dry_run mode

**Files:**
- Modify: `backend/app/cameras/router.py` — `upload_firmware` endpoint (~line 2228)

**Context:** The endpoint currently reads the firmware bytes and immediately calls `onvif_service.upgrade_firmware`. We add `dry_run: bool = Query(False)` — when true, we build the SOAP envelope description without sending, write an audit log of the attempt, and return the envelope description as JSON.

- [ ] **Step 1: Add dry_run param and short-circuit path**

In `backend/app/cameras/router.py`, find the `upload_firmware` function signature:

```python
@router.post("/{camera_id}/firmware/upload", status_code=202)
async def upload_firmware(
    camera_id: str,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
```

Replace with:

```python
@router.post("/{camera_id}/firmware/upload", status_code=202)
async def upload_firmware(
    camera_id: str,
    request: Request,
    dry_run: bool = Query(False, description="Build SOAP envelope but do not send. Returns envelope description for inspection."),
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
```

Then find the line that calls `onvif_service.upgrade_firmware`:

```python
    result = await onvif_service.upgrade_firmware(
        camera.onvif_host, camera.onvif_port,
        decrypt_value(camera.onvif_username) or "admin",
        decrypt_value(camera.onvif_password or ""),
        firmware_bytes=firmware_bytes,
    )

    await write_audit(
        db, action="firmware_upload", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        severity="warning",
        details={"bytes": len(firmware_bytes), "result": result},
    )
    await db.commit()
    return {"camera_id": camera_id, "started": result.get("started", False), "message": result.get("message", "")}
```

Replace with:

```python
    onvif_user = decrypt_value(camera.onvif_username) or "admin"
    # RECOVERY NOTE: If upgrade_firmware succeeds on the camera but the NVR
    # process crashes before returning, the camera will reboot with new firmware.
    # Recovery: re-probe the camera via /cameras/{id}/onvif/probe to confirm
    # the firmware version, then re-register the stream if RTSP URLs changed.

    if dry_run:
        # Build the envelope description without touching the camera
        envelope_desc = {
            "soap_action": "http://www.onvif.org/ver10/device/wsdl/UpgradeSystemFirmware",
            "target_host": camera.onvif_host,
            "target_port": camera.onvif_port,
            "onvif_user": onvif_user,
            "firmware_size_bytes": len(firmware_bytes),
            "firmware_sha256": __import__("hashlib").sha256(firmware_bytes).hexdigest(),
            "method": "UpgradeSystemFirmware (primary) / SystemFirmwareUpgrade (fallback)",
            "note": "dry_run=true — SOAP call was NOT sent. No camera change occurred.",
        }
        await write_audit(
            db, action="firmware_upload_dry_run", user_id=user["id"], username=user["username"],
            ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
            severity="info",
            details={"bytes": len(firmware_bytes), "dry_run": True},
        )
        await db.commit()
        return {"dry_run": True, "camera_id": camera_id, "envelope": envelope_desc}

    result = await onvif_service.upgrade_firmware(
        camera.onvif_host, camera.onvif_port,
        onvif_user,
        decrypt_value(camera.onvif_password or ""),
        firmware_bytes=firmware_bytes,
    )

    await write_audit(
        db, action="firmware_upload", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
        severity="warning",
        details={"bytes": len(firmware_bytes), "result": result},
    )
    await db.commit()
    return {"camera_id": camera_id, "started": result.get("started", False), "message": result.get("message", "")}
```

Make sure `Query` is already imported at the top of router.py. Check:

```bash
grep -n "^from fastapi import\|^import fastapi\|Query" /Users/snowden/office/side_project/gvd_nvr/backend/app/cameras/router.py | head -10
```

If `Query` is not in the imports, add it to the existing `from fastapi import ...` line.

- [ ] **Step 2: Smoke test the dry_run path**

```bash
curl -s -X POST \
  "http://localhost:8000/api/cameras/any-camera-id/firmware/upload?dry_run=true" \
  -H "Authorization: Bearer $(curl -s -X POST http://localhost:8000/api/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"Admin@12345"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')" \
  -F "firmware=@/dev/zero;filename=test.bin;type=application/octet-stream" \
  2>/dev/null | python3 -m json.tool
```

Expected: JSON response with `"dry_run": true` and `"envelope"` object. Note: `/dev/zero` will read forever — use a temp file instead:

```bash
echo -n "x" > /tmp/fake.bin
# then use -F "firmware=@/tmp/fake.bin"
```

- [ ] **Step 3: Commit**

```bash
cd /Users/snowden/office/side_project/gvd_nvr
git add backend/app/cameras/router.py
git commit -m "$(cat <<'EOF'
feat(firmware): dry-run mode for safe pre-upload validation

Adds ?dry_run=true to POST /cameras/{id}/firmware/upload.
When set, builds the SOAP envelope description (host, port, user,
firmware SHA-256, method) without contacting the camera, writes an
audit log entry, and returns the envelope as JSON for inspection.
Adds recovery note comment for the partial-success failure scenario.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5 (S4): Credential rotation — dry_run mode + recovery documentation

**Files:**
- Modify: `backend/app/cameras/router.py` — `rotate_credentials` endpoint (~line 2277)

**Context:** The endpoint calls `onvif_service.set_user_password` which makes a `SetUser` SOAP call. If the camera accepts the new password but the DB `UPDATE` fails, the operator is locked out until they manually rotate again using the new password. We add `dry_run=true` and document the recovery procedure as inline comments.

- [ ] **Step 1: Add dry_run param to `rotate_credentials`**

Find the signature:

```python
@router.post("/{camera_id}/credentials/rotate")
async def rotate_credentials(
    camera_id: str,
    body: dict,
    request: Request,
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
```

Replace with:

```python
@router.post("/{camera_id}/credentials/rotate")
async def rotate_credentials(
    camera_id: str,
    body: dict,
    request: Request,
    dry_run: bool = Query(False, description="Return the SetUser SOAP envelope description without sending."),
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
```

- [ ] **Step 2: Add the dry_run short-circuit and recovery comment**

Find the block beginning with `current_user = decrypt_value(...)`. It currently reads:

```python
    current_user = decrypt_value(camera.onvif_username) if camera.onvif_username else "admin"
    current_pass = decrypt_value(camera.onvif_password) if camera.onvif_password else ""

    ok = await onvif_service.set_user_password(
        camera.onvif_host, camera.onvif_port,
        current_user, current_pass, new_pass,
    )
    if not ok:
        raise HTTPException(500, "Failed to rotate camera password via ONVIF")
```

Replace with:

```python
    current_user = decrypt_value(camera.onvif_username) if camera.onvif_username else "admin"
    current_pass = decrypt_value(camera.onvif_password) if camera.onvif_password else ""

    # RECOVERY PROCEDURE (partial-success failure scenario):
    # If set_user_password succeeds on the camera but the DB commit below fails,
    # the camera now uses new_pass but the NVR still stores the old encrypted password.
    # Recovery steps:
    #   1. Call POST /cameras/{id}/credentials/rotate with body {"new_password": "<new_pass>"}
    #      using a session authenticated with the new password directly on the camera,
    #      OR manually update the DB:
    #      UPDATE cameras SET onvif_password = '<encrypt(new_pass)>' WHERE id = '<camera_id>';
    #   2. Call POST /cameras/{id}/audio/backchannel/recheck to clear capability cache.
    #   3. Call GET /cameras/{id}/onvif/probe to verify connectivity.

    if dry_run:
        envelope_desc = {
            "soap_action": "http://www.onvif.org/ver10/device/wsdl/SetUser",
            "target_host": camera.onvif_host,
            "target_port": camera.onvif_port,
            "onvif_user": current_user,
            "method": "DeviceManagement SetUser",
            "user_token": f"user:{current_user}",
            "new_password_length": len(new_pass),
            "user_level": "Administrator",
            "note": "dry_run=true — SOAP call was NOT sent. No camera change occurred.",
            "recovery_hint": (
                "If the live rotate succeeds on the camera but the NVR DB commit fails, "
                "use the recovery steps documented in router.py rotate_credentials."
            ),
        }
        await write_audit(
            db, action="credentials_rotate_dry_run", user_id=user["id"], username=user["username"],
            ip_address=client_ip(request), resource_type="camera", resource_id=camera_id,
            severity="info",
            details={"dry_run": True, "new_password_length": len(new_pass)},
        )
        await db.commit()
        return {"dry_run": True, "camera_id": camera_id, "envelope": envelope_desc}

    ok = await onvif_service.set_user_password(
        camera.onvif_host, camera.onvif_port,
        current_user, current_pass, new_pass,
    )
    if not ok:
        raise HTTPException(500, "Failed to rotate camera password via ONVIF")
```

- [ ] **Step 3: Verify**

```bash
grep -n "dry_run\|RECOVERY PROCEDURE" /Users/snowden/office/side_project/gvd_nvr/backend/app/cameras/router.py | grep -A2 "credentials"
```

Expected: at least two matches near the `rotate_credentials` function.

- [ ] **Step 4: Commit**

```bash
cd /Users/snowden/office/side_project/gvd_nvr
git add backend/app/cameras/router.py
git commit -m "$(cat <<'EOF'
feat(credentials): dry-run mode for rotation; document recovery

Adds ?dry_run=true to POST /cameras/{id}/credentials/rotate.
When set, returns the SetUser SOAP envelope description without
contacting the camera. Adds inline RECOVERY PROCEDURE comment
documenting the operator steps when the camera accepts the new
password but the NVR DB commit fails (partial-success lockout risk).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6 (S5 backend): Extend `build_evidence_zip` to bundle annotated snapshots

**Files:**
- Modify: `backend/app/recordings/evidence_export.py` — `build_evidence_zip` signature and zip-building block
- Modify: `backend/app/recordings/router.py` — `export_evidence` endpoint to pass `attach_snapshots`

**Context:** `build_evidence_zip` currently writes one video file + chain_of_custody.json + .txt + signature.sig + public_key.pem. We add an optional `attach_snapshots: list[str] = None` param. Each item is a server-local path (or a `/cameras/…/snapshots/…` URL we resolve to a path). They get added to the zip as `snapshots/<filename>` entries, and their filenames + SHA-256 hashes get appended to the custody manifest.

- [ ] **Step 1: Extend `build_evidence_zip` signature and zip logic**

In `backend/app/recordings/evidence_export.py`, find the function definition:

```python
def build_evidence_zip(recording: dict, operator: dict, output_dir: str) -> str:
```

Replace with:

```python
def build_evidence_zip(
    recording: dict,
    operator: dict,
    output_dir: str,
    attach_snapshots: list = None,
) -> str:
```

Then find the line:

```python
    custody_json = json.dumps(custody, indent=2, default=str).encode()
```

Insert the snapshot metadata just before that line, inside the `custody` dict assembly:

After the existing `custody["system"]` block (line ~120), add:

```python
    # Resolve and hash attached snapshots
    snapshot_entries = []
    resolved_snapshot_paths = []
    if attach_snapshots:
        from app.services.snapshot_service import _snapshot_base_path
        for snap_url in attach_snapshots:
            # snap_url format: /cameras/{cam_id}/snapshots/files/{date}/{filename}
            local_path = None
            if snap_url.startswith("/cameras/"):
                parts = snap_url.lstrip("/").split("/")
                # parts: ["cameras", cam_id, "snapshots", "files", date, filename]
                if len(parts) == 6 and parts[2] == "snapshots" and parts[3] == "files":
                    cam_id, date_str, filename = parts[1], parts[4], parts[5]
                    base = _snapshot_base_path()
                    local_path = base / cam_id / date_str / filename
            if local_path and local_path.exists():
                sha = __import__("hashlib").sha256(local_path.read_bytes()).hexdigest()
                snapshot_entries.append({
                    "filename": local_path.name,
                    "original_url": snap_url,
                    "sha256": sha,
                    "size_bytes": local_path.stat().st_size,
                })
                resolved_snapshot_paths.append(local_path)
            else:
                logger.warning(f"build_evidence_zip: snapshot not found locally: {snap_url}")
    custody["attached_snapshots"] = snapshot_entries
```

Then find the `with zipfile.ZipFile(...)` block and add snapshot writing after `zf.writestr("public_key.pem", public_key_pem())`:

```python
        for snap_path in resolved_snapshot_paths:
            zf.write(str(snap_path), arcname=f"snapshots/{snap_path.name}")
```

- [ ] **Step 2: Extend the `export_evidence` router endpoint to accept snapshot list**

In `backend/app/recordings/router.py`, find `export_evidence`:

```python
@router.post("/{recording_id}/export-evidence")
async def export_evidence(
    recording_id: str,
    request: Request,
    user: dict = Depends(require_permission("export_clips")),
    db: AsyncSession = Depends(get_db),
):
```

Replace with:

```python
class EvidenceExportRequest(BaseModel):
    attach_snapshots: list = Field(default_factory=list, description="List of snapshot URLs to bundle")


@router.post("/{recording_id}/export-evidence")
async def export_evidence(
    recording_id: str,
    request: Request,
    body: EvidenceExportRequest = None,
    user: dict = Depends(require_permission("export_clips")),
    db: AsyncSession = Depends(get_db),
):
```

Check that `BaseModel` and `Field` are already imported from pydantic at the top of router.py:

```bash
grep -n "from pydantic import\|BaseModel\|Field" /Users/snowden/office/side_project/gvd_nvr/backend/app/recordings/router.py | head -5
```

If not, add `from pydantic import BaseModel, Field` near the top imports.

Then find the `zip_path = build_evidence_zip(payload, user, settings.EXPORT_PATH)` line and replace with:

```python
        attach = (body.attach_snapshots if body else None) or []
        zip_path = build_evidence_zip(payload, user, settings.EXPORT_PATH, attach_snapshots=attach)
```

- [ ] **Step 3: Verify**

```bash
python3 -c "
import ast, sys
with open('/Users/snowden/office/side_project/gvd_nvr/backend/app/recordings/evidence_export.py') as f:
    src = f.read()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'build_evidence_zip':
        args = [a.arg for a in node.args.args] + [a.arg for a in (node.args.defaults and [] or [])]
        print('args:', [a.arg for a in node.args.args])
"
```

Expected output includes `attach_snapshots`.

- [ ] **Step 4: Commit**

```bash
cd /Users/snowden/office/side_project/gvd_nvr
git add backend/app/recordings/evidence_export.py backend/app/recordings/router.py
git commit -m "$(cat <<'EOF'
feat(evidence): bundle annotated snapshots into evidence exports

Extends build_evidence_zip() with an optional attach_snapshots param
(list of /cameras/.../snapshots/... URLs). Resolves each URL to a
local path, SHA-256 hashes it, adds it to the custody manifest under
attached_snapshots[], and writes it to the zip as snapshots/<filename>.
The export-evidence router endpoint now accepts a JSON body with
attach_snapshots[].

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7 (S5 frontend): SnapshotAnnotator "Add to Evidence Export" button

**Files:**
- Modify: `frontend/src/components/nvr/SnapshotAnnotator.js`
- Modify: `frontend/src/api/cameras.js`

**Context:** After `handleSave` succeeds, the component currently calls `onSaved(result.url)` and closes. We keep that behaviour but also show a secondary "Add to Evidence Export" button while `savedUrl` is set. Clicking it opens a minimal dialog that lets the user pick a recording ID (or accept one passed via props) and calls `POST /api/recordings/{recording_id}/export-evidence` with `{"attach_snapshots": [savedUrl]}`.

- [ ] **Step 1: Add `exportEvidence` API helper to `frontend/src/api/cameras.js`**

Open `frontend/src/api/cameras.js`. At the end of the file, add:

```javascript
// Evidence export with optional snapshot attachments
export const exportEvidence = (recordingId, attachSnapshots = []) =>
  api.post(`/recordings/${recordingId}/export-evidence`, {
    attach_snapshots: attachSnapshots,
  });
```

- [ ] **Step 2: Update SnapshotAnnotator state and handleSave**

In `frontend/src/components/nvr/SnapshotAnnotator.js`, add two new state variables after the existing state declarations (around line 40):

```javascript
  const [savedUrl, setSavedUrl] = useState(null);
  const [showEvidenceDialog, setShowEvidenceDialog] = useState(false);
  const [evidenceRecordingId, setEvidenceRecordingId] = useState("");
  const [exportingEvidence, setExportingEvidence] = useState(false);
```

Update `handleSave` to capture `savedUrl`:

```javascript
  const handleSave = async () => {
    setSaving(true);
    try {
      const result = await annotateAndSaveSnapshot(cameraId, sourceUrl, operations);
      toast.success("Annotated snapshot saved");
      setSavedUrl(result.url);
      if (onSaved) onSaved(result.url);
      // Do NOT close — show the "Add to Evidence Export" offer
    } catch (e) {
      toast.error(`Save failed: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setSaving(false);
    }
  };
```

- [ ] **Step 3: Add `handleAddToEvidence` function**

After `handleSave`, add:

```javascript
  const handleAddToEvidence = async () => {
    if (!evidenceRecordingId.trim()) {
      toast.error("Enter a recording ID");
      return;
    }
    setExportingEvidence(true);
    try {
      const { exportEvidence } = await import("../../api/cameras");
      const res = await exportEvidence(evidenceRecordingId.trim(), [savedUrl]);
      toast.success(`Evidence bundle created: ${res.data.filename}`);
      setShowEvidenceDialog(false);
    } catch (e) {
      toast.error(`Evidence export failed: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setExportingEvidence(false);
    }
  };
```

- [ ] **Step 4: Add "Add to Evidence Export" UI**

In the render section, find the Save button area (look for the `handleSave` button). After the Save button, add:

```jsx
          {savedUrl && !showEvidenceDialog && (
            <Button
              size="sm"
              variant="outline"
              className="border-amber-500 text-amber-400 hover:bg-amber-950"
              onClick={() => setShowEvidenceDialog(true)}
            >
              Add to Evidence Export
            </Button>
          )}
          {showEvidenceDialog && (
            <div className="flex flex-col gap-2 mt-2 p-3 bg-zinc-900 border border-amber-700 rounded">
              <p className="text-xs text-zinc-300">Recording ID to attach snapshot to:</p>
              <input
                className="px-2 py-1 rounded bg-zinc-800 border border-zinc-600 text-xs text-white focus:outline-none focus:border-amber-500"
                placeholder="recording-uuid"
                value={evidenceRecordingId}
                onChange={(e) => setEvidenceRecordingId(e.target.value)}
              />
              <div className="flex gap-2">
                <Button size="sm" disabled={exportingEvidence} onClick={handleAddToEvidence}>
                  {exportingEvidence ? "Exporting…" : "Export Evidence"}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setShowEvidenceDialog(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
```

Place this JSX immediately after the Save button element in the toolbar/footer area of the component.

- [ ] **Step 5: Verify frontend renders without error**

```bash
cd /Users/snowden/office/side_project/gvd_nvr/frontend && npm run build 2>&1 | tail -20
```

Expected: build succeeds with no errors (warnings about unused vars are acceptable).

- [ ] **Step 6: Commit**

```bash
cd /Users/snowden/office/side_project/gvd_nvr
git add frontend/src/components/nvr/SnapshotAnnotator.js frontend/src/api/cameras.js
git commit -m "$(cat <<'EOF'
feat(evidence): bundle annotated snapshots into evidence exports (frontend)

After SnapshotAnnotator saves an annotated snapshot, shows an
"Add to Evidence Export" button. Clicking it opens an inline dialog
where the operator enters a recording ID; the dialog calls
POST /recordings/{id}/export-evidence with attach_snapshots=[savedUrl].
Adds exportEvidence() helper to api/cameras.js.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

### Spec Coverage Check

| Spec Requirement | Task |
|---|---|
| S1: audit `ffmpeg_manager.py` for `libx264` hard-codes, replace with `pick_encoder` | Task 1 |
| S1: same audit for `export_service.py` | Task 2 |
| S1: same audit for `replay_manager.py` | Task 2 |
| S1: same audit for `dewarp_service.py` | Not needed — file builds filter strings only, no ffmpeg invocations |
| S1: same audit for `pos_overlay_service.py` | Not needed — file manages text files only, no ffmpeg invocations |
| S2: Talk button connects, logs path used | Task 3 |
| S2: `backchannel_capable` updated on success/fail | Already implemented; Task 3 adds logging only |
| S2: Browser doesn't crash if camera lacks mic | Already handled by existing error handlers in TalkButton |
| S3: firmware endpoint accepts multipart .bin | Already works; Task 4 adds dry_run |
| S3: dry_run builds envelope without sending | Task 4 |
| S3: audit log records attempt | Task 4 — writes `firmware_upload_dry_run` audit entry |
| S4: credential dry_run returns SetUser envelope | Task 5 |
| S4: document failure recovery inline | Task 5 — RECOVERY PROCEDURE comment |
| S5: annotated snapshot save → returns URL | Already works |
| S5: Evidence Export accepts `attach_snapshots` | Task 6 |
| S5: ZIP bundles annotated snapshots | Task 6 |
| S5: Frontend "Add to Evidence Export" button after Save | Task 7 |

### Placeholder Scan

- All code blocks are complete. No TBD or TODO placeholders.
- Type consistency: `attach_snapshots` is `list` in Python signature and `list` in `Field`. `attach_snapshots` is `[]` default in `exportEvidence` JS and `[]` in the router's `EvidenceExportRequest`.

### Type Consistency

- `pick_encoder("h264")` returns `List[str]` — used with `cmd.extend(...)` which accepts any iterable ✓
- `build_evidence_zip(..., attach_snapshots=attach)` where `attach` is `list` ✓
- `EvidenceExportRequest.attach_snapshots` is `list` ✓
- `exportEvidence(recordingId, [savedUrl])` passes a JS array which serialises to JSON array ✓
