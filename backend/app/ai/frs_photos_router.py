# =============================================================================
# FRS Photos Router — Photo upload / list / delete for FRS gallery.
#
# Photo upload uses multipart/form-data. The route stores the raw JPEG
# in RustFS (configured via STORAGE_PATH), then enqueues the embedding
# job:
#   1. ArcFace produces a 512-dim float vector via Triton
#   2. Vector is upserted into Qdrant collection `frs_faces`
#   3. The qdrant_point_id is written back to the frs_photos row
#
# Phase 1 stub: rows are created with `qdrant_point_id` placeholder so
# the rest of the system works end-to-end. The actual embedding job
# requires the Perception Microservice + Triton ArcFace model running,
# which lands when the RTX 5060 + NGC enterprise access are ready.
# At that point the embedding worker reads photos where
# qdrant_point_id starts with `pending:` and fills in real IDs.
# =============================================================================

import logging
import os
import uuid
from datetime import datetime
from typing import List

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import FRSPerson, FRSPhoto
from app.config import settings
from app.core.dependencies import require_permission, get_current_user
from app.database import get_db


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai/frs", tags=["AI · FRS Photos"])


# Max upload size — 8 MB / photo. Plenty for any face crop or
# full-frame enrollment image.
MAX_PHOTO_BYTES = 8 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg", "image/jpg", "image/png"}

PHOTO_STORAGE_SUBDIR = "frs/photos"


class FRSPhotoOut(BaseModel):
    id: str
    person_id: str
    storage_key: str
    qdrant_point_id: str
    quality_score: float | None
    uploaded_at: datetime

    class Config:
        from_attributes = True


def _photo_storage_dir() -> str:
    base = str(settings.STORAGE_PATH).rstrip("/")
    path = os.path.join(base, PHOTO_STORAGE_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


@router.get(
    "/persons/{person_id}/photos",
    response_model=List[FRSPhotoOut],
)
async def list_person_photos(
    person_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[FRSPhotoOut]:
    person = await db.get(FRSPerson, person_id)
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    result = await db.execute(
        select(FRSPhoto)
        .where(FRSPhoto.person_id == person_id)
        .order_by(FRSPhoto.uploaded_at.desc())
    )
    return [FRSPhotoOut.model_validate(p) for p in result.scalars().all()]


@router.post(
    "/persons/{person_id}/photos",
    response_model=FRSPhotoOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_person_photo(
    person_id: str,
    file: UploadFile = File(..., description="JPEG or PNG photo of the face"),
    _user=Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
) -> FRSPhotoOut:
    person = await db.get(FRSPerson, person_id)
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")

    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported content type: {file.content_type}",
        )

    # Stream into memory + size-check. Could refactor to disk-stream if
    # larger uploads become common.
    body = await file.read(MAX_PHOTO_BYTES + 1)
    if len(body) > MAX_PHOTO_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Photo exceeds {MAX_PHOTO_BYTES} bytes",
        )

    # Write to filesystem (Phase 2 will switch to RustFS multi-part upload)
    photo_id = str(uuid.uuid4())
    ext = ".jpg" if "jpeg" in file.content_type or "jpg" in file.content_type else ".png"
    filename = f"{photo_id}{ext}"
    rel_key = f"{PHOTO_STORAGE_SUBDIR}/{person_id}/{filename}"
    abs_path = os.path.join(_photo_storage_dir(), person_id, filename)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as fh:
        fh.write(body)

    # Placeholder qdrant_point_id — replaced by the embedding job when
    # Perception+Triton are live. Using a `pending:` prefix so the
    # batch backfill worker can find these later.
    pending_qid = f"pending:{photo_id}"

    photo = FRSPhoto(
        id=photo_id,
        person_id=person_id,
        storage_key=rel_key,
        qdrant_point_id=pending_qid,
        quality_score=None,
    )
    db.add(photo)
    await db.commit()
    await db.refresh(photo)

    logger.info(
        "Photo uploaded for person %s -> %s (qdrant pending)",
        person_id, rel_key,
    )

    return FRSPhotoOut.model_validate(photo)


@router.delete(
    "/persons/{person_id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_person_photo(
    person_id: str,
    photo_id: str,
    _user=Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
) -> None:
    photo = await db.get(FRSPhoto, photo_id)
    if not photo or photo.person_id != person_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")

    # Remove file from disk (best-effort, ignore missing)
    abs_path = os.path.join(str(settings.STORAGE_PATH).rstrip("/"), photo.storage_key)
    try:
        os.unlink(abs_path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Could not delete photo file %s: %s", abs_path, e)

    # Qdrant point cleanup deferred: a batch job removes orphans.
    # Phase 2 will add a synchronous Qdrant delete here.

    await db.delete(photo)
    await db.commit()
