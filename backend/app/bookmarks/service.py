# =============================================================================
# Bookmark Service — CRUD
# =============================================================================

import logging
from typing import Optional, List

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.bookmarks.models import Bookmark, BookmarkCreate, BookmarkUpdate

logger = logging.getLogger(__name__)


class BookmarkService:

    async def create(
        self, db: AsyncSession, data: BookmarkCreate, user_id: str,
    ) -> Bookmark:
        bookmark = Bookmark(
            camera_id=data.camera_id,
            recording_id=data.recording_id,
            timestamp=data.timestamp,
            abs_time=data.abs_time,
            label=data.label,
            category=data.category,
            note=data.note,
            user_id=user_id,
        )
        db.add(bookmark)
        await db.commit()
        await db.refresh(bookmark)
        return bookmark

    async def get_by_id(self, db: AsyncSession, bookmark_id: str) -> Optional[Bookmark]:
        result = await db.execute(select(Bookmark).where(Bookmark.id == bookmark_id))
        return result.scalar_one_or_none()

    async def list_by_camera(
        self, db: AsyncSession, camera_id: str, limit: int = 200, offset: int = 0,
    ) -> List[Bookmark]:
        result = await db.execute(
            select(Bookmark)
            .where(Bookmark.camera_id == camera_id)
            .order_by(Bookmark.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_user(
        self, db: AsyncSession, user_id: str, limit: int = 200, offset: int = 0,
    ) -> List[Bookmark]:
        result = await db.execute(
            select(Bookmark)
            .where(Bookmark.user_id == user_id)
            .order_by(Bookmark.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_camera(self, db: AsyncSession, camera_id: str) -> int:
        result = await db.execute(
            select(func.count(Bookmark.id)).where(Bookmark.camera_id == camera_id)
        )
        return result.scalar() or 0

    async def count_by_user(self, db: AsyncSession, user_id: str) -> int:
        result = await db.execute(
            select(func.count(Bookmark.id)).where(Bookmark.user_id == user_id)
        )
        return result.scalar() or 0

    async def update(
        self, db: AsyncSession, bookmark: Bookmark, data: BookmarkUpdate,
    ) -> Bookmark:
        if data.note is not None:
            bookmark.note = data.note
        if data.label is not None:
            bookmark.label = data.label
        if data.category is not None:
            bookmark.category = data.category
        await db.commit()
        await db.refresh(bookmark)
        return bookmark

    async def remove(self, db: AsyncSession, bookmark_id: str) -> bool:
        result = await db.execute(
            delete(Bookmark).where(Bookmark.id == bookmark_id)
        )
        await db.commit()
        return result.rowcount > 0
