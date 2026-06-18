"""Photo upload + in-process enrollment, listing, deletion, image serving.

Enrollment runs locally (this plugin owns the model + Qdrant — no Triton round
trip). Real path: SCRFD detect → quality gate → align → ArcFace embed, then
photometric augmentation (main + 6 synthetic variants) for recall. Every Qdrant
point carries point_key=photo_id so deletion is a single filtered delete.
"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select

from qdrant import store as qdrant_store
import recognition
from config import ALLOWED_CONTENT, DATA_PATH, MAX_PHOTO_BYTES
from db import session
from deps import recount_person, require_service_token
from db.models import FRSPerson, FRSPhoto
from schemas import photo_dict

router = APIRouter(tags=["photos"])


@router.post("/persons/{person_id}/photos", status_code=201)
async def add_photo(person_id: str, file: UploadFile = File(...), _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        person = s.get(FRSPerson, person_id)
        if not person:
            raise HTTPException(404, "person not found")
        person_name = person.full_name
    if file.content_type and file.content_type.lower() not in ALLOWED_CONTENT:
        raise HTTPException(415, f"unsupported content type: {file.content_type}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, f"photo exceeds {MAX_PHOTO_BYTES // (1024 * 1024)} MB limit")

    photo_id = str(uuid.uuid4())
    photo_dir = DATA_PATH / "persons" / person_id
    photo_dir.mkdir(parents=True, exist_ok=True)
    rel_key = f"persons/{person_id}/{photo_id}.jpg"
    (photo_dir / f"{photo_id}.jpg").write_bytes(data)

    enroll_status, embedding_id, quality, error = "enrolled", photo_id, None, None
    try:
        vector, meta = recognition.embed_largest_face(data, gate=recognition.engine_ready())
        if vector is None:
            raise ValueError(meta.get("error", "no_usable_face"))
        quality = float(meta.get("confidence") or 0.9)
        base_payload = {"person_id": person_id, "person_name": person_name,
                        "photo_id": photo_id, "point_key": photo_id}
        qdrant_store.upsert(photo_id, vector, {**base_payload, "type": "photo", "synthetic": False})
        # Augment only when the real engine produced an aligned crop.
        aligned = meta.get("aligned")
        eng = recognition.engine()
        for variant in recognition.augment_points(aligned):
            vec = eng.embed_face(variant["image"])
            if vec is None:
                continue
            qdrant_store.upsert(str(uuid.uuid4()), vec.tolist(),
                                {**base_payload, "type": "augment", "synthetic": True,
                                 "augment": variant["tag"]})
    except Exception as exc:  # noqa: BLE001
        enroll_status, embedding_id, quality, error = "failed", None, None, str(exc)

    with session() as s:
        ph = FRSPhoto(id=photo_id, person_id=person_id, storage_key=rel_key,
                      status=enroll_status, embedding_id=embedding_id,
                      quality_score=quality, error=error)
        s.add(ph); s.commit()
        recount_person(s, person_id)
        ph = s.get(FRSPhoto, photo_id)
        return photo_dict(ph)


@router.get("/persons/{person_id}/photos")
def list_photos(person_id: str, _: None = Depends(require_service_token)) -> list[dict]:
    with session() as s:
        if not s.get(FRSPerson, person_id):
            raise HTTPException(404, "person not found")
        rows = s.execute(select(FRSPhoto).where(FRSPhoto.person_id == person_id)
                         .order_by(FRSPhoto.created_at.desc())).scalars().all()
        return [photo_dict(ph) for ph in rows]


@router.delete("/photos/{photo_id}", status_code=204)
def delete_photo(photo_id: str, _: None = Depends(require_service_token)):
    with session() as s:
        ph = s.get(FRSPhoto, photo_id)
        if not ph:
            raise HTTPException(404, "photo not found")
        person_id, storage_key = ph.person_id, ph.storage_key
        s.delete(ph); s.commit()
        recount_person(s, person_id)
    # Remove this photo's face vectors (main + augment points share point_key).
    qdrant_store.delete_by("point_key", photo_id)
    if storage_key:
        f = DATA_PATH / storage_key
        if f.exists():
            try:
                os.remove(f)
            except OSError:
                pass
    return Response(status_code=204)


@router.post("/photos/{photo_id}/retry")
def retry_photo(photo_id: str, _: None = Depends(require_service_token)) -> dict:
    """Re-run enrollment on an existing (usually failed) photo from its stored
    file — SCRFD detect → align → ArcFace embed + augment, refreshing its vectors."""
    with session() as s:
        ph = s.get(FRSPhoto, photo_id)
        if not ph:
            raise HTTPException(404, "photo not found")
        person = s.get(FRSPerson, ph.person_id)
        person_name = person.full_name if person else None
        storage_key, person_id = ph.storage_key, ph.person_id
    path = DATA_PATH / storage_key if storage_key else None
    if not path or not path.exists():
        raise HTTPException(404, "photo file missing")
    data = path.read_bytes()
    # Drop any stale vectors for this photo, then re-enroll.
    qdrant_store.delete_by("point_key", photo_id)
    status_, embedding_id, quality, error = "enrolled", photo_id, None, None
    try:
        vector, meta = recognition.embed_largest_face(data, gate=recognition.engine_ready())
        if vector is None:
            raise ValueError(meta.get("error", "no_usable_face"))
        quality = float(meta.get("confidence") or 0.9)
        base = {"person_id": person_id, "person_name": person_name, "photo_id": photo_id, "point_key": photo_id}
        qdrant_store.upsert(photo_id, vector, {**base, "type": "photo", "synthetic": False})
        aligned = meta.get("aligned")
        eng = recognition.engine()
        for variant in recognition.augment_points(aligned):
            vec = eng.embed_face(variant["image"])
            if vec is None:
                continue
            qdrant_store.upsert(str(uuid.uuid4()), vec.tolist(),
                                {**base, "type": "augment", "synthetic": True, "augment": variant["tag"]})
    except Exception as exc:  # noqa: BLE001
        status_, embedding_id, quality, error = "failed", None, None, str(exc)
    with session() as s:
        ph = s.get(FRSPhoto, photo_id)
        ph.status, ph.embedding_id, ph.quality_score, ph.error = status_, embedding_id, quality, error
        s.commit()
        recount_person(s, person_id)
        ph = s.get(FRSPhoto, photo_id)
        return photo_dict(ph)


@router.get("/photos/{photo_id}/image")
def photo_image(photo_id: str, _: None = Depends(require_service_token)):
    with session() as s:
        ph = s.get(FRSPhoto, photo_id)
        if not ph or not ph.storage_key:
            raise HTTPException(404, "photo not found")
        path = DATA_PATH / ph.storage_key
    if not path.exists():
        raise HTTPException(404, "photo file not found")
    return FileResponse(str(path), media_type="image/jpeg", filename=f"{photo_id}.jpg")
