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
from registration import register_on_boot
from routers import (
    groups,
    health,
    investigate,
    persons,
    photos,
    recognize,
    reports,
    transit,
    video_jobs,
)

app = FastAPI(title="Vizor Face Recognition", version=config.VERSION)

for module in (health, groups, persons, photos, recognize, investigate,
               transit, video_jobs, reports):
    app.include_router(module.router)


@app.on_event("startup")
def _startup() -> None:
    threading.Thread(target=init_db, daemon=True).start()
    qdrant_store.client()
    threading.Thread(target=register_on_boot, daemon=True).start()
    # Live per-camera recognition workers (poll-driven; reconciles to the NVR's
    # enabled-camera set). Safe to start now — the first poll waits LIVE_POLL_SECONDS.
    start_live_manager()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
