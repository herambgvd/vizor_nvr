# =============================================================================
# Bookmark Router — CRUD endpoints
# =============================================================================

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.bookmarks.models import BookmarkCreate, BookmarkUpdate, BookmarkResponse
from app.bookmarks.service import BookmarkService
from app.core.dependencies import require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bookmarks", tags=["Bookmarks"])
svc = BookmarkService()


@router.post("", response_model=BookmarkResponse, status_code=201)
async def create_bookmark(
    body: BookmarkCreate,
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
):
    bookmark = await svc.create(db, body, user["id"])
    return bookmark


@router.get("", response_model=List[BookmarkResponse])
async def list_bookmarks(
    camera_id: Optional[str] = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
):
    if camera_id:
        return await svc.list_by_camera(db, camera_id, limit, offset)
    return await svc.list_by_user(db, user["id"], limit, offset)


@router.get("/{bookmark_id}", response_model=BookmarkResponse)
async def get_bookmark(
    bookmark_id: str,
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
):
    bookmark = await svc.get_by_id(db, bookmark_id)
    if not bookmark:
        raise HTTPException(404, "Bookmark not found")
    return bookmark


@router.patch("/{bookmark_id}", response_model=BookmarkResponse)
async def update_bookmark(
    bookmark_id: str,
    body: BookmarkUpdate,
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
):
    bookmark = await svc.get_by_id(db, bookmark_id)
    if not bookmark:
        raise HTTPException(404, "Bookmark not found")
    if bookmark.user_id != user["id"] and user.get("role") != "admin":
        raise HTTPException(403, "Cannot edit another user's bookmark")
    return await svc.update(db, bookmark, body)


@router.delete("/{bookmark_id}")
async def delete_bookmark(
    bookmark_id: str,
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
):
    bookmark = await svc.get_by_id(db, bookmark_id)
    if not bookmark:
        raise HTTPException(404, "Bookmark not found")
    if bookmark.user_id != user["id"] and user.get("role") != "admin":
        raise HTTPException(403, "Cannot delete another user's bookmark")
    await svc.remove(db, bookmark_id)
    return {"detail": "Bookmark deleted"}
