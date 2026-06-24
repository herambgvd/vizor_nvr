"""Health + deep-health (engine/db/qdrant/ffmpeg/worker/disk readiness)."""
from __future__ import annotations

import shutil
import subprocess

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select

import config
from qdrant import store as qdrant_store
import recognition
from live import live_status, worker_logs
from db import db_ready, session
from deps import require_service_token
from db.models import FRSPerson

router = APIRouter(tags=["health"])


@router.get("/live/logs")
def live_logs(camera_id: str = Query(...),
              _: None = Depends(require_service_token)) -> dict:
    """Recent worker activity log + live stats for one camera — powers the in-UI
    'worker logs' diagnostics panel."""
    return worker_logs(camera_id)


def _disk() -> dict:
    try:
        u = shutil.disk_usage(str(config.DATA_PATH))
        pct = round(u.used / u.total * 100, 1)
        return {"used_percent": pct, "ok": pct < config.DISK_WARN_PERCENT}
    except Exception:  # noqa: BLE001
        return {"used_percent": None, "ok": True}


@router.get("/health")
def health(response: Response) -> dict:
    """Real liveness probe (no auth, no PII). Reports degraded — and a 503 so the
    orchestrator restarts the container — when the DB/engine is down, or when live
    is enabled but no worker is actively decoding frames, or disk is near full."""
    db_ok = db_ready()
    engine_ok = recognition.engine_ready()
    workers = live_status()
    disk = _disk()
    # Live degraded = enabled, has expected workers, but none active in the last 60s.
    live_ok = (not workers["enabled"]) or workers["expected"] == 0 or workers["active"] > 0
    ok = db_ok and disk["ok"] and live_ok
    if not ok:
        response.status_code = 503
    return {
        "status": "ok" if ok else "degraded",
        "scenario": config.SCENARIO_SLUG, "version": config.VERSION,
        "db_ready": db_ok, "engine_ready": engine_ok,
        "workers": workers, "disk": disk,
    }


@router.post("/health/deep")
def deep_health(_: None = Depends(require_service_token)) -> dict:
    ffmpeg = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False)
    onnx = recognition.onnx_status()
    qdrant = qdrant_store.client()
    db_ok = False
    if db_ready():
        try:
            with session() as s:
                s.scalar(select(func.count(FRSPerson.id)))
            db_ok = True
        except Exception:
            db_ok = False
    return {
        "status": "ok" if (db_ok and qdrant and ffmpeg.returncode == 0) else "degraded",
        "engine": "postgres-gallery + qdrant-face-index + onnx-ready fallback",
        "ffmpeg": ffmpeg.returncode == 0,
        "database": db_ok,
        "qdrant": bool(qdrant),
        "onnx": onnx,
    }
