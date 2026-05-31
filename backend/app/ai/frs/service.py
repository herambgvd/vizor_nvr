# =============================================================================
# FRSService — persons / groups / photos CRUD (NVR-owned FRS metadata).
#
# The NVR owns the person gallery (groups, persons, photos) and a stable
# person_id the scenario service keys its Qdrant vectors on. Face EMBEDDINGS
# live in the standalone FRS gRPC scenario; a bridge polls this metadata —
# pending photos get enrolled (EnrollFace), and per-photo results land back
# here via `update_photo_result`. Deleting persons here just removes NVR rows;
# the bridge reconciles vector cleanup by polling for missing person_ids.
# =============================================================================
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import FRSGroup, FRSPerson, FRSPhoto

logger = logging.getLogger(__name__)


class FRSService:
    # ── Groups ────────────────────────────────────────────────────────────
    @staticmethod
    async def create_group(
        db: AsyncSession,
        *,
        name: str,
        group_type: Optional[str] = None,
        color_code: Optional[str] = None,
        description: Optional[str] = None,
        alert_sound: bool = False,
    ) -> FRSGroup:
        group = FRSGroup(
            name=name,
            group_type=group_type,
            color_code=color_code,
            description=description,
            alert_sound=alert_sound,
        )
        db.add(group)
        await db.commit()
        await db.refresh(group)
        return group

    @staticmethod
    async def list_groups(db: AsyncSession) -> List[Tuple[FRSGroup, int]]:
        """Return (group, member_count) pairs, ordered by name."""
        q = (
            select(FRSGroup, func.count(FRSPerson.id))
            .outerjoin(FRSPerson, FRSPerson.group_id == FRSGroup.id)
            .group_by(FRSGroup.id)
            .order_by(FRSGroup.name)
        )
        rows = (await db.execute(q)).all()
        return [(g, int(cnt or 0)) for g, cnt in rows]

    @staticmethod
    async def get_group(db: AsyncSession, group_id: str) -> Optional[FRSGroup]:
        return (await db.execute(
            select(FRSGroup).where(FRSGroup.id == group_id)
        )).scalar_one_or_none()

    @staticmethod
    async def member_count(db: AsyncSession, group_id: str) -> int:
        return int((await db.execute(
            select(func.count(FRSPerson.id)).where(FRSPerson.group_id == group_id)
        )).scalar() or 0)

    @staticmethod
    async def update_group(db: AsyncSession, group: FRSGroup, fields: dict) -> FRSGroup:
        for k, v in fields.items():
            setattr(group, k, v)
        await db.commit()
        await db.refresh(group)
        return group

    @staticmethod
    async def delete_group(db: AsyncSession, group: FRSGroup) -> None:
        # Persons keep existing (group_id ON DELETE SET NULL).
        await db.delete(group)
        await db.commit()

    # ── Persons ───────────────────────────────────────────────────────────
    @staticmethod
    async def create_person(
        db: AsyncSession,
        *,
        full_name: str,
        external_id: Optional[str] = None,
        group_id: Optional[str] = None,
        category: str = "standard",
        priority: int = 0,
        attributes: Optional[dict] = None,
    ) -> FRSPerson:
        person = FRSPerson(
            full_name=full_name,
            external_id=external_id,
            group_id=group_id,
            category=category,
            priority=priority,
            attributes=attributes,
        )
        db.add(person)
        await db.commit()
        await db.refresh(person)
        return person

    @staticmethod
    async def list_persons(
        db: AsyncSession,
        *,
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None,
        group_id: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Tuple[List[FRSPerson], int]:
        """Return (rows, total) for a filtered, paginated person list."""
        filters = []
        if search:
            like = f"%{search.strip()}%"
            filters.append(or_(
                FRSPerson.full_name.ilike(like),
                FRSPerson.external_id.ilike(like),
            ))
        if group_id:
            filters.append(FRSPerson.group_id == group_id)
        if category:
            filters.append(FRSPerson.category == category)

        count_q = select(func.count(FRSPerson.id))
        rows_q = select(FRSPerson)
        for f in filters:
            count_q = count_q.where(f)
            rows_q = rows_q.where(f)

        total = int((await db.execute(count_q)).scalar() or 0)
        rows_q = (
            rows_q.order_by(FRSPerson.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await db.execute(rows_q)).scalars().all()
        return list(rows), total

    @staticmethod
    async def get_person(db: AsyncSession, person_id: str) -> Optional[FRSPerson]:
        return (await db.execute(
            select(FRSPerson).where(FRSPerson.id == person_id)
        )).scalar_one_or_none()

    @staticmethod
    async def update_person(db: AsyncSession, person: FRSPerson, fields: dict) -> FRSPerson:
        for k, v in fields.items():
            setattr(person, k, v)
        await db.commit()
        await db.refresh(person)
        return person

    @staticmethod
    async def delete_person(db: AsyncSession, person: FRSPerson) -> None:
        """Delete the NVR person + its photos (FK cascade). Vector cleanup in
        the scenario service is handled by the bridge, which polls for
        person_ids that no longer exist here."""
        await db.delete(person)
        await db.commit()

    @staticmethod
    async def set_enrollment_status(
        db: AsyncSession, person: FRSPerson, status: str
    ) -> FRSPerson:
        person.enrollment_status = status
        await db.commit()
        await db.refresh(person)
        return person

    # ── Photos ────────────────────────────────────────────────────────────
    @staticmethod
    async def add_photo(
        db: AsyncSession,
        *,
        person_id: str,
        storage_key: Optional[str] = None,
        thumbnail_key: Optional[str] = None,
    ) -> FRSPhoto:
        """Create a pending photo row. The bridge picks up pending photos,
        runs EnrollFace, then calls `update_photo_result`."""
        photo = FRSPhoto(
            person_id=person_id,
            storage_key=storage_key,
            thumbnail_key=thumbnail_key,
            status="pending",
        )
        db.add(photo)
        await db.commit()
        await db.refresh(photo)
        # A freshly-added photo means at least one enrollment is in flight.
        await FRSService._recount_person(db, person_id)
        await db.refresh(photo)
        return photo

    @staticmethod
    async def list_photos(db: AsyncSession, person_id: str) -> List[FRSPhoto]:
        rows = (await db.execute(
            select(FRSPhoto)
            .where(FRSPhoto.person_id == person_id)
            .order_by(FRSPhoto.created_at.desc())
        )).scalars().all()
        return list(rows)

    @staticmethod
    async def get_photo(db: AsyncSession, photo_id: str) -> Optional[FRSPhoto]:
        return (await db.execute(
            select(FRSPhoto).where(FRSPhoto.id == photo_id)
        )).scalar_one_or_none()

    @staticmethod
    async def delete_photo(db: AsyncSession, photo: FRSPhoto) -> None:
        person_id = photo.person_id
        await db.delete(photo)
        await db.commit()
        await FRSService._recount_person(db, person_id)

    @staticmethod
    async def update_photo_result(
        db: AsyncSession,
        photo_id: str,
        *,
        status: str,
        embedding_id: Optional[str] = None,
        quality_score: Optional[float] = None,
        liveness_score: Optional[float] = None,
        error_code: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[FRSPhoto]:
        """Called by the bridge after EnrollFace to record the verdict, then
        recompute the parent person's photo counters + enrollment_status."""
        photo = await FRSService.get_photo(db, photo_id)
        if photo is None:
            return None
        photo.status = status
        if embedding_id is not None:
            photo.embedding_id = embedding_id
        if quality_score is not None:
            photo.quality_score = quality_score
        if liveness_score is not None:
            photo.liveness_score = liveness_score
        photo.error_code = error_code
        photo.error = error
        await db.commit()
        await db.refresh(photo)
        await FRSService._recount_person(db, photo.person_id)
        await db.refresh(photo)
        return photo

    # ── Internal: recompute person counters + enrollment_status ───────────
    @staticmethod
    async def _recount_person(db: AsyncSession, person_id: str) -> None:
        person = await FRSService.get_person(db, person_id)
        if person is None:
            return

        photo_count = int((await db.execute(
            select(func.count(FRSPhoto.id)).where(FRSPhoto.person_id == person_id)
        )).scalar() or 0)
        enrolled_count = int((await db.execute(
            select(func.count(FRSPhoto.id)).where(
                FRSPhoto.person_id == person_id,
                FRSPhoto.status == "enrolled",
            )
        )).scalar() or 0)
        pending_count = int((await db.execute(
            select(func.count(FRSPhoto.id)).where(
                FRSPhoto.person_id == person_id,
                FRSPhoto.status == "pending",
            )
        )).scalar() or 0)

        person.photo_count = photo_count
        person.enrolled_photo_count = enrolled_count

        if photo_count == 0:
            person.enrollment_status = "unenrolled"
        elif enrolled_count > 0:
            person.enrollment_status = "enrolled"
        elif pending_count > 0:
            person.enrollment_status = "pending"
        else:
            # photos exist, none enrolled, none pending → all failed.
            person.enrollment_status = "failed"

        await db.commit()


frs_service = FRSService()
