# =============================================================================
# Auth Router — registration, login, token refresh, user management
# =============================================================================

import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, delete

from app.database import get_db
from app.auth.models import (
    User, UserCreate, UserUpdate, UserLogin, UserResponse,
    TokenResponse, RefreshRequest, LogoutRequest, RoleResponse, Role,
    RefreshToken,
)
from app.auth.service import AuthService
from app.core.security import create_access_token, create_refresh_token, verify_token
from app.core.dependencies import get_current_user, get_admin_user
from app.core.audit_logger import write_audit, client_ip
from app.core.rate_limiter import auth_limiter
from app.config import settings as app_settings


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _within_access_schedule(schedule: dict) -> bool:
    """Return True if 'now' falls inside the user's access window.
    Schedule shape: {"monday": [{"start": "08:00", "end": "18:00"}], ...}
    Empty list or missing day → blocked. Empty dict / None → always allowed."""
    if not schedule:
        return True
    now = datetime.now()
    day = now.strftime("%A").lower()
    rules = schedule.get(day, [])
    if not rules:
        # No window today = no access
        return False
    cur = now.strftime("%H:%M")
    for r in rules:
        s, e = r.get("start", "00:00"), r.get("end", "23:59")
        if s > e:
            if cur >= s or cur <= e:
                return True
        elif s <= cur <= e:
            return True
    return False


async def _store_refresh_token(
    db: AsyncSession, user_id: str, token: str, request: Request
):
    """Persist a refresh token hash for revocation tracking."""
    expires_at = datetime.utcnow() + timedelta(days=app_settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    ua = request.headers.get("user-agent", "")[:500]
    ip = client_ip(request)
    rt = RefreshToken(
        user_id=user_id,
        token_hash=_hash_token(token),
        expires_at=expires_at,
        user_agent=ua,
        ip_address=ip,
    )
    db.add(rt)


async def _revoke_token_hash(db: AsyncSession, token: str):
    """Mark a refresh token as revoked."""
    h = _hash_token(token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == h, RefreshToken.revoked.is_(False))
    )
    rt = result.scalar_one_or_none()
    if rt:
        rt.revoked = True
        rt.revoked_at = datetime.utcnow()


async def _validate_refresh_token_in_db(db: AsyncSession, token: str) -> bool:
    """Return True if the token exists in DB and is NOT revoked. Also bumps
    last_seen_at so the session list shows the most-recent activity time."""
    h = _hash_token(token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == h,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.utcnow(),
        )
    )
    rt = result.scalar_one_or_none()
    if rt is None:
        return False
    rt.last_seen_at = datetime.utcnow()
    await db.commit()
    return True

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])
svc = AuthService()


# ------------------------------------------------------------------
# First-time setup check (public, no auth)
# ------------------------------------------------------------------

@router.get("/setup")
async def setup_status(db: AsyncSession = Depends(get_db)):
    """Return whether initial admin setup is still required (no users yet)."""
    from sqlalchemy import func as sqlfunc
    count_result = await db.execute(select(sqlfunc.count(User.id)))
    count = count_result.scalar()
    return {"required": count == 0}


