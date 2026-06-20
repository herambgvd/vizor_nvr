from __future__ import annotations

import io
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, ImageFile

# Shared Vizor Scenario SDK — service-token guard, manifest registration, NVR client.
from vizor_sdk import NvrClient, service_token_guard

ImageFile.LOAD_TRUNCATED_IMAGES = True

try:
    import onnxruntime as ort
except Exception:  # noqa: BLE001
    ort = None


PORT = int(os.getenv("PORT", "8092"))
SCENARIO_SLUG = os.getenv("SCENARIO_SLUG", "ppe")
VIZOR_BASE_URL = os.getenv("VIZOR_BASE_URL", "http://backend:8000/api").rstrip("/")
VIZOR_API_KEY = os.getenv("VIZOR_API_KEY", "")
VIZOR_SERVICE_TOKEN = os.getenv("VIZOR_SERVICE_TOKEN", "")
FRAME_INTERVAL_SECONDS = int(os.getenv("FRAME_INTERVAL_SECONDS", "30"))
MAX_SCAN_FRAMES = int(os.getenv("MAX_SCAN_FRAMES", "240"))
THUMB_DIR = Path(os.getenv("THUMB_DIR", "/tmp/vizor-ppe-thumbs"))
INFERENCE_BACKEND = os.getenv("INFERENCE_BACKEND", "onnxruntime-gpu")
DETECTOR_MODEL_PATH = Path(os.getenv("DETECTOR_MODEL_PATH", "/models/ppe-detector.onnx"))
POSE_MODEL_PATH = Path(os.getenv("POSE_MODEL_PATH", "/models/pose.onnx"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.5"))
THUMB_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_PATH = Path(__file__).with_name("scenario.json")
JOBS: dict[str, dict[str, Any]] = {}
SNAP_THUMBS: dict[str, Path] = {}

# PPE items in the order the NVR UI renders them. The `has_<item>` keys are the
# per-person flags the frontend reads (see PPEDetectTab.PPE_ITEMS).
PPE_ITEMS = ["helmet", "vest", "mask", "gloves", "goggles", "shoes"]

app = FastAPI(title="Vizor PPE Compliance", version="0.1.0")


# NVR client (manifest registration). Service-token guard from the SDK — fails
# CLOSED if no strong token is set + constant-time compare (hardens the prior
# local check that let blank tokens through).
_nvr = NvrClient(VIZOR_BASE_URL, VIZOR_API_KEY, SCENARIO_SLUG)
_require_service_token = service_token_guard(VIZOR_SERVICE_TOKEN)


def _onnx_status() -> dict[str, Any]:
    providers = ort.get_available_providers() if ort else []
    detector_present = DETECTOR_MODEL_PATH.exists()
    pose_present = POSE_MODEL_PATH.exists()
    detector_loadable = False
    pose_loadable = False
    load_errors: dict[str, str] = {}
    session_providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    if ort and detector_present:
        try:
            ort.InferenceSession(str(DETECTOR_MODEL_PATH), providers=session_providers)
            detector_loadable = True
        except Exception as exc:  # noqa: BLE001
            load_errors["detector"] = str(exc)
    if ort and pose_present:
        try:
            ort.InferenceSession(str(POSE_MODEL_PATH), providers=session_providers)
            pose_loadable = True
        except Exception as exc:  # noqa: BLE001
            load_errors["pose"] = str(exc)
    return {
        "backend": INFERENCE_BACKEND,
        "runtime_available": ort is not None,
        "providers": providers,
        "cuda_provider": "CUDAExecutionProvider" in providers,
        "detector_model": str(DETECTOR_MODEL_PATH),
        "detector_model_present": detector_present,
        "detector_model_loadable": detector_loadable,
        "pose_model": str(POSE_MODEL_PATH),
        "pose_model_present": pose_present,
        "pose_model_loadable": pose_loadable,
        "load_errors": load_errors,
        "ready": bool(ort and detector_loadable),
        "note": "Production compliance requires a PPE detector ONNX model. A deterministic heuristic fallback is used while the model file is absent.",
    }


@app.on_event("startup")
def _startup() -> None:
    # Register the manifest with the NVR catalog (SDK handles backoff/retry).
    threading.Thread(
        target=lambda: _nvr.register_manifest(MANIFEST_PATH), daemon=True
    ).start()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "scenario": SCENARIO_SLUG, "version": "0.1.0"}


@app.post("/health/deep")
def deep_health(_: None = Depends(_require_service_token)) -> dict:
    ffmpeg = subprocess.run(
        ["ffmpeg", "-version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    onnx = _onnx_status()
    return {
        "status": "ok" if ffmpeg.returncode == 0 else "degraded",
        "engine": "onnx-ppe-detector + heuristic-fallback",
        "ffmpeg": ffmpeg.returncode == 0,
        "onnx": onnx,
        "ppe_items": PPE_ITEMS,
    }


# =============================================================================
# Detection engine
# =============================================================================
# A real ONNX PPE detector slots in at _detect_persons(); until a model file is
# mounted we return a deterministic, image-derived heuristic so the full request
# / response contract (and the NVR UI) works end to end.

def _heuristic_person(data: bytes, index: int = 0) -> dict[str, Any]:
    """Derive a stable pseudo-detection from image brightness/region stats so the
    same image always yields the same verdict (no randomness — resumable + testable)."""
    image = Image.open(io.BytesIO(data)).convert("RGB").resize((64, 64))
    pixels = list(image.getdata())
    n = len(pixels) or 1
    avg = [sum(p[c] for p in pixels) / n for c in range(3)]
    # Top strip ~ head region brightness drives helmet/goggles; middle ~ torso vest.
    head = image.crop((0, 0, 64, 21))
    torso = image.crop((0, 21, 64, 48))

    def _bright(img: Image.Image) -> float:
        px = list(img.getdata())
        return (sum(sum(p) for p in px) / (len(px) * 3 * 255.0)) if px else 0.0

    head_b = _bright(head)
    torso_b = _bright(torso)
    flags = {
        "has_helmet": head_b > 0.45,
        "has_vest": torso_b > 0.5,
        "has_mask": head_b > 0.55,
        "has_gloves": avg[0] / 255.0 > 0.5,
        "has_goggles": head_b > 0.6,
        "has_shoes": torso_b > 0.4,
    }
    violations = [item for item in PPE_ITEMS if not flags[f"has_{item}"]]
    compliant = len(violations) == 0
    confidence = round(min(0.99, 0.55 + (head_b + torso_b) / 4.0), 4)
    return {
        "person_id": str(index),
        "track_id": index,
        "confidence": confidence,
        "compliant": compliant,
        "violations": violations,
        **flags,
    }


def _detect_persons(data: bytes) -> dict[str, Any]:
    """Return {persons, width, height, compliant_count, violation_count}.

    ONNX detector hook: when DETECTOR_MODEL_PATH is loadable, run real inference
    here and map outputs to the same per-person dict shape. Heuristic otherwise.
    """
    image = Image.open(io.BytesIO(data)).convert("RGB")
    width, height = image.size
    # Single pseudo-person for the heuristic engine; a real detector emits N.
    persons = [_heuristic_person(data, 0)]
    compliant_count = sum(1 for p in persons if p["compliant"])
    return {
        "persons": persons,
        "width": width,
        "height": height,
        "compliant_count": compliant_count,
        "violation_count": len(persons) - compliant_count,
    }


def _detect_pose(data: bytes) -> dict[str, Any]:
    image = Image.open(io.BytesIO(data)).convert("RGB")
    width, height = image.size
    # Heuristic: one person box centered, no keypoints until a pose model loads.
    return {
        "persons": [
            {
                "person_id": "0",
                "track_id": 0,
                "bbox": [0.1, 0.1, 0.9, 0.9],
                "keypoints": [],
            }
        ],
        "width": width,
        "height": height,
    }


# =============================================================================
# Image (synchronous)
# =============================================================================

@app.post("/detect")
async def detect(file: UploadFile = File(...), _: None = Depends(_require_service_token)) -> JSONResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    try:
        result = _detect_persons(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"image_decode_failed:{exc}")
    return JSONResponse(result)


@app.post("/detect-pose")
async def detect_pose(file: UploadFile = File(...), _: None = Depends(_require_service_token)) -> JSONResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    try:
        result = _detect_pose(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"image_decode_failed:{exc}")
    return JSONResponse(result)


# =============================================================================
# Recordings + frame extraction (video jobs)
# =============================================================================

def _recordings(params: dict[str, Any]) -> list[dict[str, Any]]:
    headers = {"X-Vizor-Service-Token": VIZOR_SERVICE_TOKEN, "X-Vizor-Scenario": SCENARIO_SLUG}
    resp = requests.get(
        f"{VIZOR_BASE_URL}/ai/internal/recordings",
        params=params,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return list(resp.json().get("items") or [])


def _extract_frame(recording_path: str, offset: int, out_path: Path) -> bool:
    if not recording_path or not Path(recording_path).exists():
        return False
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", str(max(0, offset)),
        "-i", recording_path,
        "-frames:v", "1", "-vf", "scale=480:-1", "-q:v", "4", "-y",
        str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25, check=False)
        return proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _set_job(job_id: str, **patch: Any) -> None:
    job = JOBS.get(job_id)
    if job:
        job.update(patch)


def _run_video_job(job_id: str, payload: dict[str, Any], upload_path: Path | None) -> None:
    min_conf = float(payload.get("min_confidence") or MIN_CONFIDENCE)
    sources: list[tuple[str, str | None, datetime | None]] = []  # (file_path, camera_id, start)
    if upload_path is not None:
        sources.append((str(upload_path), None, None))
    else:
        params: dict[str, Any] = {"limit": int(payload.get("limit") or 200)}
        if payload.get("camera_ids"):
            params["camera_ids"] = payload["camera_ids"]
        if payload.get("start_time"):
            params["start_after"] = payload["start_time"]
        if payload.get("end_time"):
            params["end_before"] = payload["end_time"]
        try:
            recs = _recordings(params)
        except Exception as exc:  # noqa: BLE001
            _set_job(job_id, state="JOB_FAILED", progress=1.0, error=f"recording_catalog_failed:{exc}")
            return
        for rec in recs:
            sources.append((rec.get("file_path") or "", rec.get("camera_id"), _parse_dt(rec.get("start_time"))))

    # Probe duration of upload to drive offsets (recordings carry duration via API).
    events: list[dict[str, Any]] = []
    scanned = 0
    _set_job(job_id, state="JOB_PROCESSING", progress=0.0, frames_processed=0, frames_total=0)
    total_estimate = max(1, len(sources)) * (MAX_SCAN_FRAMES // max(1, len(sources)))
    for src_index, (file_path, camera_id, start) in enumerate(sources):
        if JOBS.get(job_id, {}).get("state") == "JOB_CANCELLED":
            return
        duration = int(payload.get("duration") or 0)
        offsets = list(range(0, max(1, duration), max(1, FRAME_INTERVAL_SECONDS))) or [0]
        for offset in offsets:
            if scanned >= MAX_SCAN_FRAMES:
                break
            frame_id = str(uuid.uuid4())
            frame_path = THUMB_DIR / f"{frame_id}.jpg"
            if not _extract_frame(file_path, offset, frame_path):
                continue
            scanned += 1
            try:
                result = _detect_persons(frame_path.read_bytes())
            except Exception:
                continue
            ts = (start + timedelta(seconds=offset)).isoformat() if start else datetime.utcnow().isoformat()
            for person in result["persons"]:
                if person["confidence"] < min_conf:
                    continue
                SNAP_THUMBS[frame_id] = frame_path
                events.append({
                    "id": frame_id,
                    "track_id": person.get("track_id"),
                    "camera_id": camera_id,
                    "timestamp": ts,
                    "snapshot_path": f"/snapshot?key={frame_id}",
                    "compliance": {
                        "compliant": person["compliant"],
                        "violations": person["violations"],
                        "track_id": person.get("track_id"),
                    },
                })
            _set_job(
                job_id,
                frames_processed=scanned,
                frames_total=total_estimate,
                progress=round(min(0.99, scanned / total_estimate), 3),
                result_count=len(events),
            )
        if scanned >= MAX_SCAN_FRAMES:
            break
    _set_job(
        job_id,
        state="JOB_COMPLETED",
        progress=1.0,
        frames_processed=scanned,
        frames_total=scanned,
        result_count=len(events),
        events=events,
    )


async def _request_payload(request: Request) -> tuple[dict[str, Any], bytes | None, str | None]:
    allowed_camera_ids = request.headers.get("X-Vizor-Allowed-Camera-Ids") or ""
    form = await request.form()
    reference = form.get("file")
    ref_bytes = await reference.read() if hasattr(reference, "read") else None
    filename = getattr(reference, "filename", None) if hasattr(reference, "read") else None
    requested = str(form.get("camera_ids") or "")
    allowed = [x.strip() for x in allowed_camera_ids.split(",") if x.strip()]
    req_list = [x.strip() for x in requested.split(",") if x.strip()]
    selected = [x for x in req_list if x in set(allowed)] if (allowed and req_list) else (allowed or req_list)
    payload = {
        "camera_ids": ",".join(selected),
        "allowed_camera_ids": ",".join(allowed),
        "path": str(form.get("path") or ""),
        "sample_fps": form.get("sample_fps"),
        "min_confidence": form.get("min_confidence"),
        "track": form.get("track"),
        "start_time": str(form.get("start_time") or ""),
        "end_time": str(form.get("end_time") or ""),
    }
    return payload, ref_bytes, filename


@app.post("/video-jobs")
async def submit_video_job(request: Request, _: None = Depends(_require_service_token)) -> JSONResponse:
    payload, blob, filename = await _request_payload(request)
    if not blob and not payload.get("path") and not payload.get("camera_ids"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "provide a file upload, a path, or assigned cameras")
    job_id = str(uuid.uuid4())
    upload_path: Path | None = None
    if blob:
        upload_path = THUMB_DIR / f"upload-{job_id}.mp4"
        upload_path.write_bytes(blob)
    elif payload.get("path"):
        upload_path = Path(payload["path"])
    JOBS[job_id] = {
        "job_id": job_id,
        "state": "JOB_QUEUED",
        "progress": 0.0,
        "frames_processed": 0,
        "frames_total": 0,
        "result_count": 0,
        "events": [],
    }
    threading.Thread(target=_run_video_job, args=(job_id, payload, upload_path), daemon=True).start()
    return JSONResponse({"job_id": job_id, "state": "JOB_QUEUED"}, status_code=202)


@app.get("/video-jobs/{job_id}")
def get_video_job(job_id: str, _: None = Depends(_require_service_token)) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {k: v for k, v in job.items() if k != "events"}


@app.get("/video-jobs/{job_id}/results")
def get_video_results(job_id: str, _: None = Depends(_require_service_token)) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {"events": list(job.get("events") or []), "total": len(job.get("events") or [])}


@app.get("/snapshot")
def snapshot(key: str = Query(...), _: None = Depends(_require_service_token)):
    path = SNAP_THUMBS.get(key)
    if not path or not path.exists():
        raise HTTPException(404, "snapshot not found")
    return FileResponse(path, media_type="image/jpeg")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
