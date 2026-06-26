"""Public PPE dashboard router — UNAUTHENTICATED, aggregate analytics only.

Built from the shared Vizor SDK: build_public_router wires GET /public/dashboard
+ /public/stream against the singleton settings store, the shared EventBus, and
the per-scenario build_dashboard callable. Both routes 404 when the public
toggle is off. No snapshots, no raw images — aggregate counts only.
"""
from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import Response
from vizor_sdk import build_public_router

import config
from db.events import bus
from db.public_store import build_dashboard, store

router = build_public_router(store, bus, build_dashboard, data_path=config.DATA_PATH)


@router.get("/public/snapshot")
def public_snapshot(key: str):
    """Privacy-safe violation snapshot for the public dashboard: serves the crop but
    HEAVILY BLURRED server-side. Gated by the public toggle; only live/ingest keys."""
    import cv2
    import numpy as np
    if not store.get().get("public_dashboard_enabled"):
        raise HTTPException(404, "not found")
    frame_id = key.split(":", 1)[1] if ":" in key else key
    if "/" in frame_id or "\\" in frame_id or ".." in frame_id:
        raise HTTPException(404, "not found")
    base = config.DATA_PATH / "snapshots"
    path = None
    for name in (f"{frame_id}_crop.jpg", f"{frame_id}.jpg"):
        p = base / name
        if p.exists():
            path = p
            break
    if path is None:
        raise HTTPException(404, "not found")
    try:
        img = cv2.imread(str(path))
        if img is None:
            raise ValueError("decode")
        h, w = img.shape[:2]
        small = cv2.resize(img, (max(1, w // 16), max(1, h // 16)))
        img = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        img = cv2.GaussianBlur(img, (0, 0), sigmaX=8)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            raise ValueError("encode")
        return Response(buf.tobytes(), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=60"})
    except Exception:  # noqa: BLE001
        raise HTTPException(404, "not found")
