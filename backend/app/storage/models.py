# =============================================================================
# Storage Models — pools, tier rules
# =============================================================================

from sqlalchemy import (
    Column, String, Boolean, DateTime, Integer, BigInteger, Text,
)
from sqlalchemy.sql import func
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid

from app.database import Base


class StoragePool(Base):
    __tablename__ = "storage_pools"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False)
    path = Column(String(500), unique=True, nullable=False)
    pool_type = Column(String(20), default="local")  # local / nfs / smb
    max_size_bytes = Column(BigInteger, nullable=True)  # null = unlimited
    priority = Column(Integer, default=0)  # higher = preferred
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    mount_options = Column(Text, nullable=True)  # NFS/SMB mount opts
    raid_level = Column(String(10), nullable=True)  # raid0 / raid1 / raid5 / raid6 / raid10

    # ── NAS-specific fields ────────────────────────────────────────────
    nas_server = Column(String(200), nullable=True)      # IP or hostname
    nas_share = Column(String(200), nullable=True)       # share/export name
    nas_protocol = Column(String(10), nullable=True)     # nfs / smb
    nas_username = Column(String(200), nullable=True)    # SMB username
    nas_password = Column(String(500), nullable=True)    # SMB password (encrypted)
    nas_domain = Column(String(100), nullable=True)      # SMB domain / workgroup
    nas_auto_mount = Column(Boolean, default=True, nullable=False, server_default="1")
    nas_mount_state = Column(String(20), nullable=True)  # unmounted / mounting / mounted / error
    nas_last_mount_error = Column(Text, nullable=True)
    nas_last_mount_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class StorageTierRule(Base):
    __tablename__ = "storage_tier_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    source_pool_id = Column(String, nullable=False)  # FK ref but flexible
    target_pool_id = Column(String, nullable=False)
    age_threshold_hours = Column(Integer, nullable=False)  # move after X hours
    is_active = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class BackupSchedule(Base):
    __tablename__ = "backup_schedules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    source_pool_id = Column(String, nullable=False)
    target_pool_id = Column(String, nullable=False)
    # Cron-like schedule: "0 2 * * *" = daily at 02:00
    schedule = Column(String(100), nullable=False, default="0 2 * * *")
    is_active = Column(Boolean, default=True, nullable=False)
    # Backup recordings older than this many days
    age_days = Column(Integer, default=7, nullable=False)
    # Last run tracking
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(20), nullable=True)  # success / failed / running
    last_run_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# =============================================================================
# Pydantic
# =============================================================================

class StoragePoolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    path: str = Field(..., min_length=1)
    pool_type: str = "local"
    max_size_bytes: Optional[int] = None
    priority: int = 0
    is_default: bool = False
    mount_options: Optional[str] = None
    # NAS
    nas_server: Optional[str] = None
    nas_share: Optional[str] = None
    nas_protocol: Optional[str] = None  # nfs / smb
    nas_username: Optional[str] = None
    nas_password: Optional[str] = None
    nas_domain: Optional[str] = None
    nas_auto_mount: bool = True


class StoragePoolUpdate(BaseModel):
    name: Optional[str] = None
    max_size_bytes: Optional[int] = None
    priority: Optional[int] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    mount_options: Optional[str] = None
    raid_level: Optional[str] = None
    nas_server: Optional[str] = None
    nas_share: Optional[str] = None
    nas_protocol: Optional[str] = None
    nas_username: Optional[str] = None
    nas_password: Optional[str] = None
    nas_domain: Optional[str] = None
    nas_auto_mount: Optional[bool] = None


class StoragePoolResponse(BaseModel):
    id: str
    name: str
    path: str
    pool_type: str
    max_size_bytes: Optional[int]
    priority: int
    is_default: bool
    is_active: bool
    mount_options: Optional[str]
    raid_level: Optional[str] = None
    # NAS
    nas_server: Optional[str] = None
    nas_share: Optional[str] = None
    nas_protocol: Optional[str] = None
    nas_username: Optional[str] = None
    nas_domain: Optional[str] = None
    nas_auto_mount: bool = True
    nas_mount_state: Optional[str] = None
    nas_last_mount_error: Optional[str] = None
    nas_last_mount_at: Optional[datetime] = None
    # computed
    used_bytes: int = 0
    free_bytes: int = 0
    total_bytes: int = 0          # real filesystem capacity of the mount
    online: bool = True           # False = path missing / stale or offline mount
    recording_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class TierRuleCreate(BaseModel):
    name: str
    source_pool_id: str
    target_pool_id: str
    age_threshold_hours: int = Field(..., gt=0)


class TierRuleUpdate(BaseModel):
    name: Optional[str] = None
    age_threshold_hours: Optional[int] = None
    is_active: Optional[bool] = None


class TierRuleResponse(BaseModel):
    id: str
    name: str
    source_pool_id: str
    target_pool_id: str
    age_threshold_hours: int
    is_active: bool
    last_run_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class StorageSummary(BaseModel):
    total_pools: int
    total_capacity_bytes: int
    total_used_bytes: int
    total_free_bytes: int
    pools: List[StoragePoolResponse]


# =============================================================================
# Cloud storage config (stored in DB)
# =============================================================================

class CloudStorageConfig(Base):
    __tablename__ = "cloud_storage_configs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    provider = Column(String(20), default="s3")  # s3 / gcs / azure
    endpoint = Column(String(500), nullable=True)  # custom endpoint for MinIO etc.
    bucket = Column(String(200), nullable=False)
    region = Column(String(50), default="us-east-1")
    access_key = Column(String(200), nullable=True)
    secret_key = Column(String(500), nullable=True)
    prefix = Column(String(200), default="recordings/")
    is_active = Column(Boolean, default=True)
    sync_enabled = Column(Boolean, default=False)  # auto-sync new recordings
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class CloudConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider: str = "s3"
    endpoint: Optional[str] = None
    bucket: str = Field(..., min_length=1)
    region: str = "us-east-1"
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    prefix: str = "recordings/"
    sync_enabled: bool = False


class CloudConfigUpdate(BaseModel):
    name: Optional[str] = None
    endpoint: Optional[str] = None
    bucket: Optional[str] = None
    region: Optional[str] = None
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    prefix: Optional[str] = None
    is_active: Optional[bool] = None
    sync_enabled: Optional[bool] = None


class CloudConfigResponse(BaseModel):
    id: str
    name: str
    provider: str
    endpoint: Optional[str]
    bucket: str
    region: str
    prefix: str
    is_active: bool
    sync_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


class CloudUploadJob(BaseModel):
    recording_id: str
    cloud_config_id: str


# ── Backup Schedule schemas ──────────────────────────────────────────

class BackupScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    source_pool_id: str
    target_pool_id: str
    schedule: str = "0 2 * * *"
    is_active: bool = True
    age_days: int = Field(default=7, ge=1, le=3650)


class BackupScheduleUpdate(BaseModel):
    name: Optional[str] = None
    source_pool_id: Optional[str] = None
    target_pool_id: Optional[str] = None
    schedule: Optional[str] = None
    is_active: Optional[bool] = None
    age_days: Optional[int] = Field(None, ge=1, le=3650)


class BackupScheduleResponse(BaseModel):
    id: str
    name: str
    source_pool_id: str
    target_pool_id: str
    schedule: str
    is_active: bool
    age_days: int
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    last_run_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
