"""Video-upload PPE compliance — upload a clip, watch it analysed live (MJPEG),
get violation/compliant events into the PPE DB, and replay the annotated result.

Endpoints (all service-token gated, served through the NVR's scenario proxy):
  POST /video/upload                 multipart video + config (roi, required_items, …)
  GET  /video/stream/{job_id}        MJPEG of the latest annotated frame (live)
  GET  /video/status/{job_id}        progress + recent alerts (JSON, polled)
  GET  /video/result/{job_id}        per-worker compliance summary (JSON)
  GET  /video/output/{job_id}        the annotated MP4 (from rustfs, else disk)
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, Response, StreamingResponse

import config
from deps import require_service_token
from live.video_job import VIDEO_JOBS, frame_generator

router = APIRouter(prefix="/video", tags=["video"])

_ALLOWED_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
_UPLOAD_DIR = Path(config.DATA_PATH) / "video_uploads"


@router.post("/upload")
async def upload(
    video: UploadFile = File(...),
    required_items: str = Form("[\"helmet\", \"vest\"]"),
    roi: str = Form(""),
    emit_compliant: bool = Form(False),
    missing_grace: float = Form(None),
    cooldown: float = Form(None),
    _: None = Depends(require_service_token),
):
    ext = Path(video.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(400, f"unsupported video format: {ext or '?'}")

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = _UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    try:
        with dest.open("wb") as f:
            shutil.copyfileobj(video.file, f)
    finally:
        await video.close()

    cfg = {
        "required_items": _parse_json(required_items, ["helmet", "vest"]),
        "roi": _parse_json(roi, None) if roi else None,
        "emit_compliant": bool(emit_compliant),
    }
    if missing_grace is not None:
        cfg["missing_grace"] = missing_grace
    if cooldown is not None:
        cfg["cooldown"] = cooldown

    job = VIDEO_JOBS.start(dest, cfg)
    return {"job_id": job.job_id, "state": job.state}


@router.get("/stream/{job_id}")
def stream(job_id: str, _: None = Depends(require_service_token)):
    if VIDEO_JOBS.get(job_id) is None:
        raise HTTPException(404, "job not found")
    return StreamingResponse(
        frame_generator(job_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/frame/{job_id}")
def frame(job_id: str, _: None = Depends(require_service_token)):
    """Latest annotated frame as a single JPEG. The UI polls this (auth'd via the
    proxy) instead of an MJPEG <img> — MJPEG can't carry the Bearer token."""
    job = VIDEO_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    data = job.get_frame()
    if not data:
        raise HTTPException(404, "no frame yet")
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@router.post("/cancel/{job_id}")
def cancel(job_id: str, _: None = Depends(require_service_token)):
    """Stop a running analysis. The loop breaks at the next frame; whatever events
    were already recorded stay (partial result)."""
    job = VIDEO_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    job.cancel()
    return {"job_id": job_id, "state": "cancelling"}


@router.get("/status/{job_id}")
def status(job_id: str, _: None = Depends(require_service_token)):
    job = VIDEO_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job.status()


@router.get("/result/{job_id}")
def result(job_id: str, _: None = Depends(require_service_token)):
    job = VIDEO_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job.result()


@router.get("/output/{job_id}")
def output(job_id: str, _: None = Depends(require_service_token)):
    job = VIDEO_JOBS.get(job_id)
    if job is None or not job.output_key:
        raise HTTPException(404, "output not ready")
    key = job.output_key
    if key.startswith("local:"):
        path = Path(key[len("local:"):])
        if not path.exists():
            raise HTTPException(404, "output file missing")
        return FileResponse(str(path), media_type="video/mp4",
                            filename=f"{job_id}.mp4")
    # rustfs-stored — stream the bytes back through the app.
    try:
        from vizor_sdk.objectstore import default_store
        data = default_store().get(key)
    except Exception:  # noqa: BLE001
        raise HTTPException(404, "output unavailable")
    return Response(content=data, media_type="video/mp4",
                    headers={"Content-Disposition": f'inline; filename="{job_id}.mp4"'})


def _parse_json(raw: str, default):
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return default
