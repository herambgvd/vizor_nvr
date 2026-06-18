# =============================================================================
# Auth Service — user CRUD, authentication, role seeding
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import (
    User, Role, RoleName, ROLE_DEFAULTS,
    UserCreate, UserUpdate,
)
from app.core.security import hash_password, verify_password

logger = logging.getLogger(__name__)


class AuthService:
    """Stateless service — all methods receive a db session."""

    # ------------------------------------------------------------------
    # Role management
    # ------------------------------------------------------------------

    @staticmethod
    async def seed_roles(db: AsyncSession) -> None:
        """Create the three default roles if missing, and reconcile system roles
        with any newly-added default permissions (so upgrades that introduce a
        permission grant it to existing system roles). Called at startup."""
        for role_name in RoleName:
            existing = (await db.execute(
                select(Role).where(Role.name == role_name.value)
            )).scalar_one_or_none()
            defaults = ROLE_DEFAULTS[role_name]
            if existing is None:
                db.add(Role(
                    name=role_name.value,
                    description=f"System {role_name.value} role",
                    permissions=defaults,
                    is_system=True,
                ))
                logger.info(f"Seeded role: {role_name.value}")
                continue
            # Union-in any default perms the system role is missing (e.g. new
            # AI/biometric perms added in an upgrade). Custom additions are kept.
            if existing.is_system:
                current = list(existing.permissions or [])
                missing = [p for p in defaults if p not in current]
                if missing:
                    existing.permissions = current + missing
                    logger.info(f"Granted new perms to '{role_name.value}': {missing}")
        await db.commit()

    @staticmethod
    async def get_role_by_name(db: AsyncSession, name: str) -> Optional[Role]:
        result = await db.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_roles(db: AsyncSession) -> List[Role]:
        result = await db.execute(select(Role).order_by(Role.name))
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def create_user(db: AsyncSession, data: UserCreate) -> User:
        # Resolve role
        role_name = data.role_name or RoleName.VIEWER.value

        # First user ever → auto-admin
        count = await db.execute(select(func.count(User.id)))
        if count.scalar() == 0:
            role_name = RoleName.ADMIN.value

        role = await AuthService.get_role_by_name(db, role_name)
        if not role:
            raise ValueError(f"Role '{role_name}' not found — run seed_roles first")

        # Enforce password policy (Phase 5.6)
        from app.auth.password_policy import validate
        errs = await validate(db, data.password)
        if errs:
            raise ValueError("Password does not meet policy: " + "; ".join(errs))

        user = User(
            username=data.username,
            email=data.email,
            hashed_password=hash_password(data.password),
            role_id=role.id,
            is_active=True,
            password_changed_at=datetime.utcnow(),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def authenticate(db: AsyncSession, username: str, password: str) -> Optional[User]:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, user.hashed_password):
            return None
        if not user.is_active:
            return None
        # Update last login
        user.last_login_at = datetime.utcnow()
        await db.commit()
        return user

    @staticmethod
    async def check_password_policy_on_login(db: AsyncSession, user: User) -> Optional[str]:
        """Return an error message if the user must change their password, else None."""
        from app.auth.password_policy import expired
        if user.force_password_reset:
            return "Password change required — an administrator has forced a password reset"
        if await expired(db, user.password_changed_at):
            return "Password expired — please change your password"
        return None

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[User]:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_users(db: AsyncSession) -> List[User]:
        result = await db.execute(
            select(User).order_by(User.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def update_user(db: AsyncSession, user_id: str, data: UserUpdate) -> Optional[User]:
        user = await AuthService.get_user_by_id(db, user_id)
        if not user:
            return None
        if data.username is not None:
            user.username = data.username
        if data.email is not None:
            user.email = data.email
        if data.password is not None:
            from app.auth.password_policy import validate, check_history, record_history
            errs = await validate(db, data.password)
            if errs:
                raise ValueError("Password does not meet policy: " + "; ".join(errs))
            new_hash = hash_password(data.password)
            if not await check_history(db, user.id, new_hash):
                raise ValueError("Password matches one of your recent passwords")
            # Record the OLD hash before replacing it.
            await record_history(db, user.id, user.hashed_password)
            user.hashed_password = new_hash
            user.password_changed_at = datetime.utcnow()
            user.force_password_reset = False
        if data.is_active is not None:
            user.is_active = data.is_active
        if data.role_name is not None:
            role = await AuthService.get_role_by_name(db, data.role_name)
            if role:
                user.role_id = role.id
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def delete_user(db: AsyncSession, user_id: str) -> bool:
        user = await AuthService.get_user_by_id(db, user_id)
        if not user:
            return False
        await db.delete(user)
        await db.commit()
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def user_to_response(user: User) -> dict:
        """Convert User ORM to a dict matching UserResponse."""
        role_name = None
        permissions = []
        is_admin = False
        if user.role:
            role_name = user.role.name
            is_admin = role_name == "admin"
            permissions = user.role.permissions if isinstance(user.role.permissions, list) else []
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
            "is_admin": is_admin,
            "role_name": role_name,
            "permissions": permissions,
            "last_login_at": user.last_login_at,
            "created_at": user.created_at,
            "password_changed_at": user.password_changed_at,
            "force_password_reset": user.force_password_reset,
        }

    @staticmethod
    def build_token_data(user: User) -> dict:
        """Build JWT payload dict for a user."""
        role_name = user.role.name if user.role else "viewer"
        return {
            "sub": user.id,
            "username": user.username,
            "email": user.email,
            "role": role_name,
            "role_id": user.role_id,
        }
