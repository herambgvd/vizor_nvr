"""Video-file PPE analysis — runs the SAME proven pipeline on an uploaded video.

Reuses PpePipeline (which reuses CameraWorker's _process: detector → tracker →
stable-id → smoother → SigLIP → ComplianceEngine → snapshots, every threshold) so a
video gives byte-for-byte the same detections as a live camera. The only difference:
time advances by VIDEO frame time (not wall-clock) so grace/min-present/cooldown
behave the same whether the box analyses in real time or faster.

Output: an annotated H.264 mp4 (corner box + status card + ROI overlay) plus the
list of detected events. Driven as a background job (1 GB videos take minutes).
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2

import config

logger = logging.getLogger(__name__)


@dataclass
class MediaJob:
    job_id: str
    name: str = ""                   # original filename, for the history list
    src_path: str = ""               # uploaded source video, removed on delete
    status: str = "queued"          # queued | running | encoding | done | error
    progress: float = 0.0           # 0..1
    frames_total: int = 0
    frames_done: int = 0
    events: list = field(default_factory=list)
    annotated_path: Optional[str] = None
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None


_JOBS: dict[str, MediaJob] = {}
_LOCK = threading.Lock()


def _media_dir() -> Path:
    d = config.DATA_PATH / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _job_meta_path(job_id: str) -> Path:
    return _media_dir() / f"{job_id}.json"


def _persist(job: MediaJob) -> None:
    """Write job metadata to disk so it survives a page reload / process restart and
    can be listed in the media history."""
    import json
    from dataclasses import asdict
    try:
        _job_meta_path(job.job_id).write_text(json.dumps(asdict(job), default=str))
    except Exception:  # noqa: BLE001
        pass


def get_job(job_id: str) -> Optional[MediaJob]:
    with _LOCK:
        j = _JOBS.get(job_id)
    if j is not None:
        return j
    # Recover from disk (operator navigated away, or the dev uvicorn --reload killed
    # the worker thread mid-job).
    import json
    p = _job_meta_path(job_id)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
        job = MediaJob(**d)
    except Exception:  # noqa: BLE001
        return None
    # Orphaned in-flight job: persisted as running but no live thread owns it (the dev
    # uvicorn --reload restarted the process). The H.264 pipe streams as it goes, so
    # whatever encoded so far is fine, but the run can't continue — mark it failed so
    # the UI stops showing an endless spinner. (Production has no --reload.)
    if job.status in ("running", "encoding"):
        final_out = _media_dir() / f"{job.job_id}.mp4"
        if final_out.exists() and (job.progress or 0) >= 0.999:
            job.status = "done"
            job.annotated_path = f"/media/result?job_id={job.job_id}"
        else:
            job.status = "error"
            job.error = "interrupted before completion (process reload)"
        _persist(job)
    return job


def delete_job(job_id: str) -> None:
    """Remove every artifact of a job: result mp4, metadata json, source upload, and
    its in-memory record. Used by the UI's delete button."""
    with _LOCK:
        job = _JOBS.pop(job_id, None)
    md = _media_dir()
    paths = [md / f"{job_id}.mp4", md / f"{job_id}_raw.mp4", _job_meta_path(job_id)]
    src = getattr(job, "src_path", "") if job else ""
    if not src:
        # Recover src_path from the persisted json before we delete it.
        import json
        p = _job_meta_path(job_id)
        if p.exists():
            try:
                src = json.loads(p.read_text()).get("src_path", "")
            except Exception:  # noqa: BLE001
                src = ""
    if src:
        paths.append(Path(src))
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def list_jobs() -> list:
    """All media jobs (in-flight + persisted) newest first — for the history list."""
    import json
    out: dict[str, dict] = {}
    for p in sorted(_media_dir().glob("*.json")):
        try:
            d = json.loads(p.read_text())
            out[d["job_id"]] = d
        except Exception:  # noqa: BLE001
            continue
    with _LOCK:
        for jid, j in _JOBS.items():
            from dataclasses import asdict
            out[jid] = asdict(j)
    items = list(out.values())
    items.sort(key=lambda j: j.get("started_at", 0), reverse=True)
    # Trim events to a count in the list view (full events via /media/status).
    for it in items:
        it["event_count"] = len(it.get("events") or [])
        it.pop("events", None)
    return items


