"""Standalone entry point for one media analysis — run as its own process.

`start_media_job` launches `python -m live.media_runner '<json-spec>'`. Running the
GIL-heavy CV + Triton + ffmpeg work in a child process (not a thread inside the
uvicorn worker) keeps the API responsive: a background thread starved the event loop
and the job itself stalled at frame 1. The child reports progress by writing the same
<job_id>.json the status endpoint reads, so the parent needs no IPC.

Usage:  python -m live.media_runner '{"job_id":..,"video_path":..,"cam_config":..}'
"""
from __future__ import annotations

import json
import sys

from .video_pipeline import MediaJob, _run_job, get_job


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("media_runner: missing job spec", file=sys.stderr)
        return 2
    spec = json.loads(argv[1])
    job_id = spec["job_id"]
    # Reuse any already-persisted record (carries name/src_path) so we keep the same
    # metadata the parent wrote when it registered the job.
    job = get_job(job_id) or MediaJob(job_id=job_id, name=spec.get("name", "video"),
                                      src_path=spec.get("video_path", ""))
    job.name = spec.get("name", job.name)
    job.src_path = spec.get("video_path", job.src_path)
    _run_job(job, spec["video_path"], spec.get("cam_config") or {}, int(spec.get("sample_fps") or 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
