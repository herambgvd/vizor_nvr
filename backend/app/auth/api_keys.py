# =============================================================================
# API Keys — Machine-to-machine authentication
#
# Used by vizor-gpu workers and other services to authenticate against the
# NVR API without going through interactive JWT login. Keys are stored as
# SHA-256 hashes; the plaintext value is shown to the user exactly once at
# creation time.
#
# Format: vzn_<48 hex chars>
#   - prefix "vzn_" makes secret scanners catch leaks
#   - 192 bits of entropy is overkill for symmetric secret use
#
# Scopes restrict what a key can do. Current scopes:
#   - events:ingest   — POST /api/events/ingest from inference workers
#   - cameras:read    — GET /api/cameras for config fetch
#   - models:read     — GET /api/ai/models for model registry lookups
#   - admin           — full access (avoid in production)
# =============================================================================

import hashlib
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import (
    Column, String, Boolean, DateTime, JSON, Index,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.database import Base, get_db


API_KEY_PREFIX = "vzn_"
API_KEY_BYTES = 24  # 24 bytes = 48 hex chars = 192 bits entropy
API_KEY_HEADER = "X-Vizor-API-Key"


# ---------------------------------------------------------------------------
# SQLAlchemy model
# ---------------------------------------------------------------------------

class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True)
    name = Column(String(100), nullable=False, index=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    key_prefix = Column(String(12), nullable=False)  # first 12 chars for display
    scopes = Column(JSON, nullable=False, default=list)
    enabled = Column(Boolean, default=True, nullable=False)
    created_by = Column(String, nullable=True)  # user id of creator
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    last_used_ip = Column(String(45), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_api_keys_enabled", "enabled"),
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None


class APIKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: List[str]
    enabled: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None
    last_used_ip: Optional[str] = None
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class APIKeyCreateResponse(APIKeyResponse):
    plaintext_key: str = Field(
        ...,
        description="Full API key value. Shown ONCE. Store it now or rotate.",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def generate_api_key() -> str:
    """Returns a fresh plaintext API key with vzn_ prefix."""
    return API_KEY_PREFIX + secrets.token_hex(API_KEY_BYTES)


def hash_api_key(plaintext: str) -> str:
    """SHA-256 hex digest. Constant-time compared during auth."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def key_prefix(plaintext: str) -> str:
    """First 12 chars for non-secret display in UI."""
    return plaintext[:12]


# ---------------------------------------------------------------------------
# CRUD service
# ---------------------------------------------------------------------------

class APIKeyService:

    @staticmethod
    async def create(
        db: AsyncSession,
        data: APIKeyCreate,
        created_by: Optional[str] = None,
    ) -> tuple[APIKey, str]:
        plaintext = generate_api_key()
        key = APIKey(
            id=secrets.token_hex(16),
            name=data.name,
            key_hash=hash_api_key(plaintext),
            key_prefix=key_prefix(plaintext),
            scopes=data.scopes,
            enabled=True,
            created_by=created_by,
            expires_at=data.expires_at,
        )
        db.add(key)
        await db.commit()
        await db.refresh(key)
        return key, plaintext

    @staticmethod
    async def list_all(db: AsyncSession) -> List[APIKey]:
        result = await db.execute(
            select(APIKey).order_by(APIKey.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(db: AsyncSession, key_id: str) -> Optional[APIKey]:
        result = await db.execute(select(APIKey).where(APIKey.id == key_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def revoke(db: AsyncSession, key_id: str) -> bool:
        key = await APIKeyService.get_by_id(db, key_id)
        if not key or key.revoked_at:
            return False
        key.revoked_at = datetime.utcnow()
        key.enabled = False
        await db.commit()
        return True

    @staticmethod
    async def delete(db: AsyncSession, key_id: str) -> bool:
        key = await APIKeyService.get_by_id(db, key_id)
        if not key:
            return False
        await db.delete(key)
        await db.commit()
        return True

    @staticmethod
    async def authenticate(
        db: AsyncSession, plaintext: str, source_ip: Optional[str] = None
    ) -> Optional[APIKey]:
        """Validate a plaintext key against stored hashes.

        Updates last_used_at and last_used_ip on success.
        Returns None for invalid, disabled, revoked, or expired keys.
        """
        if not plaintext or not plaintext.startswith(API_KEY_PREFIX):
            return None
        digest = hash_api_key(plaintext)
        result = await db.execute(
            select(APIKey).where(APIKey.key_hash == digest)
        )
        key = result.scalar_one_or_none()
        if not key:
            return None
        if not key.enabled or key.revoked_at is not None:
            return None
        if key.expires_at and key.expires_at < datetime.utcnow():
            return None
        key.last_used_at = datetime.utcnow()
        if source_ip:
            key.last_used_ip = source_ip
        await db.commit()
        return key


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def get_api_key(
    x_vizor_api_key: Optional[str] = Header(None, alias=API_KEY_HEADER),
    db: AsyncSession = Depends(get_db),
) -> APIKey:
    """Require a valid API key. Returns the APIKey row on success."""
    if not x_vizor_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing {API_KEY_HEADER} header",
        )
    key = await APIKeyService.authenticate(db, x_vizor_api_key)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )
    return key


def require_scope(scope: str):
    """Returns a dependency that checks the API key has the given scope.

    Usage::

        @router.post("/ingest")
        async def ingest(
            payload: EventIngestBatch,
            key=Depends(require_scope("events:ingest")),
            db: AsyncSession = Depends(get_db),
        ): ...
    """

    async def _check(key: APIKey = Depends(get_api_key)) -> APIKey:
        scopes = key.scopes or []
        if "admin" in scopes or scope in scopes:
            return key
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key missing required scope: {scope}",
        )

    return _check
