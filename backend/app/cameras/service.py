# =============================================================================
# Camera Service — CRUD, group management
# =============================================================================

import logging
import re
from typing import Optional, List
from datetime import datetime, timezone

from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.cameras.models import (
    Camera, CameraGroup, CameraStatus,
    CameraCreate, CameraUpdate,
    CameraGroupCreate, CameraGroupUpdate,
    camera_group_members, user_camera_groups,
)
from app.core.crypto import encrypt_value, decrypt_value

logger = logging.getLogger(__name__)

# Stream URL fields that may embed credentials (rtsp://user:pass@host/...)
_STREAM_URL_FIELDS = ("main_stream_url", "sub_stream_url", "detect_stream_url")

# Sentinel inserted in place of embedded credentials when returning URLs to
# clients. If an incoming update still contains this marker we treat the URL as
# unchanged and preserve the stored value (mirrors the ONVIF-password pattern).
_CRED_MASK = "••••"  # ••••
_USERINFO_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*://)([^/\s]+)@")


def mask_stream_url(url: Optional[str]) -> Optional[str]:
    """Mask credentials embedded in a stream URL before returning to clients.

    rtsp://user:pass@host:554/path -> rtsp://••••:••••@host:554/path
    URLs without embedded credentials are returned unchanged.
    """
    if not url or not isinstance(url, str):
        return url
    return _USERINFO_RE.sub(lambda m: f"{m.group(1)}{_CRED_MASK}:{_CRED_MASK}@", url)


def _is_masked_stream_url(value) -> bool:
    """True if the value still contains the credential mask sentinel."""
    return isinstance(value, str) and _CRED_MASK in value


