"""Health + deep-health (engine/db/qdrant/ffmpeg/worker/disk readiness)."""
from __future__ import annotations

import asyncio
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


import time as _time

# Cached health snapshot. /health is hit constantly by the orchestrator; computing
# it (DB ping, disk stat) on every request — on a SYNC route that borrows an anyio
# threadpool thread — meant that whenever one component briefly blocked, the request
# held its pool thread for the full timeout. Under a burst those threads piled up,
# the pool starved, and EVERY subsequent /health stalled (the "events hold" the
# container kept flapping on). We refresh the snapshot at most once per
# _HEALTH_TTL_S and serve it from cache otherwise, and the route is async so it
# never borrows a pool thread at all.
_HEALTH_TTL_S = 5.0
_health_cache: dict = {"ts": 0.0, "data": None, "code": 200}


def _compute_health() -> tuple[dict, int]:
    db_ok = db_ready()
    engine_ok = recognition.engine_ready()
    workers = live_status()
    disk = _disk()
    live_ok = (not workers["enabled"]) or workers["expected"] == 0 or workers["active"] > 0
    ok = db_ok and disk["ok"] and live_ok
    data = {
        "status": "ok" if ok else "degraded",
        "scenario": config.SCENARIO_SLUG, "version": config.VERSION,
        "db_ready": db_ok, "engine_ready": engine_ok,
        "workers": workers, "disk": disk,
    }
    return data, (200 if ok else 503)


def _refresh_health_loop() -> None:
    """Recompute the health snapshot on a dedicated background thread, NOT on a
    request. The /health route then just returns the cached snapshot instantly —
    it never does DB/disk work and never borrows a pool thread, so it can't be
    starved by recognition load (the root cause of the container flapping
    "unhealthy" + the apparent event hold). One private thread, not the shared pool,
    so it's isolated from inference back-pressure."""
    import time as _t
    while True:
        try:
            data, code = _compute_health()
            _health_cache.update(ts=_t.monotonic(), data=data, code=code)
        except Exception:  # noqa: BLE001
            pass
        _t.sleep(_HEALTH_TTL_S)


@router.get("/health")
async def health(response: Response) -> dict:
    """Liveness probe (no auth, no PII). Returns the cached snapshot computed by the
    background refresher — pure in-memory read, so it's always fast regardless of
    recognition load."""
    if _health_cache["data"] is None:
        # First call before the refresher has run once — compute once inline.
        try:
            data, code = _compute_health()
            _health_cache.update(ts=_time.monotonic(), data=data, code=code)
        except Exception:  # noqa: BLE001
            response.status_code = 503
            return {"status": "starting", "scenario": config.SCENARIO_SLUG,
                    "version": config.VERSION}
    response.status_code = _health_cache["code"]
    return _health_cache["data"]


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