def start_media_job(video_path: str, cam_config: dict, *, sample_fps: int = 0, name: str = "") -> str:
    """Register + launch a background analysis of `video_path` using `cam_config`
    (required_items, roi, *_conf, etc — same schema as a camera). Returns job_id."""
    job_id = uuid.uuid4().hex[:12]
    job = MediaJob(job_id=job_id, name=name or "video", src_path=str(video_path))
    with _LOCK:
        _JOBS[job_id] = job
    _persist(job)
    threading.Thread(target=_run_job, args=(job, video_path, cam_config, sample_fps),
                     name=f"ppe-media-{job_id}", daemon=True).start()
    return job_id


def _run_job(job: MediaJob, video_path: str, cam_config: dict, sample_fps: int) -> None:
    from .async_pipeline import PpePipeline

    job.status = "running"
    # Encode H.264 directly via an ffmpeg pipe — annotated BGR frames are written to
    # ffmpeg's stdin as they are produced, so the output is a browser-playable .mp4
    # the moment the last frame lands. No mp4v intermediate, no slow second-pass
    # re-encode (which used to leave the job stuck at "encoding"), no 400 MB raw file.
    final_out = str(_media_dir() / f"{job.job_id}.mp4")
    cap = None
    enc = None
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError("cannot open uploaded video")
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        job.frames_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

        # Optional analyse-fps downsample (skip frames) for long videos.
        step = 1
        if sample_fps and sample_fps > 0 and src_fps > sample_fps:
            step = max(1, int(round(src_fps / sample_fps)))
        out_fps = src_fps / step

        cam = {"camera_id": f"media:{job.job_id}", "config": cam_config}
        pipeline = PpePipeline(cam)
        enc = _open_h264_pipe(final_out, W, H, out_fps)

        fno = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            fno += 1
            if (fno - 1) % step != 0:
                continue
            ts = (fno - 1) / src_fps   # video time so grace/cooldown match live
            annotated, events = pipeline.process_with_overlay(frame, ts)
            for ev in events:
                ev["video_ts"] = round(ts, 2)
                job.events.append(_event_summary(ev))
            enc.stdin.write(annotated.tobytes())
            job.frames_done = fno
            if job.frames_total:
                job.progress = min(1.0, fno / job.frames_total)
            if fno % 200 == 0:
                _persist(job)   # checkpoint so a reopened page sees live progress
        cap.release(); cap = None
        enc.stdin.close()
        enc.wait(timeout=120)
        enc = None

        job.annotated_path = f"/media/result?job_id={job.job_id}"
        job.status = "done"
        job.progress = 1.0
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = str(e)[:300]
        logger.exception("[ppe-media] job %s failed", job.job_id)
    finally:
        if cap is not None:
            cap.release()
        if enc is not None:
            try:
                enc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                enc.wait(timeout=30)
            except Exception:  # noqa: BLE001
                enc.kill()
        job.finished_at = time.time()
        _persist(job)


def _open_h264_pipe(dst: str, w: int, h: int, fps: float) -> "subprocess.Popen":
    """ffmpeg reading raw BGR frames on stdin, writing a faststart H.264 mp4."""
    return subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{w}x{h}", "-r", f"{max(1.0, fps):.4f}", "-i", "pipe:0",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", dst],
        stdin=subprocess.PIPE,
    )


def _to_h264(src: str, dst: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
         "-c:v", "libx264", "-preset", "fast", "-crf", "26",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", dst],
        check=True,
    )


def _event_summary(ev: dict) -> dict:
    return {
        "event_type": ev.get("event_type"),
        "worker_track_id": ev.get("worker_track_id"),
        "missing_items": ev.get("missing_items"),
        "present_items": ev.get("present_items"),
        "confidence": ev.get("confidence"),
        "video_ts": ev.get("video_ts"),
        "snapshot_path": ev.get("snapshot_path"),
    }