# ------------------------------------------------------------------
# Public endpoints (rate limited)
# ------------------------------------------------------------------

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    data: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(auth_limiter.limit),
):
    """First-time admin setup only. Locked once any user exists."""
    from sqlalchemy import func as sqlfunc
    count_result = await db.execute(select(sqlfunc.count(User.id)))
    if count_result.scalar() > 0:
        raise HTTPException(
            403,
            "Registration is closed. Ask an administrator to create your account."
        )
    # Check duplicates
    if await svc.get_user_by_username(db, data.username):
        raise HTTPException(400, "Username already taken")

    try:
        user = await svc.create_user(db, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    # Eager-load role for response
    await db.refresh(user, ["role"])

    token_data = svc.build_token_data(user)
    access = create_access_token(token_data)
    refresh = create_refresh_token(token_data)

    # Persist refresh token for revocation tracking
    await _store_refresh_token(db, user.id, refresh, request)

    await write_audit(
        db, action="user_create", user_id=user.id, username=user.username,
        ip_address=client_ip(request), resource_type="user", resource_id=user.id,
        description=f"User registered: {user.username}",
    )
    await db.commit()

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user=UserResponse(**svc.user_to_response(user)),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    creds: UserLogin,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(auth_limiter.limit),
):
    """Authenticate with username + password → JWT tokens."""
    result = await db.execute(
        select(User).options(selectinload(User.role)).where(User.username == creds.username)
    )
    user_check = result.scalar_one_or_none()

    user = await svc.authenticate(db, creds.username, creds.password)
    if not user:
        await write_audit(
            db, action="login_failed", username=creds.username,
            ip_address=client_ip(request), severity="warning",
            description=f"Failed login attempt for: {creds.username}",
        )
        await db.commit()
        raise HTTPException(401, "Invalid username or password")

    # ── Password policy enforcement (Phase 5.6) ──────────────────────────
    policy_msg = await svc.check_password_policy_on_login(db, user)
    if policy_msg:
        await write_audit(
            db, action="login_password_policy", user_id=user.id, username=user.username,
            ip_address=client_ip(request), severity="warning",
            description=policy_msg,
        )
        await db.commit()
        raise HTTPException(403, policy_msg, headers={"X-Password-Change-Required": "true"})

    # ── TOTP gate (Phase 5.3) ────────────────────────────────────────────
    if user.totp_enabled and user.totp_secret:
        from app.core.crypto import decrypt_value
        from app.auth import totp_service
        if not creds.totp_token:
            raise HTTPException(401, "TOTP token required", headers={"X-2FA-Required": "true"})
        secret = decrypt_value(user.totp_secret)
        if not totp_service.verify(secret, creds.totp_token):
            # Allow recovery codes too — single-use.
            recovery = list(user.totp_recovery_codes or [])
            if creds.totp_token in recovery:
                recovery.remove(creds.totp_token)
                user.totp_recovery_codes = recovery
                await db.commit()
            else:
                await write_audit(
                    db, action="login_2fa_failed", user_id=user.id, username=user.username,
                    ip_address=client_ip(request), severity="warning",
                )
                await db.commit()
                raise HTTPException(401, "Invalid 2FA token")

    # ── Time-bound access (Phase 6.4) ────────────────────────────────────
    if user.access_schedule and user.role and user.role.name != "admin":
        if not _within_access_schedule(user.access_schedule):
            await write_audit(
                db, action="login_blocked_schedule", user_id=user.id, username=user.username,
                ip_address=client_ip(request), severity="warning",
            )
            await db.commit()
            raise HTTPException(403, "Outside permitted access hours")

    await db.refresh(user, ["role"])
    token_data = svc.build_token_data(user)
    access = create_access_token(token_data)
    refresh = create_refresh_token(token_data)

    # Persist refresh token for revocation tracking
    await _store_refresh_token(db, user.id, refresh, request)

    await write_audit(
        db, action="login_success", user_id=user.id, username=user.username,
        ip_address=client_ip(request), resource_type="user", resource_id=user.id,
    )
    await db.commit()

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user=UserResponse(**svc.user_to_response(user)),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(auth_limiter.limit),
):
    """Exchange a valid refresh token for new access + refresh tokens."""
    payload = verify_token(body.refresh_token, expected_type="refresh")
    if not payload:
        raise HTTPException(401, "Invalid or expired refresh token")

    # Validate against revocation DB
    if not await _validate_refresh_token_in_db(db, body.refresh_token):
        raise HTTPException(401, "Refresh token has been revoked or does not exist")

    user = await svc.get_user_by_id(db, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or disabled")

    # ── Password policy enforcement on refresh ───────────────────────────
    policy_msg = await svc.check_password_policy_on_login(db, user)
    if policy_msg:
        raise HTTPException(403, policy_msg, headers={"X-Password-Change-Required": "true"})

    await db.refresh(user, ["role"])
    token_data = svc.build_token_data(user)
    new_access = create_access_token(token_data)
    new_refresh = create_refresh_token(token_data)

    # Rotate: revoke old token, store new one
    await _revoke_token_hash(db, body.refresh_token)
    await _store_refresh_token(db, user.id, new_refresh, request)
    await db.commit()

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        user=UserResponse(**svc.user_to_response(user)),
    )


