"""Async video recognition jobs over uploaded files or assigned recordings.

Extracts frames via ffmpeg, runs recognition per frame, records FRS events +
attendance, and exposes a proto-enum job lifecycle the NVR UI polls.
"""
from __future__ import annotations

import subprocess
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

import config
import recognition
from db import session
from deps import require_service_token
from db.models import FRSAttendance, FRSEvent
from schemas import iso, naive, parse_dt

router = APIRouter(tags=["video-jobs"])

# In-memory job table (jobs are ephemeral; results are also persisted as FRS
# events so the Events/Reports tabs survive a restart).
JOBS: dict[str, dict[str, Any]] = {}


def _recordings(params: dict[str, Any]) -> list[dict[str, Any]]:
    headers = {"X-Vizor-Service-Token": config.VIZOR_SERVICE_TOKEN, "X-Vizor-Scenario": config.SCENARIO_SLUG}
    resp = requests.get(f"{config.VIZOR_BASE_URL}/ai/internal/recordings",
                        params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    return list(resp.json().get("items") or [])


def _extract_frame(recording_path: str, offset: int, out_path: Path) -> bool:
    if not recording_path or not Path(recording_path).exists():
        return False
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(max(0, offset)),
           "-i", recording_path, "-frames:v", "1", "-vf", "scale=480:-1", "-q:v", "4", "-y", str(out_path)]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25, check=False)
        return proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def _set_job(job_id: str, **patch: Any) -> None:
    job = JOBS.get(job_id)
    if job:
        job.update(patch)


def _record_event(camera_id, person_id, person_name, confidence, snapshot_path, ts) -> None:
    event_type = "face_recognized" if person_id else "face_unknown"
    with session() as s:
        ev = FRSEvent(
            camera_id=camera_id, event_type=event_type, severity="info",
            title=person_name or "Unknown face", detection_type="face",
            person_id=person_id, confidence=round(confidence, 4),
            snapshot_path=snapshot_path, triggered_at=naive(ts) or ts,
        )
        s.add(ev)
        if person_id:
            day_key = (ts or datetime.utcnow()).date().isoformat()
            existing = s.scalar(select(FRSAttendance).where(
                FRSAttendance.person_id == person_id, FRSAttendance.day_key == day_key))
            if existing:
                existing.check_out_at = naive(ts)
            else:
                s.add(FRSAttendance(person_id=person_id, camera_id=camera_id, day_key=day_key,
                                    check_in_at=naive(ts), sighting_type="seen", event_id=ev.id))
        s.commit()


def _run_video_job(job_id: str, payload: dict[str, Any], upload_path: Path | None) -> None:
    min_conf = float(payload.get("min_confidence") or config.SIMILARITY_THRESHOLD)
    sources: list[tuple[str, str | None, datetime | None]] = []
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
            sources.append((rec.get("file_path") or "", rec.get("camera_id"), parse_dt(rec.get("start_time"))))

    events: list[dict[str, Any]] = []
    scanned = 0
    _set_job(job_id, state="JOB_PROCESSING", progress=0.0, frames_processed=0, frames_total=0)
    total_estimate = max(1, len(sources)) * (config.MAX_SCAN_FRAMES // max(1, len(sources)))
    for file_path, camera_id, start in sources:
        if JOBS.get(job_id, {}).get("state") == "JOB_CANCELLED":
            return
        duration = int(payload.get("duration") or 0)
        offsets = list(range(0, max(1, duration), max(1, config.FRAME_INTERVAL_SECONDS))) or [0]
        for offset in offsets:
            if scanned >= config.MAX_SCAN_FRAMES:
                break
            frame_id = str(uuid.uuid4())
            frame_path = config.DATA_PATH / "frames" / f"{frame_id}.jpg"
            frame_path.parent.mkdir(parents=True, exist_ok=True)
            if not _extract_frame(file_path, offset, frame_path):
                continue
            scanned += 1
            try:
                rec = recognition.recognize(frame_path.read_bytes(), min_conf=min_conf)
            except Exception:
                continue
            ts = (start + timedelta(seconds=offset)) if start else datetime.utcnow()
            for m in rec["matches"]:
                snap = f"/photos/{m['photo_id']}/image" if m.get("photo_id") else None
                _record_event(camera_id, m["person_id"], m["person_name"], m["confidence"], snap, ts)
                events.append({
                    "id": frame_id, "person_id": m["person_id"], "person_name": m["person_name"],
                    "camera_id": camera_id, "timestamp": iso(ts), "confidence": m["confidence"],
                })
            _set_job(job_id, frames_processed=scanned, frames_total=total_estimate,
                     progress=round(min(0.99, scanned / total_estimate), 3), result_count=len(events))
        if scanned >= config.MAX_SCAN_FRAMES:
            break
    _set_job(job_id, state="JOB_COMPLETED", progress=1.0, frames_processed=scanned,
             frames_total=scanned, result_count=len(events), events=events)


async def _video_payload(request: Request) -> tuple[dict[str, Any], bytes | None]:
    allowed = request.headers.get("X-Vizor-Allowed-Camera-Ids") or ""
    form = await request.form()
    ref = form.get("file")
    blob = await ref.read() if hasattr(ref, "read") else None
    requested = str(form.get("camera_ids") or "")
    allowed_list = [x.strip() for x in allowed.split(",") if x.strip()]
    req_list = [x.strip() for x in requested.split(",") if x.strip()]
    selected = [x for x in req_list if x in set(allowed_list)] if (allowed_list and req_list) else (allowed_list or req_list)
    return {
        "camera_ids": ",".join(selected),
        "path": str(form.get("path") or ""),
        "sample_fps": form.get("sample_fps"),
        "recognize": form.get("recognize"),
        "check_liveness": form.get("check_liveness"),
        "min_confidence": form.get("min_confidence"),
        "start_time": str(form.get("start_time") or ""),
        "end_time": str(form.get("end_time") or ""),
    }, blob


@router.post("/video-jobs")
async def submit_video_job(request: Request, _: None = Depends(require_service_token)) -> JSONResponse:
    payload, blob = await _video_payload(request)
    if not blob and not payload.get("path") and not payload.get("camera_ids"):
        raise HTTPException(400, "provide a file upload, a path, or assigned cameras")
    job_id = str(uuid.uuid4())
    upload_path: Path | None = None
    if blob:
        upload_path = config.DATA_PATH / "uploads" / f"{job_id}.mp4"
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.write_bytes(blob)
    elif payload.get("path"):
        upload_path = Path(payload["path"])
    JOBS[job_id] = {"job_id": job_id, "state": "JOB_QUEUED", "progress": 0.0,
                    "frames_processed": 0, "frames_total": 0, "result_count": 0, "events": []}
    threading.Thread(target=_run_video_job, args=(job_id, payload, upload_path), daemon=True).start()
    return JSONResponse({"job_id": job_id, "state": "JOB_QUEUED"}, status_code=202)


@router.get("/video-jobs/{job_id}")
def get_video_job(job_id: str, _: None = Depends(require_service_token)) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {k: v for k, v in job.items() if k != "events"}


@router.get("/video-jobs/{job_id}/results")
def get_video_results(job_id: str, _: None = Depends(require_service_token)) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {"events": list(job.get("events") or []), "total": len(job.get("events") or [])}
