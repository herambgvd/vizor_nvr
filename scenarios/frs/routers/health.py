"""Health + deep-health (engine/db/qdrant/ffmpeg readiness)."""
from __future__ import annotations

import subprocess

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

import config
from qdrant import store as qdrant_store
import recognition
from db import db_ready, session
from deps import require_service_token
from db.models import FRSPerson

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "scenario": config.SCENARIO_SLUG, "version": config.VERSION, "db_ready": db_ready()}


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
