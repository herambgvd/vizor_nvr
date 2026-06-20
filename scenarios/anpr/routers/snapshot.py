"""Snapshot serving — returns a stored plate-read JPEG. Service-token gated.

Read payloads carry `snapshot_path` = "/snapshot?key=live:<frame_id>". The frame
is stored under DATA_PATH/snapshots/<frame_id>.jpg (full frame) with a
<frame_id>_crop.jpg plate crop. Path-traversal guarded (frame ids are uuids).
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
    # key form: "live:<frame_id>" (or a bare frame id). Strip a known prefix.
    frame_id = key.split(":", 1)[1] if ":" in key else key
    # Guard against path traversal — frame ids are uuids; reject separators.
    if "/" in frame_id or "\\" in frame_id or ".." in frame_id:
        raise HTTPException(400, "invalid key")
    base = config.DATA_PATH / "snapshots"
    name = f"{frame_id}_crop.jpg" if crop else f"{frame_id}.jpg"
    path = base / name
    if not path.exists():
        # Fall back to the full frame if a crop was requested but absent.
        path = base / f"{frame_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "snapshot not found")
    return FileResponse(str(path), media_type="image/jpeg")
