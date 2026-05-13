# =============================================================================
# Auth Models — User, Role + Pydantic schemas
# =============================================================================

from sqlalchemy import (
    Column, String, Boolean, DateTime, Text, ForeignKey, JSON, Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum
import uuid

from app.database import Base


# =============================================================================
# Enums
# =============================================================================

class RoleName(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class PermissionAction(str, Enum):
    """Granular permissions assignable to roles."""
    VIEW_LIVE = "view_live"
    VIEW_PLAYBACK = "view_playback"
    CONTROL_RECORDING = "control_recording"
    CONTROL_PTZ = "control_ptz"
    MANAGE_CAMERA = "manage_camera"
    EXPORT_CLIPS = "export_clips"
    DELETE_RECORDINGS = "delete_recordings"
    MANAGE_USERS = "manage_users"
    MANAGE_SETTINGS = "manage_settings"
    MANAGE_STORAGE = "manage_storage"
    VIEW_AUDIT_LOG = "view_audit_log"
    # Fine-grained permissions added in Phase 6.6 — referenced by routers
    ACKNOWLEDGE_EVENTS = "acknowledge_events"
    MANAGE_ROLES = "manage_roles"
    MANAGE_GROUPS = "manage_groups"


# Default permission sets per role
ROLE_DEFAULTS = {
    RoleName.ADMIN: [p.value for p in PermissionAction],
    RoleName.OPERATOR: [
        PermissionAction.VIEW_LIVE.value,
        PermissionAction.VIEW_PLAYBACK.value,
        PermissionAction.CONTROL_RECORDING.value,
        PermissionAction.CONTROL_PTZ.value,
        PermissionAction.EXPORT_CLIPS.value,
    ],
    RoleName.VIEWER: [
        PermissionAction.VIEW_LIVE.value,
        PermissionAction.VIEW_PLAYBACK.value,
    ],
}


# =============================================================================
# SQLAlchemy Models
# =============================================================================

class Role(Base):
    __tablename__ = "roles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(30), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    permissions = Column(JSON, nullable=False)   # list of PermissionAction values
    is_system = Column(Boolean, default=False)   # system roles can't be deleted
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    users = relationship("User", back_populates="role")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    role_id = Column(String, ForeignKey("roles.id"), nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # ── Phase 5 security additions ──────────────────────────────────────
    totp_secret = Column(String(255), nullable=True)  # AES-encrypted Base32 seed
    totp_enabled = Column(Boolean, default=False, nullable=False)
    totp_recovery_codes = Column(JSON, nullable=True)  # list of unused hex codes
    password_changed_at = Column(DateTime, nullable=True)
    force_password_reset = Column(Boolean, default=False, nullable=False)
    # Time-bound access — JSON: {"monday": [{"start": "08:00", "end": "18:00"}], ...}
    access_schedule = Column(JSON, nullable=True)

    role = relationship("Role", back_populates="users")


class RefreshToken(Base):
    """
    Persisted refresh tokens for revocation support.
    On logout or user deletion, mark revoked=True so the token is rejected
    even before its expiry date.
    """
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256 hex of token
    issued_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    user_agent = Column(String(500), nullable=True)
    ip_address = Column(String(45), nullable=True)
    last_seen_at = Column(DateTime, nullable=True)   # bumped on each /refresh use


# =============================================================================
# Pydantic Schemas
# =============================================================================

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)
    role_name: Optional[str] = Field(None, description="admin/operator/viewer")


class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6)
    role_name: Optional[str] = None
    is_active: Optional[bool] = None


class UserLogin(BaseModel):
    username: str
    password: str
    totp_token: Optional[str] = None  # required when account has 2FA enabled


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    is_active: bool
    is_admin: bool = False
    role_name: Optional[str] = None
    permissions: List[str] = []
    last_login_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class RoleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    permissions: List[str]
    is_system: bool

    class Config:
        from_attributes = True