# ------------------------------------------------------------------
# Logout — revoke the presented refresh token
# ------------------------------------------------------------------

@router.post("/logout", status_code=204)
async def logout(
    body: LogoutRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Revoke the current refresh token (logout from this device)."""
    await _revoke_token_hash(db, body.refresh_token)
    await write_audit(
        db, action="logout", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="user", resource_id=user["id"],
    )
    await db.commit()


# ------------------------------------------------------------------
# Authenticated endpoints
# ------------------------------------------------------------------

@router.get("/me", response_model=UserResponse)
async def get_profile(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    db_user = await svc.get_user_by_id(db, user["id"])
    if not db_user:
        raise HTTPException(404, "User not found")
    await db.refresh(db_user, ["role"])
    return UserResponse(**svc.user_to_response(db_user))


@router.put("/me", response_model=UserResponse)
async def update_profile(
    data: UserUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Users can update their own profile (except role)."""
    data.role_name = None  # Users can't change their own role
    data.is_active = None
    updated = await svc.update_user(db, user["id"], data)
    if not updated:
        raise HTTPException(404, "User not found")
    await db.refresh(updated, ["role"])
    return UserResponse(**svc.user_to_response(updated))


class PasswordChangeBody(BaseModel):
    current_password: str
    new_password: str


@router.post("/me/change-password", status_code=200)
async def change_own_password(
    body: PasswordChangeBody,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Self-service password change with current-password verification."""
    db_user = await svc.get_user_by_id(db, user["id"])
    if not db_user:
        raise HTTPException(404, "User not found")

    from app.core.security import verify_password
    if not verify_password(body.current_password, db_user.hashed_password):
        raise HTTPException(401, "Current password is incorrect")

    try:
        updated = await svc.update_user(
            db, user["id"],
            UserUpdate(password=body.new_password),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    await write_audit(
        db, action="password_change", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="user", resource_id=user["id"],
        description="User changed their own password",
    )
    await db.commit()
    return {"success": True, "message": "Password changed successfully"}


class PasswordVerifyBody(BaseModel):
    password: str


@router.post("/me/verify-password", status_code=200)
async def verify_own_password(
    body: PasswordVerifyBody,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-authenticate the current user by their password.

    Used as a confirmation gate for sensitive/irreversible actions
    (e.g. deleting a camera). Returns {"verified": true} on success,
    401 otherwise. Does not mutate any state.
    """
    db_user = await svc.get_user_by_id(db, user["id"])
    if not db_user:
        raise HTTPException(404, "User not found")

    from app.core.security import verify_password
    if not verify_password(body.password, db_user.hashed_password):
        raise HTTPException(401, "Password is incorrect")

    return {"verified": True}


# ------------------------------------------------------------------
# Admin-only
# ------------------------------------------------------------------

@router.get("/users", response_model=List[UserResponse])
async def list_users(
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).options(selectinload(User.role)).order_by(User.created_at)
    )
    users = result.scalars().all()
    return [UserResponse(**svc.user_to_response(u)) for u in users]


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user_admin(
    data: UserCreate,
    request: Request,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin creates a new user with specified role."""
    if await svc.get_user_by_username(db, data.username):
        raise HTTPException(400, "Username already taken")
    try:
        user = await svc.create_user(db, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await db.refresh(user, ["role"])

    await write_audit(
        db, action="user_create", user_id=admin["id"], username=admin["username"],
        ip_address=client_ip(request), resource_type="user", resource_id=user.id,
        description=f"Admin created user: {user.username}",
    )
    await db.commit()
    return UserResponse(**svc.user_to_response(user))


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user_admin(
    user_id: str,
    data: UserUpdate,
    request: Request,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    old_user = await svc.get_user_by_id(db, user_id)
    if not old_user:
        raise HTTPException(404, "User not found")
    updated = await svc.update_user(db, user_id, data)
    await db.refresh(updated, ["role"])

    await write_audit(
        db, action="user_update", user_id=admin["id"], username=admin["username"],
        ip_address=client_ip(request), resource_type="user", resource_id=user_id,
        description=f"Admin updated user: {updated.username}",
        details={"changes": data.model_dump(exclude_unset=True)},
    )
    await db.commit()
    return UserResponse(**svc.user_to_response(updated))


@router.delete("/users/{user_id}", status_code=204)
async def delete_user_admin(
    user_id: str,
    request: Request,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin["id"]:
        raise HTTPException(400, "Cannot delete your own account")
    # Revoke all active tokens before deleting user
    await db.execute(
        delete(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked.is_(False),
        )
    )
    if not await svc.delete_user(db, user_id):
        raise HTTPException(404, "User not found")
    await write_audit(
        db, action="user_delete", user_id=admin["id"], username=admin["username"],
        ip_address=client_ip(request), resource_type="user", resource_id=user_id,
        severity="warning",
    )
    await db.commit()


@router.get("/sessions")
async def list_my_sessions(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the calling user's currently active sessions (non-revoked,
    non-expired refresh tokens). Used by the profile page to show 'logged in
    from these devices' and offer one-click logout."""
    now = datetime.utcnow()
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user["id"],
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > now,
        ).order_by(RefreshToken.issued_at.desc())
    )
    return [
        {
            "id": rt.id,
            "issued_at": rt.issued_at,
            "expires_at": rt.expires_at,
            "last_seen_at": rt.last_seen_at,
            "ip_address": rt.ip_address,
            "user_agent": rt.user_agent,
        }
        for rt in result.scalars().all()
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_my_session(
    session_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a single session by id. Users may only revoke their own."""
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.id == session_id)
    )
    rt = result.scalar_one_or_none()
    if not rt:
        raise HTTPException(404)
    if rt.user_id != user["id"]:
        raise HTTPException(403, "Cannot revoke another user's session")
    rt.revoked = True
    rt.revoked_at = datetime.utcnow()
    await write_audit(
        db, action="session_revoke", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="session", resource_id=session_id,
    )
    await db.commit()


@router.post("/sessions/revoke-others", status_code=200)
async def revoke_other_sessions(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """'Log out of all other devices.' Revokes every active session for the
    calling user except the one tied to the current refresh-token cookie
    (best-effort identified by the most-recently used token)."""
    now = datetime.utcnow()
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user["id"],
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > now,
        ).order_by(RefreshToken.last_seen_at.desc().nullslast(),
                   RefreshToken.issued_at.desc())
    )
    tokens = result.scalars().all()
    # Keep the freshest (most-recently-seen) session — that's "this one".
    revoked = 0
    for rt in tokens[1:]:
        rt.revoked = True
        rt.revoked_at = now
        revoked += 1
    await write_audit(
        db, action="sessions_revoke_others", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="user", resource_id=user["id"],
        description=f"Revoked {revoked} other session(s)",
    )
    await db.commit()
    return {"revoked": revoked}


@router.get("/sessions/all")
async def list_all_sessions(
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin view: every active session across the whole system."""
    now = datetime.utcnow()
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > now,
        ).order_by(RefreshToken.last_seen_at.desc().nullslast())
    )
    return [
        {
            "id": rt.id, "user_id": rt.user_id,
            "issued_at": rt.issued_at, "expires_at": rt.expires_at,
            "last_seen_at": rt.last_seen_at,
            "ip_address": rt.ip_address, "user_agent": rt.user_agent,
        }
        for rt in result.scalars().all()
    ]


