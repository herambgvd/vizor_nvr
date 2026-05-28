# =============================================================================
# Camera Models — multi-stream, groups, ONVIF, PTZ
# =============================================================================

from sqlalchemy import (
    Column, String, Boolean, DateTime, Integer, Float, Text, JSON,
    ForeignKey, Table, BigInteger,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from datetime import datetime
from enum import Enum
import uuid

from app.database import Base


# =============================================================================
# Enums
# =============================================================================

class CameraStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    CONNECTING = "connecting"
    ERROR = "error"


class RecordingMode(str, Enum):
    CONTINUOUS = "continuous"
    SCHEDULE = "schedule"
    MOTION = "motion"
    MANUAL = "manual"


# =============================================================================
# Association tables
# =============================================================================

camera_group_members = Table(
    "camera_group_members",
    Base.metadata,
    Column("camera_id", String, ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", String, ForeignKey("camera_groups.id", ondelete="CASCADE"), primary_key=True),
)

user_camera_groups = Table(
    "user_camera_groups",
    Base.metadata,
    Column("user_id", String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", String, ForeignKey("camera_groups.id", ondelete="CASCADE"), primary_key=True),
)

# Direct per-user → per-camera ACL (Phase 6.3). Effective access for a user
# is the UNION of direct grants here and group grants via user_camera_groups.
user_camera_access = Table(
    "user_camera_access",
    Base.metadata,
    Column("user_id", String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("camera_id", String, ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True),
)


# =============================================================================
# ORM Models
# =============================================================================

class CameraGroup(Base):
    __tablename__ = "camera_groups"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(7), nullable=True)  # hex e.g. "#FF5733"
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    cameras = relationship("Camera", secondary=camera_group_members, back_populates="groups")


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)

    # ── Multi-stream URLs ───────────────────────────────────────────────
    main_stream_url = Column(String(500), nullable=False)     # High-res for recording
    sub_stream_url = Column(String(500), nullable=True)       # Low-res for live preview
    detect_stream_url = Column(String(500), nullable=True)    # For AI (defaults to sub)

    # ── ONVIF / PTZ ────────────────────────────────────────────────────
    onvif_host = Column(String(200), nullable=True)
    onvif_port = Column(Integer, default=80)
    # Stored encrypted (Fernet token) — see app.core.crypto. Widened to 500
    # because Fernet ciphertext is ~80 chars per ~30 chars of plaintext plus
    # the 'enc:' prefix.
    onvif_username = Column(String(500), nullable=True)
    onvif_password = Column(String(500), nullable=True)
    ptz_capable = Column(Boolean, default=False)
    ptz_presets = Column(JSON, nullable=True)   # [{"token": "1", "name": "Gate"}]
    # Which ONVIF media profile this camera represents.  Populated when the
    # camera is one channel of a multi-channel NVR/DVR.  Helpers that call
    # GetProfiles() will use this token directly when set, skipping the
    # GetProfiles() round-trip.  NULL → fall back to profile[0] (legacy
    # single-camera behaviour).
    onvif_profile_token = Column(String(256), nullable=True)

    # ── Status ─────────────────────────────────────────────────────────
    status = Column(String(20), default=CameraStatus.OFFLINE.value)
    is_recording = Column(Boolean, default=False)
    is_enabled = Column(Boolean, default=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=5)
    last_retry_at = Column(DateTime, nullable=True)
    last_online_at = Column(DateTime, nullable=True)

    # ── Operator-controlled display order (drag-to-reorder on UI) ──────
    display_order = Column(Integer, default=0, nullable=False, server_default="0")

    # ── Stream info (auto-detected) ────────────────────────────────────
    resolution = Column(String(20), nullable=True)
    fps = Column(Integer, nullable=True)
    bitrate = Column(String(20), nullable=True)
    sub_resolution = Column(String(20), nullable=True)
    sub_fps = Column(Integer, nullable=True)
    codec = Column(String(20), nullable=True)   # h264 / h265

    # ── Recording settings ─────────────────────────────────────────────
    recording_fps = Column(Integer, nullable=True)
    recording_mode = Column(String(20), default=RecordingMode.CONTINUOUS.value, nullable=False, server_default="continuous")
    recording_schedule = Column(JSON, nullable=True)

    # ── ONVIF Events ───────────────────────────────────────────────────
    onvif_events_enabled = Column(Boolean, default=False)
    onvif_event_topics = Column(JSON, nullable=True)    # list of subscribed ONVIF topics

    # ── PTZ Tour ───────────────────────────────────────────────────────
    # { "presets": [{"token": "1", "dwell_seconds": 10}, ...], "loop": true }
    ptz_tour_config = Column(JSON, nullable=True)
    ptz_tour_enabled = Column(Boolean, default=False, nullable=False, server_default="0")

    # ── ONVIF I/O ──────────────────────────────────────────────────────
    relay_outputs = Column(JSON, nullable=True)         # cached relay output tokens
    digital_inputs = Column(JSON, nullable=True)        # cached digital input tokens

    # ── Motion / Privacy ───────────────────────────────────────────────
    motion_config = Column(JSON, nullable=True)
    privacy_masks = Column(JSON, nullable=True)

    # ── Storage ────────────────────────────────────────────────────────
    storage_pool_id = Column(String, ForeignKey("storage_pools.id"), nullable=True)

    # ── Bandwidth ──────────────────────────────────────────────────────
    bandwidth_limit_kbps = Column(Integer, default=0)  # 0 = unlimited
    bandwidth_alert_threshold_pct = Column(Integer, default=80, nullable=False, server_default="80")

    # ── Scheduled snapshots ────────────────────────────────────────────
    # { "enabled": bool, "interval_seconds": int, "retention_days": int|null }
    snapshot_config = Column(JSON, nullable=True)

    # ── Retention override ─────────────────────────────────────────────
    retention_days = Column(Integer, nullable=True)   # NULL = use global

    # ── Pre/Post Event Buffer ──────────────────────────────────────────
    pre_buffer_seconds = Column(Integer, default=10, nullable=True)
    post_buffer_seconds = Column(Integer, default=30, nullable=True)

    # ── Credential health probe ────────────────────────────────────────
    # Values: None (not yet probed) | "ok" | "unauthorized" | "unreachable"
    credentials_status = Column(String(20), nullable=True)
    credentials_checked_at = Column(DateTime, nullable=True)

    # ── Two-Way Audio Backchannel ──────────────────────────────────────
    # NULL = untested, True = supported, False = not supported.
    # Cached on first Talk press; reset by POST /audio/backchannel/recheck.
    backchannel_capable = Column(Boolean, nullable=True)

    # ── Metadata ───────────────────────────────────────────────────────
    location = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    thumbnail_path = Column(String(500), nullable=True)

    # ── Timestamps ─────────────────────────────────────────────────────
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # ── Relationships ──────────────────────────────────────────────────
    groups = relationship("CameraGroup", secondary=camera_group_members, back_populates="cameras")


# =============================================================================
# Pydantic Schemas
# =============================================================================

class CameraCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    main_stream_url: str = Field(..., min_length=1)
    sub_stream_url: Optional[str] = None
    detect_stream_url: Optional[str] = None
    onvif_host: Optional[str] = None
    # Optional. Frontend may send null when no ONVIF host configured.
    # SQLAlchemy column default kicks in at INSERT time.
    onvif_port: Optional[int] = 80
    onvif_username: Optional[str] = None
    onvif_password: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    is_enabled: bool = True
    recording_fps: Optional[int] = Field(None, ge=1, le=60)
    recording_mode: str = RecordingMode.CONTINUOUS.value
    recording_schedule: Optional[Dict[str, Any]] = None
    motion_config: Optional[Dict[str, Any]] = None
    privacy_masks: Optional[List[Dict[str, Any]]] = None
    storage_pool_id: Optional[str] = None
    bandwidth_limit_kbps: int = 0
    retention_days: Optional[int] = None
    pre_buffer_seconds: int = 10
    post_buffer_seconds: int = 30
    group_ids: List[str] = []
    onvif_events_enabled: bool = False
    onvif_event_topics: Optional[List[str]] = None
    onvif_profile_token: Optional[str] = None
    ptz_tour_config: Optional[Dict[str, Any]] = None
    ptz_tour_enabled: bool = False


class CameraUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    main_stream_url: Optional[str] = None
    sub_stream_url: Optional[str] = None
    detect_stream_url: Optional[str] = None
    onvif_host: Optional[str] = None
    onvif_port: Optional[int] = None
    onvif_username: Optional[str] = None
    onvif_password: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    is_enabled: Optional[bool] = None
    recording_fps: Optional[int] = Field(None, ge=1, le=60)
    recording_mode: Optional[str] = None
    recording_schedule: Optional[Dict[str, Any]] = None
    motion_config: Optional[Dict[str, Any]] = None
    privacy_masks: Optional[List[Dict[str, Any]]] = None
    storage_pool_id: Optional[str] = None
    bandwidth_limit_kbps: Optional[int] = None
    retention_days: Optional[int] = None
    pre_buffer_seconds: Optional[int] = None
    post_buffer_seconds: Optional[int] = None
    group_ids: Optional[List[str]] = None
    onvif_events_enabled: Optional[bool] = None
    onvif_event_topics: Optional[List[str]] = None
    onvif_profile_token: Optional[str] = None
    ptz_tour_config: Optional[Dict[str, Any]] = None
    ptz_tour_enabled: Optional[bool] = None


class CameraResponse(BaseModel):
    id: str
    name: str
    main_stream_url: str
    sub_stream_url: Optional[str]
    detect_stream_url: Optional[str]
    onvif_host: Optional[str]
    onvif_port: Optional[int] = None
    ptz_capable: bool
    ptz_presets: Optional[List[Dict[str, Any]]]
    status: str
    is_recording: bool
    is_enabled: bool
    retry_count: int
    max_retries: int
    last_retry_at: Optional[datetime]
    last_online_at: Optional[datetime]
    display_order: int = 0
    resolution: Optional[str]
    fps: Optional[int]
    bitrate: Optional[str]
    sub_resolution: Optional[str]
    sub_fps: Optional[int]
    codec: Optional[str]
    recording_fps: Optional[int]
    recording_mode: str = RecordingMode.CONTINUOUS.value
    recording_schedule: Optional[Dict[str, Any]]
    motion_config: Optional[Dict[str, Any]]
    privacy_masks: Optional[List[Dict[str, Any]]]
    storage_pool_id: Optional[str]
    retention_days: Optional[int] = None
    bandwidth_limit_kbps: int
    pre_buffer_seconds: int
    post_buffer_seconds: int
    location: Optional[str]
    description: Optional[str]
    thumbnail_path: Optional[str]
    group_ids: List[str] = []
    onvif_events_enabled: bool = False
    onvif_event_topics: Optional[List[str]] = None
    relay_outputs: Optional[List[Dict[str, Any]]] = None
    digital_inputs: Optional[List[Dict[str, Any]]] = None
    onvif_profile_token: Optional[str] = None
    ptz_tour_config: Optional[Dict[str, Any]] = None
    ptz_tour_enabled: bool = False
    credentials_status: Optional[str] = None
    credentials_checked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CameraGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    camera_ids: List[str] = []


class CameraGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    color: Optional[str] = None
    camera_ids: Optional[List[str]] = None


class CameraGroupResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    color: Optional[str]
    camera_ids: List[str] = []
    created_at: datetime

    class Config:
        from_attributes = True


class StreamUrlsResponse(BaseModel):
    camera_id: str
    live_stream_id: str    # The stream ID to use for live viewing (may be camera_id_sub)
    webrtc_url: str        # go2rtc WebRTC (sub stream for live)
    mse_url: str           # fallback MSE
    snapshot_url: str


class PTZMoveRequest(BaseModel):
    pan: float = Field(0.0, ge=-1.0, le=1.0)
    tilt: float = Field(0.0, ge=-1.0, le=1.0)
    zoom: float = Field(0.0, ge=-1.0, le=1.0)
    speed: float = Field(0.5, gt=0.0, le=1.0)


class PTZPreset(BaseModel):
    token: str
    name: str

class ONVIFDiscoveryResult(BaseModel):
    ip: str
    port: int
    name: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    firmware: Optional[str] = None
    serial_number: Optional[str] = None
    hardware_id: Optional[str] = None
    mac: Optional[str] = None
    has_ptz: Optional[bool] = None
    has_imaging: Optional[bool] = None
    has_analytics: Optional[bool] = None
    has_events: Optional[bool] = None
    main_stream_url: Optional[str] = None
    sub_stream_url: Optional[str] = None
    ptz_capable: bool = False
    # True when the host responded to ONVIF SOAP but rejected the default
    # credentials. UI shows "Unverified — enter password" prompt.
    auth_required: bool = False


# =============================================================================
# Camera Snapshot ORM + Schema
# =============================================================================

class CameraSnapshot(Base):
    __tablename__ = "camera_snapshots"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id = Column(String, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True)
    # trigger: periodic | event | manual
    trigger = Column(String(20), nullable=False, default="periodic")
    event_id = Column(String, nullable=True)     # FK to events.id if triggered by event
    captured_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)


class CameraSnapshotResponse(BaseModel):
    id: str
    camera_id: str
    file_path: str
    file_size: Optional[int]
    trigger: str
    event_id: Optional[str]
    captured_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Camera Health Snapshot ORM + Schema
# =============================================================================

class CameraHealthSnapshot(Base):
    __tablename__ = "camera_health_snapshots"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id = Column(String, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True)
    packet_loss_percent = Column(Float, nullable=True)
    bitrate_kbps = Column(Integer, nullable=True)
    fps_actual = Column(Float, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    status = Column(String(20), nullable=True)
    captured_at = Column(DateTime, server_default=func.now(), nullable=False)


class CameraHealthSnapshotResponse(BaseModel):
    id: str
    camera_id: str
    packet_loss_percent: Optional[float]
    bitrate_kbps: Optional[int]
    fps_actual: Optional[float]
    latency_ms: Optional[int]
    status: Optional[str]
    captured_at: datetime

    class Config:
        from_attributes = True
