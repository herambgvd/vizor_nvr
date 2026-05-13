# =============================================================================
# RBAC Permission Checker
# =============================================================================
# Centralised logic for "can user X do action Y on resource Z?"
#
# Flow:
#   1. Admin role  → always allowed
#   2. Role check  → does the role's permission list include the action?
#   3. Camera-scope → is the camera in a group the user has access to?
# =============================================================================

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def has_permission(
    db: AsyncSession,
    user: dict,
    action: str,
    camera_id: Optional[str] = None,
) -> bool:
    """
    Check whether *user* may perform *action*, optionally scoped to *camera_id*.

    Parameters
    ----------
    db        : active database session
    user      : dict from JWT (keys: id, username, role, role_id)
    action    : a PermissionAction string value, e.g. "control_recording"
    camera_id : optional camera UUID — when given, also checks group access
    """
    # Admins bypass everything
    if user.get("role") == "admin":
        return True

    # ── 1. Role-level permission ────────────────────────────────────────
    # Lazy import to avoid circular deps at module load time
    from app.auth.models import Role

    result = await db.execute(select(Role).where(Role.name == user.get("role")))
    role_obj = result.scalar_one_or_none()
    if not role_obj:
        return False

    role_perms = role_obj.permissions or []
    if action not in role_perms:
        return False

    # ── 2. Camera-group scope ───────────────────────────────────────────
    if camera_id:
        allowed = await user_can_access_camera(db, user["id"], camera_id)
        if not allowed:
            return False

    return True


async def user_can_access_camera(
    db: AsyncSession,
    user_id: str,
    camera_id: str,
) -> bool:
    """True if user has access to camera via any of:
       - direct grant (user_camera_access)
       - group membership (user_camera_groups → camera_group_members)
    """
    from app.cameras.models import (
        camera_group_members, user_camera_groups, user_camera_access,
    )

    # 1. Direct grant
    direct = await db.execute(
        select(user_camera_access.c.camera_id).where(
            user_camera_access.c.user_id == user_id,
            user_camera_access.c.camera_id == camera_id,
        )
    )
    if direct.scalar_one_or_none() is not None:
        return True

    # 2. Group grant
    ug = await db.execute(
        select(user_camera_groups.c.group_id).where(
            user_camera_groups.c.user_id == user_id
        )
    )
    group_ids = [row[0] for row in ug.fetchall()]
    if not group_ids:
        return False
    cg = await db.execute(
        select(camera_group_members.c.camera_id).where(
            camera_group_members.c.camera_id == camera_id,
            camera_group_members.c.group_id.in_(group_ids),
        )
    )
    return cg.scalar_one_or_none() is not None


async def get_accessible_camera_ids(
    db: AsyncSession,
    user: dict,
) -> Optional[list]:
    """
    Return list of camera IDs the user can access, or None if admin (= all cameras).
    Union of direct grants and group grants.
    """
    if user.get("role") == "admin":
        return None  # None means "all"

    from app.cameras.models import (
        camera_group_members, user_camera_groups, user_camera_access,
    )

    # Direct grants
    direct = await db.execute(
        select(user_camera_access.c.camera_id).where(
            user_camera_access.c.user_id == user["id"]
        )
    )
    cams = {row[0] for row in direct.fetchall()}

    # Group grants
    ug = await db.execute(
        select(user_camera_groups.c.group_id).where(
            user_camera_groups.c.user_id == user["id"]
        )
    )
    group_ids = [row[0] for row in ug.fetchall()]
    if group_ids:
        cg = await db.execute(
            select(camera_group_members.c.camera_id).where(
                camera_group_members.c.group_id.in_(group_ids)
            ).distinct()
        )
        for row in cg.fetchall():
            cams.add(row[0])

    return list(cams)
