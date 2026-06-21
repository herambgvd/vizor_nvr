"""Vizor ANPR (License Plate Recognition) scenario plugin.

Standalone FastAPI microservice. Owns its plate reads (its own Postgres) and
snapshot storage (volume), and runs the proven ANPR pipeline in real time: frames
pulled from go2rtc, plate detection + PP-OCRv6 recognition + vehicle-type
classification on the shared Triton server (anpr_plate / ppocr_v6 / yolo26), and
the ported per-track plate voting deciding one clean read per vehicle pass. Adds
the Milesight-parity features (vehicle-type, direction, speed estimate, global
whitelist/blacklist). Registers its manifest with the NVR on boot and is reached
through the NVR's licensed scenario proxy.

Thin entrypoint — each concern is its own package: config/ (settings), db/
(engine + models + events + lists + settings), schemas/ (serializers), inference/
(Triton clients), pipeline/ (voting + gating + motion), live/ (per-camera workers
+ manager + retention), deps/ (auth), registration/ (manifest), routers/ (one
module per endpoint group).
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
    health,
    ingest,
    lists,
    plates,
    public,
    reports,
    settings as settings_router,
    snapshot,
)

app = FastAPI(title="Vizor ANPR", version=config.VERSION)

for module in (health, plates, lists, reports, snapshot, settings_router,
               public, ingest):
    app.include_router(module.router)


@app.on_event("startup")
def _startup() -> None:
    threading.Thread(target=init_db, daemon=True).start()
    threading.Thread(target=register_on_boot, daemon=True).start()
    # Live per-camera ANPR workers (poll-driven; reconciles to the NVR's
    # enabled-camera set). Safe to start now — the first poll waits LIVE_POLL_SECONDS.
    start_live_manager()
    # Retention sweeper: purge aged reads + snapshot files.
    start_retention_sweeper()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
