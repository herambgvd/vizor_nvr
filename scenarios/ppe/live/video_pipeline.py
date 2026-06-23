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
    pid: int = 0                     # child analysis process (liveness check)
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
    # The analysis runs in a child process that writes the canonical state to disk, so
    # the on-disk json is the source of truth — always prefer it. Fall back to the
    # in-memory record only if no json exists yet.
    import json
    p = _job_meta_path(job_id)
    if not p.exists():
        with _LOCK:
            return _JOBS.get(job_id)
    try:
        d = json.loads(p.read_text())
        job = MediaJob(**d)
    except Exception:  # noqa: BLE001
        with _LOCK:
            return _JOBS.get(job_id)
    # In-flight job whose child process has died (crash / kill) without reaching a
    # terminal status: mark it failed so the UI stops spinning forever. A live child
    # keeps `pid` running, so we only error out when the pid is gone.
    if job.status in ("running", "encoding") and job.pid and not _pid_alive(job.pid):
        job.status = "error"
        job.error = "analysis process exited unexpectedly"
        _persist(job)
    return job


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:  # noqa: BLE001
        return True


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
    # Only remove the source video if NO OTHER job still references it — the same
    # upload can be analysed more than once, and deleting a shared src would break the
    # other runs (they'd fail with "cannot open uploaded video").
    if src:
        import json
        shared = False
        for jp in _media_dir().glob("*.json"):
            if jp.name == f"{job_id}.json":
                continue
            try:
                if json.loads(jp.read_text()).get("src_path") == src:
                    shared = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if not shared:
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
    (required_items, roi, *_conf, etc — same schema as a camera). Returns job_id.

    The analysis runs in a SEPARATE PROCESS, not a thread. The CV + Triton + ffmpeg
    work is GIL-heavy and, inside the uvicorn worker, a background thread starved the
    event loop (health checks timed out, the job itself stalled at frame 1). A child
    process is fully isolated from uvicorn; it reports progress by writing the same
    <job_id>.json the status endpoint already reads."""
    import json
    import sys
    job_id = uuid.uuid4().hex[:12]
    job = MediaJob(job_id=job_id, name=name or "video", src_path=str(video_path))
    with _LOCK:
        _JOBS[job_id] = job
    _persist(job)
    spec = json.dumps({
        "job_id": job_id, "video_path": str(video_path), "cam_config": cam_config,
        "sample_fps": sample_fps, "name": name or "video",
    })
    # python -m live.media_runner '<json>' — detached, its own GIL/fds.
    subprocess.Popen([sys.executable, "-m", "live.media_runner", spec],
                     cwd="/app", stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return job_id


def _run_job(job: MediaJob, video_path: str, cam_config: dict, sample_fps: int) -> None:
    from .async_pipeline import PpePipeline

    job.status = "running"
    job.pid = os.getpid()
    _persist(job)
    # Write annotated frames with an OpenCV VideoWriter (mp4v) — NO ffmpeg stdin pipe.
    # The pipe deadlocked at large frame sizes (ffmpeg stopped draining stdin and our
    # write() blocked forever, job stuck at 0/N). OpenCV writes straight to a file, so
    # there's nothing to deadlock on. mp4v (MPEG-4) isn't reliably browser-playable, so
    # once all frames are written we transcode the file -> H.264 in a single
    # file->file ffmpeg pass (also no pipe). GPU NVENC when available, else libx264.
    final_out = str(_media_dir() / f"{job.job_id}.mp4")
    raw_out = str(_media_dir() / f"{job.job_id}_raw.mp4")
    cap = None
    writer = None
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError("cannot open uploaded video")
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        job.frames_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        _persist(job)   # publish the frame count immediately so the UI shows N, not "—"

        # Optional analyse-fps downsample (skip frames) for long videos.
        step = 1
        if sample_fps and sample_fps > 0 and src_fps > sample_fps:
            step = max(1, int(round(src_fps / sample_fps)))
        out_fps = src_fps / step

        # Loading the detector/Triton/SigLIP takes a few seconds — flag it so the UI
        # shows "Preparing model…" instead of a frozen 0%.
        job.status = "preparing"
        _persist(job)
        cam = {"camera_id": f"media:{job.job_id}", "config": cam_config}
        pipeline = PpePipeline(cam)
        writer = cv2.VideoWriter(raw_out, cv2.VideoWriter_fourcc(*"mp4v"),
                                 max(1.0, out_fps), (W, H))
        if not writer.isOpened():
            raise RuntimeError("cannot open video writer")
        job.status = "running"
        _persist(job)

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
            writer.write(annotated)
            job.frames_done = fno
            if job.frames_total:
                job.progress = min(1.0, fno / job.frames_total)
            if fno % 10 == 0:
                _persist(job)   # checkpoint so a reopened page sees live progress
        cap.release(); cap = None
        writer.release(); writer = None

        # Transcode mp4v -> browser-playable H.264 (file -> file, no pipe).
        job.status = "encoding"
        _persist(job)
        _to_h264(raw_out, final_out)
        try:
            os.remove(raw_out)
        except OSError:
            pass

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
        if writer is not None:
            writer.release()
        job.finished_at = time.time()
        _persist(job)


def _to_h264(src: str, dst: str) -> None:
    """Transcode to browser-playable H.264, file -> file (no pipe). Prefer the GPU
    NVENC encoder; fall back to libx264 if NVENC isn't usable on this box."""
    base = ["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-an",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    nvenc = base[:-2] + ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr",
                         "-cq", "26"] + base[-2:] + [dst]
    try:
        subprocess.run(nvenc, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    except Exception:  # noqa: BLE001 — NVENC unavailable / busy: fall back to CPU
        pass
    subprocess.run(base[:-2] + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"]
                   + base[-2:] + [dst],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
