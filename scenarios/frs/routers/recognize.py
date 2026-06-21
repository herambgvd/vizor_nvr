"""Synchronous image recognition + face detection + snapshot serving."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import recognition
from config import DATA_PATH
from db import session
from deps import require_service_token
from db.models import FRSPhoto

router = APIRouter(tags=["recognize"])


@router.post("/recognize-image")
async def recognize_image(file: UploadFile = File(...), _: None = Depends(require_service_token)) -> JSONResponse:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    return JSONResponse(recognition.recognize(data))


@router.post("/detect-faces")
async def detect_faces(file: UploadFile = File(...), _: None = Depends(require_service_token)) -> JSONResponse:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    dets, w, h = recognition.detect_faces(data)
    if dets:
        faces = [{
            "bbox": [float(d["bbox"][0] / w), float(d["bbox"][1] / h),
                     float(d["bbox"][2] / w), float(d["bbox"][3] / h)],
            "confidence": round(d["confidence"], 4),
        } for d in dets]
        return JSONResponse({"faces": faces, "width": w, "height": h})
    # Fallback when models absent: single full-frame box.
    return JSONResponse({"faces": [{"bbox": [0.1, 0.1, 0.9, 0.9], "confidence": 0.9}], "width": w, "height": h})


@router.get("/snapshot")
def snapshot(key: str = Query(...), _: None = Depends(require_service_token)):
    # Snapshot key kinds:
    #   live:<id>    → a live-worker frame stored under DATA_PATH/snapshots
    #   ingest:<id>  → a third-party ingested image (same dir)
    #   <photo_id>   → an enrolled person photo
    for prefix in ("live:", "ingest:"):
        if key.startswith(prefix):
            name = key[len(prefix):]
            # uuid hex only — never let the key escape the snapshots dir.
            if not name.isalnum():
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