class CameraService:

    # ------------------------------------------------------------------
    # Camera CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def get_all(db: AsyncSession, camera_ids: Optional[List[str]] = None) -> List[Camera]:
        """
        Get all cameras, optionally filtered to specific IDs (for RBAC).
        camera_ids=None means return all (admin).
        """
        q = (
            select(Camera)
            .options(selectinload(Camera.groups))
            .order_by(Camera.display_order, Camera.created_at)
        )
        if camera_ids is not None:
            q = q.where(Camera.id.in_(camera_ids))
        result = await db.execute(q)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(db: AsyncSession, camera_id: str) -> Optional[Camera]:
        result = await db.execute(
            select(Camera).options(selectinload(Camera.groups)).where(Camera.id == camera_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, data: CameraCreate) -> Camera:
        # Encrypt ONVIF credentials (username + password) before persisting
        encrypted_password = encrypt_value(data.onvif_password) if data.onvif_password else None
        encrypted_username = encrypt_value(data.onvif_username) if data.onvif_username else None

        camera = Camera(
            name=data.name,
            main_stream_url=data.main_stream_url,
            sub_stream_url=data.sub_stream_url,
            detect_stream_url=data.detect_stream_url,
            onvif_host=data.onvif_host,
            onvif_port=data.onvif_port,
            onvif_username=encrypted_username,
            onvif_password=encrypted_password,
            onvif_profile_token=getattr(data, "onvif_profile_token", None),
            location=data.location,
            description=data.description,
            is_enabled=data.is_enabled,
            recording_fps=data.recording_fps,
            recording_mode=data.recording_mode,
            recording_schedule=data.recording_schedule,
            storage_pool_id=data.storage_pool_id,
            bandwidth_limit_kbps=data.bandwidth_limit_kbps,
            retention_days=data.retention_days,
            record_substream=data.record_substream,
            pre_buffer_seconds=data.pre_buffer_seconds,
            post_buffer_seconds=data.post_buffer_seconds,
            anr_enabled=data.anr_enabled,
            anr_max_gap_hours=data.anr_max_gap_hours,
            pos_overlay_config=data.pos_overlay_config,
            dewarp_config=data.dewarp_config,
            onvif_events_enabled=data.onvif_events_enabled,
            onvif_event_topics=data.onvif_event_topics,
            ptz_tour_config=data.ptz_tour_config,
            ptz_tour_enabled=data.ptz_tour_enabled,
            status=CameraStatus.OFFLINE.value,
        )
        db.add(camera)
        await db.flush()  # populate id

        # Assign groups
        if data.group_ids:
            await CameraService._set_groups(db, camera.id, data.group_ids)

        await db.commit()
        await db.refresh(camera, ["groups"])
        return camera

    @staticmethod
    async def update(db: AsyncSession, camera_id: str, data: CameraUpdate) -> Optional[Camera]:
        camera = await CameraService.get_by_id(db, camera_id)
        if not camera:
            return None
        update_dict = data.model_dump(exclude_unset=True, exclude={"group_ids"})

        # Preserve stored stream URLs when the client submits a value that is
        # still masked (unchanged) — avoids overwriting real credentials with
        # the mask returned by to_response().
        for field in _STREAM_URL_FIELDS:
            if field in update_dict and _is_masked_stream_url(update_dict[field]):
                del update_dict[field]

        # Encrypt ONVIF credentials if being updated
        if update_dict.get("onvif_password"):
            update_dict["onvif_password"] = encrypt_value(update_dict["onvif_password"])
        if update_dict.get("onvif_username"):
            update_dict["onvif_username"] = encrypt_value(update_dict["onvif_username"])

        for k, v in update_dict.items():
            setattr(camera, k, v)
        if data.group_ids is not None:
            await CameraService._set_groups(db, camera_id, data.group_ids)
        await db.commit()
        await db.refresh(camera, ["groups"])
        return camera

    @staticmethod
    def get_decrypted_onvif_password(camera: Camera) -> Optional[str]:
        """Get decrypted ONVIF password for a camera."""
        if not camera.onvif_password:
            return None
        return decrypt_value(camera.onvif_password)

    @staticmethod
    def get_decrypted_onvif_username(camera: Camera) -> Optional[str]:
        """Get decrypted ONVIF username for a camera."""
        if not camera.onvif_username:
            return None
        return decrypt_value(camera.onvif_username)

    @staticmethod
    async def delete(db: AsyncSession, camera_id: str) -> bool:
        camera = await CameraService.get_by_id(db, camera_id)
        if not camera:
            return False
        await db.delete(camera)
        await db.commit()
        return True

    @staticmethod
    async def count(db: AsyncSession) -> int:
        result = await db.execute(select(func.count(Camera.id)))
        return result.scalar()

    @staticmethod
    async def cameras_needing_recording(db: AsyncSession) -> List[Camera]:
        """Cameras that are enabled + is_recording=True but may need FFmpeg restart."""
        result = await db.execute(
            select(Camera).where(Camera.is_enabled.is_(True), Camera.is_recording.is_(True))
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Group helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _set_groups(db: AsyncSession, camera_id: str, group_ids: List[str]):
        """Replace camera's group memberships."""
        await db.execute(
            delete(camera_group_members).where(camera_group_members.c.camera_id == camera_id)
        )
        for gid in group_ids:
            await db.execute(camera_group_members.insert().values(camera_id=camera_id, group_id=gid))

    # ------------------------------------------------------------------
    # Camera Groups
    # ------------------------------------------------------------------

    @staticmethod
    async def get_all_groups(db: AsyncSession) -> List[CameraGroup]:
        result = await db.execute(
            select(CameraGroup).options(selectinload(CameraGroup.cameras)).order_by(CameraGroup.name)
        )
        return list(result.scalars().all())

    @staticmethod
    async def create_group(db: AsyncSession, data: CameraGroupCreate) -> CameraGroup:
        group = CameraGroup(name=data.name, description=data.description, color=data.color)
        db.add(group)
        await db.flush()
        if data.camera_ids:
            for cid in data.camera_ids:
                await db.execute(camera_group_members.insert().values(camera_id=cid, group_id=group.id))
        await db.commit()
        await db.refresh(group, ["cameras"])
        return group

    @staticmethod
    async def update_group(db: AsyncSession, group_id: str, data: CameraGroupUpdate) -> Optional[CameraGroup]:
        result = await db.execute(select(CameraGroup).where(CameraGroup.id == group_id))
        group = result.scalar_one_or_none()
        if not group:
            return None
        if data.name is not None:
            group.name = data.name
        if data.description is not None:
            group.description = data.description
        if data.color is not None:
            group.color = data.color
        if data.camera_ids is not None:
            await db.execute(
                delete(camera_group_members).where(camera_group_members.c.group_id == group_id)
            )
            for cid in data.camera_ids:
                await db.execute(camera_group_members.insert().values(camera_id=cid, group_id=group_id))
        await db.commit()
        await db.refresh(group, ["cameras"])
        return group

    @staticmethod
    async def delete_group(db: AsyncSession, group_id: str) -> bool:
        result = await db.execute(select(CameraGroup).where(CameraGroup.id == group_id))
        group = result.scalar_one_or_none()
        if not group:
            return False
        await db.delete(group)
        await db.commit()
        return True

    # ------------------------------------------------------------------
    # User ↔ Group access
    # ------------------------------------------------------------------

    @staticmethod
    async def grant_user_group(db: AsyncSession, user_id: str, group_id: str):
        await db.execute(user_camera_groups.insert().values(user_id=user_id, group_id=group_id))
        await db.commit()

    @staticmethod
    async def revoke_user_group(db: AsyncSession, user_id: str, group_id: str):
        await db.execute(
            delete(user_camera_groups).where(
                user_camera_groups.c.user_id == user_id,
                user_camera_groups.c.group_id == group_id,
            )
        )
        await db.commit()

    @staticmethod
    async def get_user_groups(db: AsyncSession, user_id: str) -> List[str]:
        result = await db.execute(
            select(user_camera_groups.c.group_id).where(user_camera_groups.c.user_id == user_id)
        )
        return [row[0] for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    @staticmethod
    def to_response(camera: Camera) -> dict:
        data = {
            **{c.name: getattr(camera, c.name) for c in Camera.__table__.columns},
            "group_ids": [g.id for g in camera.groups] if camera.groups else [],
        }
        # Never expose credentials embedded in stream URLs to clients.
        for field in _STREAM_URL_FIELDS:
            if field in data:
                data[field] = mask_stream_url(data[field])
        return data
