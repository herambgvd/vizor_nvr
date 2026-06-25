"""Vizor Face Recognition scenario plugin.

Standalone FastAPI microservice. Owns its gallery (Postgres), face vectors
(Qdrant) and photo storage (volume), and runs the real SCRFD + ArcFace pipeline
in-process via onnxruntime (ported from vizor-gpu). Registers its manifest with
the NVR on boot and is reached through the NVR's licensed scenario proxy.

This module is intentionally thin. Each concern is its own package:
config/ (settings), db/ (engine + models), schemas/ (serializers),
qdrant/ (vector store), recognition/ (service + inference/), deps/ (auth),
registration/ (manifest), and routers/ (one module per endpoint group).
"""
from __future__ import annotations

import threading

from fastapi import FastAPI

import config
from qdrant import store as qdrant_store
from db import init_db
from live import start_live_manager
from live.retention import start_retention_sweeper
from registration import register_on_boot
from routers import (
    groups,
    health,
    ingest,
    investigate,
    persons,
    photos,
    public,
    recognize,
    reports,
    settings as settings_router,
    transit,
    tts,
)

app = FastAPI(title="Vizor Face Recognition", version=config.VERSION)

for module in (health, groups, persons, photos, recognize, investigate,
               transit, reports, ingest, public, settings_router, tts):
    app.include_router(module.router)


@app.on_event("startup")
def _startup() -> None:
    # Raise the threadpool FastAPI runs sync routes (like /health) on. The default
    # is 40; recognition's blocking calls + GStreamer threads can occupy enough of
    # it that a sync /health request can't get a worker and times out, flapping the
    # container "unhealthy". A bigger pool keeps the probe responsive. (The real
    # leak — un-joined GStreamer threads — is fixed in FrameSource.close(); this is
    # defence-in-depth.)
    try:
        import anyio
        limiter = anyio.to_thread.current_default_thread_limiter()
        limiter.total_tokens = int(__import__("os").getenv("FRS_THREADPOOL", "96"))
    except Exception:  # noqa: BLE001
        pass
    threading.Thread(target=init_db, daemon=True).start()
    qdrant_store.client()
    threading.Thread(target=register_on_boot, daemon=True).start()
    # Live per-camera recognition workers (poll-driven; reconciles to the NVR's
    # enabled-camera set). Safe to start now — the first poll waits LIVE_POLL_SECONDS.
    start_live_manager()
    # Retention sweeper: purge aged events/snapshots/vectors + retry pending erasures.
    start_retention_sweeper()
    # Background health refresher — keeps /health a cached in-memory read so it's
    # never starved by recognition load (was flapping "unhealthy" → apparent event hold).
    from routers.health import _refresh_health_loop
    threading.Thread(target=_refresh_health_loop, daemon=True, name="health-refresh").start()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
