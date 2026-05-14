# =============================================================================
# FRS Router — Persons + Groups CRUD for the face recognition gallery.
#
# Photos are managed by a separate endpoint (frs_photos_router) because
# they involve binary uploads + Qdrant operations. Investigations have
# their own router too (frs_investigations_router) since they kick off
# background jobs.
#
# Permission model: viewing persons/groups requires `view_live`; mutating
# requires `manage_camera` (FRS-specific permissions added in Phase 2).
# =============================================================================

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import FRSGroup, FRSPerson, FRSPhoto
from app.core.dependencies import get_current_user, require_permission
from app.database import get_db


router = APIRouter(prefix="/api/ai/frs", tags=["AI · FRS"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    color: Optional[str] = Field(None, max_length=20)


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    color: Optional[str] = Field(None, max_length=20)


class GroupOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    color: Optional[str]
    created_at: datetime
    person_count: int = 0

    class Config:
        from_attributes = True


class PersonCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    external_id: Optional[str] = Field(None, max_length=100)
    group_id: Optional[str] = None
    attributes: Optional[dict] = None


class PersonUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    external_id: Optional[str] = Field(None, max_length=100)
    group_id: Optional[str] = None
    attributes: Optional[dict] = None


class PersonOut(BaseModel):
    id: str
    name: str
    external_id: Optional[str]
    group_id: Optional[str]
    group_name: Optional[str] = None
    attributes: Optional[dict]
    enrolled_at: Optional[datetime]
    last_seen_at: Optional[datetime]
    photo_count: int = 0

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

@router.get("/groups", response_model=List[GroupOut])
async def list_groups(
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[GroupOut]:
    """List FRS groups with person counts."""
    # Single round-trip with subquery person count
    stmt = (
        select(FRSGroup, func.count(FRSPerson.id).label("pcount"))
        .outerjoin(FRSPerson, FRSPerson.group_id == FRSGroup.id)
        .group_by(FRSGroup.id)
        .order_by(FRSGroup.name)
    )
    result = await db.execute(stmt)
    out: List[GroupOut] = []
    for group, pcount in result.all():
        gd = GroupOut.model_validate(group)
        gd.person_count = pcount or 0
        out.append(gd)
    return out


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    data: GroupCreate,
    _user=Depends(require_permission("manage_groups")),
    db: AsyncSession = Depends(get_db),
) -> GroupOut:
    # Uniqueness check first so we return 409 instead of generic 500
    existing = await db.execute(select(FRSGroup).where(FRSGroup.name == data.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Group '{data.name}' already exists"
        )
    group = FRSGroup(
        name=data.name, description=data.description, color=data.color
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return GroupOut.model_validate(group)


@router.patch("/groups/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: str,
    data: GroupUpdate,
    _user=Depends(require_permission("manage_groups")),
    db: AsyncSession = Depends(get_db),
) -> GroupOut:
    group = await db.get(FRSGroup, group_id)
    if not group:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await db.commit()
    await db.refresh(group)
    return GroupOut.model_validate(group)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: str,
    _user=Depends(require_permission("manage_groups")),
    db: AsyncSession = Depends(get_db),
) -> None:
    group = await db.get(FRSGroup, group_id)
    if not group:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    # ON DELETE SET NULL on persons.group_id keeps persons safe
    await db.delete(group)
    await db.commit()


# ---------------------------------------------------------------------------
# Persons
# ---------------------------------------------------------------------------

@router.get("/persons", response_model=List[PersonOut])
async def list_persons(
    q: Optional[str] = Query(None, description="Search name or external_id"),
    group_id: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[PersonOut]:
    stmt = (
        select(
            FRSPerson,
            FRSGroup.name.label("group_name"),
            func.count(FRSPhoto.id).label("pcount"),
        )
        .outerjoin(FRSGroup, FRSPerson.group_id == FRSGroup.id)
        .outerjoin(FRSPhoto, FRSPhoto.person_id == FRSPerson.id)
        .group_by(FRSPerson.id, FRSGroup.name)
        .order_by(FRSPerson.name)
        .limit(limit)
        .offset(offset)
    )
    if group_id:
        stmt = stmt.where(FRSPerson.group_id == group_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(FRSPerson.name.ilike(like), FRSPerson.external_id.ilike(like)))

    result = await db.execute(stmt)
    out: List[PersonOut] = []
    for person, group_name, pcount in result.all():
        pd = PersonOut.model_validate(person)
        pd.group_name = group_name
        pd.photo_count = pcount or 0
        out.append(pd)
    return out


@router.get("/persons/{person_id}", response_model=PersonOut)
async def get_person(
    person_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonOut:
    stmt = (
        select(
            FRSPerson,
            FRSGroup.name.label("group_name"),
            func.count(FRSPhoto.id).label("pcount"),
        )
        .outerjoin(FRSGroup, FRSPerson.group_id == FRSGroup.id)
        .outerjoin(FRSPhoto, FRSPhoto.person_id == FRSPerson.id)
        .where(FRSPerson.id == person_id)
        .group_by(FRSPerson.id, FRSGroup.name)
    )
    result = await db.execute(stmt)
    row = result.one_or_none()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    person, group_name, pcount = row
    pd = PersonOut.model_validate(person)
    pd.group_name = group_name
    pd.photo_count = pcount or 0
    return pd


@router.post("/persons", response_model=PersonOut, status_code=status.HTTP_201_CREATED)
async def create_person(
    data: PersonCreate,
    _user=Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
) -> PersonOut:
    if data.external_id:
        existing = await db.execute(
            select(FRSPerson).where(FRSPerson.external_id == data.external_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Person with external_id={data.external_id} already exists",
            )
    if data.group_id:
        group = await db.get(FRSGroup, data.group_id)
        if not group:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "group_id does not exist")

    person = FRSPerson(
        name=data.name,
        external_id=data.external_id,
        group_id=data.group_id,
        attributes=data.attributes,
    )
    db.add(person)
    await db.commit()
    await db.refresh(person)
    return PersonOut.model_validate(person)


@router.patch("/persons/{person_id}", response_model=PersonOut)
async def update_person(
    person_id: str,
    data: PersonUpdate,
    _user=Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
) -> PersonOut:
    person = await db.get(FRSPerson, person_id)
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(person, field, value)
    await db.commit()
    await db.refresh(person)
    return PersonOut.model_validate(person)


@router.delete("/persons/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    person_id: str,
    _user=Depends(require_permission("manage_camera")),
    db: AsyncSession = Depends(get_db),
) -> None:
    person = await db.get(FRSPerson, person_id)
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    # NOTE: photos cascade delete on FK. Qdrant points orphan until a
    # scheduled cleanup job runs. Phase 2 will wire a delete hook that
    # also removes the Qdrant points synchronously.
    await db.delete(person)
    await db.commit()
