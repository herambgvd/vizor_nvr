"""Snapshot serving — returns a stored event/frame JPEG. Service-token gated.

Event payloads carry `snapshot_path` = "/snapshot?key=live:<frame_id>". The frame
is stored under DATA_PATH/snapshots/<frame_id>.jpg (full frame) with an optional
<frame_id>_crop.jpg person crop.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

import config
from deps import require_service_token

router = APIRouter(tags=["snapshot"])


@router.get("/snapshot")
def snapshot(key: str = Query(...), crop: bool = Query(False),
             _: None = Depends(require_service_token)):
    # key kinds:
    #   live:<frame_id>   → a live-worker frame (DATA_PATH/snapshots/<id>.jpg)
    #   ingest:<uuid>     → a third-party ingested image (same dir, no crop variant)
    #   <bare frame id>   → legacy bare id
    base = config.DATA_PATH / "snapshots"
    if key.startswith("ingest:"):
        name = key[len("ingest:"):]
        # uuid hex only — never let the key escape the snapshots dir.
        if not name.isalnum():
            raise HTTPException(404, "snapshot not found")
        path = base / f"{name}.jpg"
        if not path.exists():
            raise HTTPException(404, "snapshot not found")
        return FileResponse(str(path), media_type="image/jpeg")
    # key form: "live:<frame_id>" (or a bare frame id). Strip a known prefix.
    frame_id = key.split(":", 1)[1] if ":" in key else key
    # Guard against path traversal — frame ids are uuids; reject separators.
    if "/" in frame_id or "\\" in frame_id or ".." in frame_id:
        raise HTTPException(400, "invalid key")
    name = f"{frame_id}_crop.jpg" if crop else f"{frame_id}.jpg"
    path = base / name
    if not path.exists():
        # Fall back to the full frame if a crop was requested but absent.
        path = base / f"{frame_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "snapshot not found")
    return FileResponse(str(path), media_type="image/jpeg")
