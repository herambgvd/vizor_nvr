"""Vizor PPE Compliance scenario plugin.

Standalone FastAPI microservice. Owns its compliance events (its own Postgres) and
snapshot storage (volume), and runs the proven person-level PPE pipeline in real
time: frames pulled from go2rtc, detection on the shared Triton server
(ppe_yolo26), and the ported temporal compliance engine (grace / smoothing /
relinking / cooldown) deciding violations. Registers its manifest with the NVR on
boot and is reached through the NVR's licensed scenario proxy.

Thin entrypoint — each concern is its own package: config/ (settings), db/
(engine + models + events), schemas/ (serializers), inference/ (Triton client),
pipeline/ (compliance logic), live/ (per-camera workers + manager + retention),
deps/ (auth), registration/ (manifest), routers/ (one module per endpoint group).
"""
from __future__ import annotations

import threading

from fastapi import FastAPI

import config
from db import init_db
from live import start_live_manager
from live.retention import start_retention_sweeper
from registration import register_on_boot
from routers import (
    events,
    health,
    ingest,
    public,
    reports,
    settings as settings_router,
    snapshot,
)

app = FastAPI(title="Vizor PPE Compliance", version=config.VERSION)

for module in (health, events, reports, snapshot, settings_router, public, ingest):
    app.include_router(module.router)


@app.on_event("startup")
def _startup() -> None:
    threading.Thread(target=init_db, daemon=True).start()
    threading.Thread(target=register_on_boot, daemon=True).start()
    # Live per-camera compliance workers (poll-driven; reconciles to the NVR's
    # enabled-camera set). Safe to start now — the first poll waits LIVE_POLL_SECONDS.
    start_live_manager()
    # Retention sweeper: purge aged events + snapshot files.
    start_retention_sweeper()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
