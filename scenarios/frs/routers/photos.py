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
import config
from config import ALLOWED_CONTENT, DATA_PATH, MAX_PHOTO_BYTES
from schemas import utcnow


def naive_iso() -> str:
    return utcnow().isoformat()
from db import session
from deps import recount_person, require_service_token, looks_like_image
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
    # Verify the BYTES are actually an image — a spoofed Content-Type must not let
    # a non-image (script, payload) be stored as a .jpg.
    if not looks_like_image(data):
        raise HTTPException(415, "uploaded file is not a valid JPEG/PNG/WEBP image")

    photo_id = str(uuid.uuid4())
    photo_dir = DATA_PATH / "persons" / person_id
    photo_dir.mkdir(parents=True, exist_ok=True)
    rel_key = f"persons/{person_id}/{photo_id}.jpg"
    (photo_dir / f"{photo_id}.jpg").write_bytes(data)

    enroll_status, embedding_id, quality, error = "enrolled", photo_id, None, None
    try:
        # Enrollment path: gated, NO denoise (vizor-app embeds the raw aligned crop).
        vector, meta = recognition.embed_largest_face(data, gate=recognition.engine_ready())
        if vector is None:
            raise ValueError(meta.get("error", "no_usable_face"))
        # Duplicate guard (vizor-app parity): reject if this face already belongs
        # to a DIFFERENT person at cosine >= DUPLICATE_COSINE.
        dup = qdrant_store.search(vector, limit=1)
        if dup:
            top = dup[0]
            if (float(top.get("score", 0.0)) >= config.DUPLICATE_COSINE
                    and top.get("person_id") and top.get("person_id") != person_id):
                raise ValueError("duplicate_face")
        quality = float(meta.get("confidence") or 0.9)
        enrolled_at = naive_iso()
        # Main + augment points share type:"photo" (vizor-app keeps augments as
        # "photo"); point_key lets us delete all of a photo's vectors together.
        base_payload = {"person_id": person_id, "person_name": person_name,
                        "photo_id": photo_id, "point_key": photo_id,
                        "type": "photo", "enrolled_at": enrolled_at}
        # The MAIN vector must land — if Qdrant rejects it the person would never
        # match, so fail the enrollment loudly instead of reporting false success.
        if not qdrant_store.upsert(photo_id, vector, dict(base_payload)):
            raise RuntimeError("vector_store_unavailable")
        aligned = meta.get("aligned")
        eng = recognition.engine()
        for variant in recognition.augment_points(aligned):
            vec = eng.embed_face(variant["image"])
            if vec is None:
                continue
            qdrant_store.upsert(str(uuid.uuid4()), vec.tolist(),
                                {**base_payload, "synthetic": True, "augment": variant["tag"]})
    except Exception as exc:  # noqa: BLE001
        enroll_status, embedding_id, quality, error = "failed", None, None, str(exc)
        # Roll back partial state: drop any vectors that did land + the orphan file.
        qdrant_store.delete_by("point_key", photo_id)
        try:
            (photo_dir / f"{photo_id}.jpg").unlink(missing_ok=True)
        except OSError:
            pass

    with session() as s:
        # On failure the orphan file was removed above → don't keep a dangling key.
        ph = FRSPhoto(id=photo_id, person_id=person_id,
                      storage_key=rel_key if enroll_status == "enrolled" else None,
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