@router.post("/users/{user_id}/revoke-sessions", status_code=204)
async def revoke_user_sessions(
    user_id: str,
    request: Request,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Force-logout a user by revoking all their active refresh tokens (admin only)."""
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked.is_(False),
        )
    )
    tokens = result.scalars().all()
    now = datetime.utcnow()
    count = 0
    for rt in tokens:
        rt.revoked = True
        rt.revoked_at = now
        count += 1
    await write_audit(
        db, action="revoke_sessions", user_id=admin["id"], username=admin["username"],
        ip_address=client_ip(request), resource_type="user", resource_id=user_id,
        description=f"Revoked {count} active session(s)",
        severity="warning",
    )
    await db.commit()


# ------------------------------------------------------------------
# Roles
# ------------------------------------------------------------------

class RoleUpsert(BaseModel):
    name: str = Field(..., min_length=2, max_length=30)
    description: Optional[str] = None
    permissions: List[str] = []


@router.post("/roles", response_model=RoleResponse, status_code=201)
async def create_role(
    body: RoleUpsert,
    request: Request,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Custom role with arbitrary permission list (Phase 6.6)."""
    from app.auth.models import Role
    existing = (await db.execute(select(Role).where(Role.name == body.name))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Role with that name already exists")
    role = Role(name=body.name, description=body.description,
                permissions=body.permissions, is_system=False)
    db.add(role)
    await db.commit()
    await db.refresh(role)
    await write_audit(
        db, action="role_create", user_id=admin["id"], username=admin["username"],
        ip_address=client_ip(request), resource_type="role", resource_id=role.id,
        description=f"Created role '{role.name}'",
    )
    await db.commit()
    return RoleResponse(
        id=role.id, name=role.name, description=role.description,
        permissions=role.permissions or [], is_system=role.is_system,
    )


@router.put("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: str,
    body: RoleUpsert,
    request: Request,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.auth.models import Role
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if not role:
        raise HTTPException(404)
    if role.is_system:
        # Allow tweaking permissions on system roles but not their name
        role.permissions = body.permissions
        if body.description is not None:
            role.description = body.description
    else:
        role.name = body.name
        role.description = body.description
        role.permissions = body.permissions
    await db.commit()
    await db.refresh(role)
    await write_audit(
        db, action="role_update", user_id=admin["id"], username=admin["username"],
        ip_address=client_ip(request), resource_type="role", resource_id=role.id,
    )
    await db.commit()
    return RoleResponse(
        id=role.id, name=role.name, description=role.description,
        permissions=role.permissions or [], is_system=role.is_system,
    )


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(
    role_id: str,
    request: Request,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.auth.models import Role, User
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if not role:
        raise HTTPException(404)
    if role.is_system:
        raise HTTPException(400, "System roles cannot be deleted")
    in_use = (await db.execute(select(User).where(User.role_id == role_id).limit(1))).scalar_one_or_none()
    if in_use:
        raise HTTPException(409, "Role is assigned to users — reassign first")
    await db.delete(role)
    await write_audit(
        db, action="role_delete", user_id=admin["id"], username=admin["username"],
        ip_address=client_ip(request), resource_type="role", resource_id=role_id,
    )
    await db.commit()


@router.get("/permissions/available")
async def list_available_permissions(admin: dict = Depends(get_admin_user)):
    """All known permission tokens — used by the role builder UI."""
    from app.auth.models import PermissionAction
    return [p.value for p in PermissionAction]


# ─── Per-user camera ACL (Phase 6.3) ──────────────────────────────────────

@router.get("/users/{user_id}/cameras")
async def get_user_camera_access(
    user_id: str,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the camera IDs directly granted to *user_id* (excludes group grants)."""
    from sqlalchemy import select as _s
    from app.cameras.models import user_camera_access
    rows = await db.execute(_s(user_camera_access.c.camera_id).where(
        user_camera_access.c.user_id == user_id
    ))
    return {"camera_ids": [r[0] for r in rows.fetchall()]}


class CameraAccessBody(BaseModel):
    camera_ids: List[str]


@router.put("/users/{user_id}/cameras", status_code=200)
async def set_user_camera_access(
    user_id: str,
    body: CameraAccessBody,
    request: Request,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace the direct camera ACL for *user_id* with the supplied list."""
    from sqlalchemy import delete as _del
    from app.cameras.models import user_camera_access
    await db.execute(_del(user_camera_access).where(user_camera_access.c.user_id == user_id))
    for cid in body.camera_ids:
        await db.execute(user_camera_access.insert().values(user_id=user_id, camera_id=cid))
    await write_audit(
        db, action="user_camera_access_set",
        user_id=admin["id"], username=admin["username"],
        ip_address=client_ip(request), resource_type="user", resource_id=user_id,
        description=f"Direct camera ACL set to {len(body.camera_ids)} camera(s)",
    )
    await db.commit()
    return {"camera_ids": body.camera_ids}


@router.get("/roles", response_model=List[RoleResponse])
async def list_roles(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    roles = await svc.get_all_roles(db)
    out = []
    for r in roles:
        out.append(RoleResponse(
            id=r.id, name=r.name, description=r.description,
            permissions=r.permissions or [], is_system=r.is_system,
        ))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Two-factor authentication (TOTP) — Phase 5.3
# ─────────────────────────────────────────────────────────────────────────────

class TOTPEnableResponse(BaseModel):
    secret: str
    otpauth_uri: str


class TOTPVerifyBody(BaseModel):
    token: str


@router.post("/2fa/enable", response_model=TOTPEnableResponse)
async def enable_2fa(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Step 1: generate a TOTP secret and otpauth:// URI. The user scans
    the QR, then confirms with /2fa/verify before 2fa_enabled flips True."""
    from app.auth import totp_service
    from app.core.crypto import encrypt_value
    secret = totp_service.generate_secret()
    db_user = (await db.execute(select(User).where(User.id == user["id"]))).scalar_one()
    db_user.totp_secret = encrypt_value(secret)
    db_user.totp_enabled = False  # not enabled until verified
    await db.commit()
    return TOTPEnableResponse(
        secret=secret,
        otpauth_uri=totp_service.provisioning_uri(user["username"], secret),
    )


@router.post("/2fa/verify")
async def verify_2fa(
    body: TOTPVerifyBody,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Step 2: user enters the current 6-digit code; on match, 2FA is armed
    and a fresh batch of recovery codes is returned (operator must save them
    — they're not retrievable afterward)."""
    from app.auth import totp_service
    from app.core.crypto import decrypt_value
    db_user = (await db.execute(select(User).where(User.id == user["id"]))).scalar_one()
    if not db_user.totp_secret:
        raise HTTPException(400, "2FA not initialized — call /2fa/enable first")
    secret = decrypt_value(db_user.totp_secret)
    if not totp_service.verify(secret, body.token):
        raise HTTPException(400, "Invalid TOTP token")
    db_user.totp_enabled = True
    codes = totp_service.generate_recovery_codes()
    db_user.totp_recovery_codes = codes
    await write_audit(
        db, action="2fa_enabled", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="user", resource_id=user["id"],
    )
    await db.commit()
    return {"enabled": True, "recovery_codes": codes}


@router.post("/2fa/disable")
async def disable_2fa(
    body: TOTPVerifyBody,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disable 2FA on the calling user. Requires a current TOTP token to
    prevent a stolen session from removing the second factor."""
    from app.auth import totp_service
    from app.core.crypto import decrypt_value
    db_user = (await db.execute(select(User).where(User.id == user["id"]))).scalar_one()
    if db_user.totp_enabled and db_user.totp_secret:
        if not totp_service.verify(decrypt_value(db_user.totp_secret), body.token):
            # Allow a recovery code to disable too
            if body.token not in (db_user.totp_recovery_codes or []):
                raise HTTPException(400, "Invalid TOTP token")
    db_user.totp_enabled = False
    db_user.totp_secret = None
    db_user.totp_recovery_codes = None
    await write_audit(
        db, action="2fa_disabled", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="user", resource_id=user["id"],
        severity="warning",
    )
    await db.commit()
    return {"enabled": False}


# ─────────────────────────────────────────────────────────────────────────────
# Time-bound access schedule (Phase 6.4)
# ─────────────────────────────────────────────────────────────────────────────

class AccessScheduleBody(BaseModel):
    schedule: Optional[dict] = None   # {"monday": [{"start": "08:00", "end": "18:00"}], ...}


@router.put("/users/{user_id}/access-schedule")
async def set_access_schedule(
    user_id: str,
    body: AccessScheduleBody,
    request: Request,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or clear the per-user access-hours window. Admin role is exempt at
    enforcement time regardless of what's stored here."""
    db_user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not db_user:
        raise HTTPException(404)
    db_user.access_schedule = body.schedule
    await write_audit(
        db, action="access_schedule_set",
        user_id=admin["id"], username=admin["username"],
        ip_address=client_ip(request), resource_type="user", resource_id=user_id,
        description="Access schedule cleared" if not body.schedule else "Access schedule updated",
    )
    await db.commit()
    return {"user_id": user_id, "schedule": body.schedule}
