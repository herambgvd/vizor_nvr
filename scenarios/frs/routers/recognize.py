"""Snapshot serving — returns enrolled-photo / live-worker / ingested face JPEGs.

(The on-demand image-recognition + face-detection endpoints, and the video-job
recognition feature, were removed — FRS is live-camera only, no media uploads.)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from config import DATA_PATH
from db import session
from deps import require_service_token
from db.models import FRSPhoto

router = APIRouter(tags=["snapshot"])


@router.get("/snapshot")
def snapshot(key: str = Query(...), _: None = Depends(require_service_token)):
    # Snapshot key kinds:
    #   live:<id>    → a live-worker frame stored under DATA_PATH/snapshots
    #   ingest:<id>  → a third-party ingested image (same dir)
    #   <photo_id>   → an enrolled person photo
    for prefix in ("live:", "ingest:"):
        if key.startswith(prefix):
            name = key[len(prefix):]
            # UUID chars + the "_face" crop suffix only — never let the key escape the
            # dir. (Live frame ids are str(uuid4) with hyphens; the face crop adds _face.)
            if not all(c.isalnum() or c in "-_" for c in name) or "/" in name or ".." in name:
                raise HTTPException(404, "snapshot not found")
            path = DATA_PATH / "snapshots" / f"{name}.jpg"
            if not path.exists():
                raise HTTPException(404, "snapshot not found")
            return FileResponse(str(path), media_type="image/jpeg")
    with session() as s:
        ph = s.get(FRSPhoto, key)
        path = DATA_PATH / ph.storage_key if (ph and ph.storage_key) else None
    if not path or not path.exists():
        raise HTTPException(404, "snapshot not found")
    return FileResponse(str(path), media_type="image/jpeg")
