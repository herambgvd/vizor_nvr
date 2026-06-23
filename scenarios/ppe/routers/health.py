"""Health + deep-health (Triton / db / ffmpeg / worker / disk readiness)."""
from __future__ import annotations

import shutil
import subprocess

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select

import config
from db import db_ready, session
from db.models import PPEEvent
from deps import require_service_token
from inference import detector
from live import live_status, worker_logs

router = APIRouter(tags=["health"])


def _disk() -> dict:
    try:
        u = shutil.disk_usage(str(config.DATA_PATH))
        pct = round(u.used / u.total * 100, 1)
        return {"used_percent": pct, "ok": pct < config.DISK_WARN_PERCENT}
    except Exception:  # noqa: BLE001
        return {"used_percent": None, "ok": True}


@router.get("/health")
def health(response: Response) -> dict:
    """Liveness probe (no auth, no PII). Reports degraded — and a 503 so the
    orchestrator restarts the container — when the DB is down, or when live is
    enabled but no worker is actively decoding frames, or disk is near full."""
    db_ok = db_ready()
    workers = live_status()
    disk = _disk()
    live_ok = (not workers["enabled"]) or workers["expected"] == 0 or workers["active"] > 0
    ok = db_ok and disk["ok"] and live_ok
    if not ok:
        response.status_code = 503
    return {
        "status": "ok" if ok else "degraded",
        "scenario": config.SCENARIO_SLUG, "version": config.VERSION,
        "db_ready": db_ok, "triton_ready": detector.ready(),
        "workers": workers, "disk": disk,
    }


@router.get("/live/logs")
def live_logs(camera_id: str = Query(...),
              _: None = Depends(require_service_token)) -> dict:
    """Recent worker activity log + live stats for one camera — powers the in-UI
    'worker logs' diagnostics panel."""
    return worker_logs(camera_id)


@router.post("/health/deep")
def deep_health(_: None = Depends(require_service_token)) -> dict:
    ffmpeg = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False)
    triton = detector.status()
    db_ok = False
    if db_ready():
        try:
            with session() as s:
                s.scalar(select(func.count(PPEEvent.id)))
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
    return {
        "status": "ok" if (db_ok and triton.get("ready") and ffmpeg.returncode == 0) else "degraded",
        "engine": "triton ppe_yolo26 + temporal compliance",
        "ffmpeg": ffmpeg.returncode == 0,
        "database": db_ok,
        "triton": triton,
    }
