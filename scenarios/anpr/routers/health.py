"""Health + deep-health (Triton / db / ffmpeg / worker / disk readiness)."""
from __future__ import annotations

import shutil
import subprocess

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select

import config
from db import db_ready, session
from db.models import ANPRPlateRead
from deps import require_service_token
from inference import detector, ocr, vehicle
from live import live_status

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
        "db_ready": db_ok,
        "triton_ready": detector.ready() and ocr.ready(),
        "workers": workers, "disk": disk,
    }


@router.post("/health/deep")
def deep_health(_: None = Depends(require_service_token)) -> dict:
    ffmpeg = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False)
    plate_t = detector.status()
    ocr_t = ocr.status()
    veh_t = vehicle.status()
    db_ok = False
    if db_ready():
        try:
            with session() as s:
                s.scalar(select(func.count(ANPRPlateRead.id)))
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
    triton_ok = bool(plate_t.get("ready")) and bool(ocr_t.get("ready"))
    return {
        "status": "ok" if (db_ok and triton_ok and ffmpeg.returncode == 0) else "degraded",
        "engine": "triton anpr_plate + ppocr_v6 + yolo26 + per-track plate voting",
        "ffmpeg": ffmpeg.returncode == 0,
        "database": db_ok,
        "triton": {"plate": plate_t, "ocr": ocr_t, "vehicle": veh_t},
    }
