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


class StoragePoolUpdate(BaseModel):
    name: Optional[str] = None
    max_size_bytes: Optional[int] = None
    priority: Optional[int] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    mount_options: Optional[str] = None


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
    # computed
    used_bytes: int = 0
    free_bytes: int = 0
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
