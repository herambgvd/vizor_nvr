"""On-demand video analysis — upload a clip, draw an ROI on it, run the full PPE
pipeline, get an annotated video + the detected events back. Lets an operator test
and validate the model (and run a video-file workflow) without a live camera. Service-
token gated via the NVR proxy; ROI + required-PPE come from the request so accuracy
matches a real camera.

Flow:
  1. POST /media/upload   multipart file=<video>           -> {upload_id}
  2. GET  /media/frame    upload_id                         -> first frame JPEG (draw ROI)
  3. POST /media/analyze  upload_id + config(json)          -> {job_id}
  4. GET  /media/status   job_id                            -> progress + events
  5. GET  /media/result   job_id                            -> annotated H.264 mp4
"""
from __future__ import annotations

import json
import uuid

import cv2
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from deps import require_service_token
from live.video_pipeline import _media_dir, delete_job, get_job, list_jobs, start_media_job

router = APIRouter(tags=["media"])

# 500 MB upload cap (also enforced at nginx + uvicorn).
_MAX_BYTES = 500 * 1024 * 1024


def _src_path(upload_id: str):
    if not upload_id.isalnum():
        raise HTTPException(400, "bad upload_id")
    return _media_dir() / f"{upload_id}_src.mp4"


@router.post("/media/upload")
async def media_upload(
    file: UploadFile = File(...),
    _: None = Depends(require_service_token),
) -> dict:
    """Store an uploaded video (<=500 MB). Returns an upload_id for the ROI step +
    analysis."""
    upload_id = uuid.uuid4().hex[:12]
    src = _media_dir() / f"{upload_id}_src.mp4"
    size = 0
    try:
        with src.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > _MAX_BYTES:
                    f.close()
                    src.unlink(missing_ok=True)
                    raise HTTPException(413, "video exceeds the 500 MB limit")
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        src.unlink(missing_ok=True)
        raise HTTPException(400, f"upload failed: {e}")
    if size == 0:
        src.unlink(missing_ok=True)
        raise HTTPException(400, "empty upload")
    # Probe the first frame so the UI gets dimensions immediately.
    cap = cv2.VideoCapture(str(src))
    ok, frame = cap.read()
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    if not ok:
        src.unlink(missing_ok=True)
        raise HTTPException(422, "not a readable video")
    return {"upload_id": upload_id, "bytes": size, "width": w, "height": h,
            "frames": frames, "fps": round(fps or 0, 2)}


@router.get("/media/frame")
def media_frame(upload_id: str = Query(...), _: None = Depends(require_service_token)):
    """First frame as JPEG — the UI draws the ROI on the real scene before analysis."""
    src = _src_path(upload_id)
    if not src.exists():
        raise HTTPException(404, "upload not found")
    cap = cv2.VideoCapture(str(src))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise HTTPException(422, "cannot read first frame")
    enc_ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not enc_ok:
        raise HTTPException(500, "encode failed")
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.post("/media/analyze")
def media_analyze(
    body: dict = Body(...),
    _: None = Depends(require_service_token),
) -> dict:
    """Run the PPE pipeline on a previously uploaded video. body = {upload_id,
    config:{required_items, roi, *_conf, ...}, sample_fps?}. Returns a job_id."""
    upload_id = str(body.get("upload_id") or "")
    src = _src_path(upload_id)
    if not src.exists():
        raise HTTPException(404, "upload not found")
    cam_config = body.get("config") or {}
    sample_fps = int(body.get("sample_fps") or 0)
    name = str(body.get("name") or "video")[:120]
    job_id = start_media_job(str(src), cam_config, sample_fps=sample_fps, name=name)
    return {"job_id": job_id}


@router.get("/media/list")
def media_list(_: None = Depends(require_service_token)) -> dict:
    """Media analysis history — every job (in-flight + finished), newest first."""
    return {"jobs": list_jobs()}


@router.post("/media/delete")
def media_delete(body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    """Completely remove an analysis: result mp4, metadata, and the source upload."""
    job_id = str(body.get("job_id") or "")
    if not job_id.isalnum():
        raise HTTPException(400, "bad job_id")
    delete_job(job_id)
    return {"deleted": job_id}


@router.get("/media/status")
def media_status(job_id: str = Query(...), _: None = Depends(require_service_token)) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return {
        "job_id": job.job_id, "status": job.status, "progress": round(job.progress, 3),
        "frames_total": job.frames_total, "frames_done": job.frames_done,
        "events": job.events, "event_count": len(job.events),
        "annotated_path": job.annotated_path, "error": job.error,
    }


@router.get("/media/result")
def media_result(job_id: str = Query(...), _: None = Depends(require_service_token)):
    job = get_job(job_id)
    if job is None or job.status != "done":
        raise HTTPException(404, "result not ready")
    if not job_id.isalnum():
        raise HTTPException(400, "bad job_id")
    path = _media_dir() / f"{job_id}.mp4"
    if not path.exists():
        raise HTTPException(404, "result file missing")
    return FileResponse(str(path), media_type="video/mp4", filename=f"ppe_{job_id}.mp4")
