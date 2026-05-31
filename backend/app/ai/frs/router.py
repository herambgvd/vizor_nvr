# =============================================================================
# FRS persons / groups / photos API (NVR-owned metadata).
#
#   Groups:
#     GET    /api/ai/frs/groups
#     POST   /api/ai/frs/groups
#     GET    /api/ai/frs/groups/{id}
#     PUT    /api/ai/frs/groups/{id}
#     DELETE /api/ai/frs/groups/{id}
#   Persons:
#     GET    /api/ai/frs/persons          (paginated; search/group_id/category)
#     POST   /api/ai/frs/persons
#     GET    /api/ai/frs/persons/{id}
#     PUT    /api/ai/frs/persons/{id}
#     DELETE /api/ai/frs/persons/{id}
#   Photos:
#     POST   /api/ai/frs/persons/{id}/photos   (multipart upload → pending row)
#     GET    /api/ai/frs/persons/{id}/photos
#     DELETE /api/ai/frs/photos/{photo_id}
#     GET    /api/ai/frs/photos/{photo_id}/image
#
# Reads require an authenticated user; writes require "manage_system".
# Photo bytes are stored at DATA_PATH/frs/persons/{person_id}/{photo_id}.jpg;
# a pending FRSPhoto row is created and the bridge enrolls it asynchronously.
# =============================================================================
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, File, HTTPException, Query, UploadFile, status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.core.dependencies import get_current_user, require_permission
from app.ai.frs.service import frs_service
from app.ai.models import (
    GroupCreate, GroupResponse,
    PersonCreate, PersonUpdate, PersonResponse,
    PhotoResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai/frs", tags=["FRS"])

# Upload guards.
_MAX_PHOTO_BYTES = 15 * 1024 * 1024  # 15 MB
_ALLOWED_CONTENT = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


# =============================================================================
# Schemas (local — request bodies not covered by app.ai.models)
# =============================================================================

class GroupUpdate(BaseModel):
    name: Optional[str] = None
    group_type: Optional[str] = None
    color_code: Optional[str] = None
    description: Optional[str] = None
    alert_sound: Optional[bool] = None


class PersonListResponse(BaseModel):
    items: List[PersonResponse]
    total: int
    limit: int
    offset: int


# =============================================================================
# Helpers
# =============================================================================

def _group_to_response(group, member_count: int) -> GroupResponse:
    r = GroupResponse.model_validate(group)
    r.member_count = member_count
    return r


def _person_photo_dir(person_id: str) -> Path:
    return Path(settings.DATA_PATH) / "frs" / "persons" / person_id


# =============================================================================
# Groups
# =============================================================================

@router.get("/groups", response_model=List[GroupResponse])
async def list_groups(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pairs = await frs_service.list_groups(db)
    return [_group_to_response(g, cnt) for g, cnt in pairs]


@router.post("/groups", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupCreate,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    group = await frs_service.create_group(
        db,
        name=body.name,
        group_type=body.group_type,
        color_code=body.color_code,
        description=body.description,
        alert_sound=body.alert_sound,
    )
    return _group_to_response(group, 0)


@router.get("/groups/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = await frs_service.get_group(db, group_id)
    if not group:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "group not found")
    cnt = await frs_service.member_count(db, group_id)
    return _group_to_response(group, cnt)


@router.put("/groups/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: str,
    body: GroupUpdate,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    group = await frs_service.get_group(db, group_id)
    if not group:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "group not found")
    fields = body.model_dump(exclude_unset=True)
    group = await frs_service.update_group(db, group, fields)
    cnt = await frs_service.member_count(db, group_id)
    return _group_to_response(group, cnt)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: str,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    group = await frs_service.get_group(db, group_id)
    if not group:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "group not found")
    await frs_service.delete_group(db, group)


# =============================================================================
# Persons
# =============================================================================

@router.get("/persons", response_model=PersonListResponse)
async def list_persons(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await frs_service.list_persons(
        db,
        limit=limit,
        offset=offset,
        search=search,
        group_id=group_id,
        category=category,
    )
    return PersonListResponse(
        items=[PersonResponse.model_validate(p) for p in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/persons", response_model=PersonResponse, status_code=status.HTTP_201_CREATED)
async def create_person(
    body: PersonCreate,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    if body.group_id:
        group = await frs_service.get_group(db, body.group_id)
        if not group:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "group not found")
    person = await frs_service.create_person(
        db,
        full_name=body.full_name,
        external_id=body.external_id,
        group_id=body.group_id,
        category=body.category,
        priority=body.priority,
        attributes=body.attributes,
    )
    return PersonResponse.model_validate(person)


@router.get("/persons/{person_id}", response_model=PersonResponse)
async def get_person(
    person_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    person = await frs_service.get_person(db, person_id)
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "person not found")
    return PersonResponse.model_validate(person)


@router.put("/persons/{person_id}", response_model=PersonResponse)
async def update_person(
    person_id: str,
    body: PersonUpdate,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    person = await frs_service.get_person(db, person_id)
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "person not found")
    fields = body.model_dump(exclude_unset=True)
    if "group_id" in fields and fields["group_id"]:
        group = await frs_service.get_group(db, fields["group_id"])
        if not group:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "group not found")
    person = await frs_service.update_person(db, person, fields)
    return PersonResponse.model_validate(person)


@router.delete("/persons/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    person_id: str,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    person = await frs_service.get_person(db, person_id)
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "person not found")
    await frs_service.delete_person(db, person)
    # Best-effort: drop the on-disk photo directory. The DB cascade already
    # removed the photo rows; the bridge reconciles scenario-side vectors.
    try:
        import shutil
        photo_dir = _person_photo_dir(person_id)
        if photo_dir.exists():
            shutil.rmtree(photo_dir, ignore_errors=True)
    except Exception:
        logger.warning("[frs] failed to remove photo dir for person %s", person_id)


# =============================================================================
# Photos
# =============================================================================

@router.post(
    "/persons/{person_id}/photos",
    response_model=PhotoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_person_photo(
    person_id: str,
    file: UploadFile = File(...),
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    person = await frs_service.get_person(db, person_id)
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "person not found")

    if file.content_type and file.content_type.lower() not in _ALLOWED_CONTENT:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"unsupported content type: {file.content_type}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    if len(data) > _MAX_PHOTO_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"photo exceeds {_MAX_PHOTO_BYTES // (1024 * 1024)} MB limit",
        )

    photo_id = str(uuid.uuid4())
    photo_dir = _person_photo_dir(person_id)
    photo_dir.mkdir(parents=True, exist_ok=True)
    rel_key = f"frs/persons/{person_id}/{photo_id}.jpg"
    abs_path = photo_dir / f"{photo_id}.jpg"
    try:
        with open(abs_path, "wb") as f:
            f.write(data)
    except OSError as e:
        logger.error("[frs] failed to write photo %s: %s", abs_path, e)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "failed to store photo"
        )

    # The id assigned by the DB default won't match our on-disk filename, so
    # pin the id explicitly via add_photo's underlying row. We create the row
    # with the matching id by writing the file first, then persisting metadata.
    from app.ai.models import FRSPhoto

    photo = FRSPhoto(
        id=photo_id,
        person_id=person_id,
        storage_key=rel_key,
        thumbnail_key=None,
        status="pending",
    )
    db.add(photo)
    await db.commit()
    await db.refresh(photo)
    # Recompute the parent person's counters / enrollment_status.
    await frs_service._recount_person(db, person_id)
    await db.refresh(photo)
    return PhotoResponse.model_validate(photo)


@router.get("/persons/{person_id}/photos", response_model=List[PhotoResponse])
async def list_person_photos(
    person_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    person = await frs_service.get_person(db, person_id)
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "person not found")
    photos = await frs_service.list_photos(db, person_id)
    return [PhotoResponse.model_validate(p) for p in photos]


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_photo(
    photo_id: str,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    photo = await frs_service.get_photo(db, photo_id)
    if not photo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo not found")
    storage_key = photo.storage_key
    await frs_service.delete_photo(db, photo)
    # Best-effort: remove the on-disk file.
    if storage_key:
        try:
            abs_path = Path(settings.DATA_PATH) / storage_key
            if abs_path.exists():
                os.remove(abs_path)
        except OSError:
            logger.warning("[frs] failed to remove photo file %s", storage_key)


@router.get("/photos/{photo_id}/image")
async def get_photo_image(
    photo_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    photo = await frs_service.get_photo(db, photo_id)
    if not photo or not photo.storage_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo not found")
    abs_path = Path(settings.DATA_PATH) / photo.storage_key
    if not abs_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo file not found")
    return FileResponse(
        path=str(abs_path),
        media_type="image/jpeg",
        filename=f"{photo_id}.jpg",
    )


# ── Bridge enrollment loop ───────────────────────────────────────────────
from sqlalchemy import select  # noqa: E402
from app.ai.models import FRSPhoto, FRSPerson  # noqa: E402


class _PendingPhoto(BaseModel):
    photo_id: str
    person_id: str
    person_name: str
    storage_key: Optional[str] = None


class _PhotoResult(BaseModel):
    status: str                      # "enrolled" | "failed"
    embedding_id: Optional[str] = None
    quality_score: Optional[float] = None
    liveness_score: Optional[float] = None
    error_code: Optional[str] = None
    error: Optional[str] = None


@router.get("/photos-pending", response_model=List[_PendingPhoto])
async def list_pending_photos(
    limit: int = 50,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    """Photos awaiting enrollment — the bridge polls this, runs EnrollFace per
    photo against the scenario, then PUTs the verdict to /photos/{id}/result."""
    rows = (await db.execute(
        select(FRSPhoto, FRSPerson)
        .join(FRSPerson, FRSPerson.id == FRSPhoto.person_id)
        .where(FRSPhoto.status == "pending")
        .limit(limit)
    )).all()
    return [
        _PendingPhoto(
            photo_id=ph.id, person_id=ph.person_id,
            person_name=pr.full_name, storage_key=ph.storage_key,
        )
        for ph, pr in rows
    ]


@router.put("/photos/{photo_id}/result", response_model=PhotoResponse)
async def report_photo_result(
    photo_id: str,
    body: _PhotoResult,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    photo = await frs_service.update_photo_result(
        db, photo_id,
        status=body.status,
        embedding_id=body.embedding_id,
        quality_score=body.quality_score,
        liveness_score=body.liveness_score,
        error_code=body.error_code,
        error=body.error,
    )
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo not found")
    return photo
