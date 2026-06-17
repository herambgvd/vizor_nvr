# =============================================================================
# Event Models — events, event linkage rules
# =============================================================================

from sqlalchemy import (
    Column, String, Boolean, DateTime, Integer, Text, JSON, Float,
    ForeignKey, Index,
)
from sqlalchemy.sql import func
from pydantic import BaseModel, Field, field_serializer
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from enum import Enum
import uuid

from app.database import Base


# =============================================================================
# Enums
# =============================================================================

class EventType(str, Enum):
    MOTION_DETECTED = "motion_detected"
    VIDEO_LOSS = "video_loss"
    CAMERA_TAMPER = "camera_tamper"
    CAMERA_OFFLINE = "camera_offline"
    CAMERA_ONLINE = "camera_online"
    RECORDING_ERROR = "recording_error"
    RECORDING_GAP = "recording_gap"
    STORAGE_LOW = "storage_low"
    DISK_FULL = "disk_full"
    SYSTEM_ERROR = "system_error"
    MANUAL = "manual"
    # ONVIF-sourced event types
    DIGITAL_INPUT_CHANGE = "digital_input_change"   # tns1:Device/Trigger/DigitalInput
    LINE_CROSSING = "line_crossing"                  # tns1:RuleEngine/LineDetector/Crossed
    ZONE_INTRUSION = "zone_intrusion"                # tns1:RuleEngine/FieldDetector/ObjectInside
    AUDIO_ALARM = "audio_alarm"                      # tns1:AudioAnalytics/Audio/DetectedSound
    FACE_DETECTED = "face_detected"                  # tns1:VideoAnalytics/FaceDetection
    ONVIF_METADATA = "onvif_metadata"                # Generic camera-generated Profile M metadata


class EventSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    ALARM = "alarm"


class LinkageAction(str, Enum):
    START_RECORDING = "start_recording"
    SEND_EMAIL = "send_email"
    SEND_WEBHOOK = "send_webhook"
    NOTIFY_CHANNEL = "notify_channel"
    TRIGGER_ALARM_OUTPUT = "trigger_alarm_output"


# =============================================================================
# ORM Models
# =============================================================================

class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id = Column(String, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False, default="info")
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    event_metadata = Column("metadata", JSON, nullable=True)
    snapshot_path = Column(String(500), nullable=True)
    recording_id = Column(String, ForeignKey("recordings.id", ondelete="SET NULL"), nullable=True)
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    is_false_alarm = Column(Boolean, default=False)
    note = Column(Text, nullable=True)
    triggered_at = Column(DateTime, server_default=func.now(), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    # ── Service attribution ──────────────────────────────────────────────
    source_service = Column(String(50), nullable=True, index=True)   # "onvif-event-service", "nvr-motion-detector", etc.
    dedup_key = Column(String(128), nullable=True, unique=True, index=True)
    """
    Idempotency key. Workers compute this from (camera_id, event_type,
    time bucket) so retries of the same logical event don't create
    duplicate rows.
    """

    # ── AI / detection attributes (written by the bridge from scenario events) ──
    detection_type = Column(String(50), nullable=True, index=True)   # "face","ppe_violation",...
    confidence = Column(Float, nullable=True)                        # 0.0..1.0
    bbox = Column(JSON, nullable=True)                               # {x,y,w,h}
    person_id = Column(String, nullable=True, index=True)            # FRS person (soft ref)
    track_id = Column(String(50), nullable=True)
    attributes = Column(JSON, nullable=True)                         # {gender,age,violations,...}

    __table_args__ = (
        Index("ix_events_camera_triggered", "camera_id", "triggered_at"),
        Index("ix_events_source_triggered", "source_service", "triggered_at"),
    )


class EventLinkageRule(Base):
    __tablename__ = "event_linkage_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    trigger_type = Column(String(50), nullable=False)
    trigger_config = Column(JSON, nullable=True)
    actions = Column(JSON, nullable=False)
    camera_ids = Column(JSON, nullable=True)
    enabled = Column(Boolean, default=True)
    schedule = Column(JSON, nullable=True)
    cooldown_seconds = Column(Integer, default=30)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# =============================================================================
# Pydantic Schemas — Events
# =============================================================================

class EventCreate(BaseModel):
    camera_id: Optional[str] = None
    event_type: str
    severity: str = "info"
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    snapshot_path: Optional[str] = None
    recording_id: Optional[str] = None


class EventUpdate(BaseModel):
    acknowledged: Optional[bool] = None
    acknowledged_by: Optional[str] = None
    is_false_alarm: Optional[bool] = None
    note: Optional[str] = None


class EventResponse(BaseModel):
    id: str
    camera_id: Optional[str]
    event_type: str
    severity: str
    title: str
    description: Optional[str]
    event_metadata: Optional[Dict[str, Any]] = None
    snapshot_path: Optional[str]
    recording_id: Optional[str]
    acknowledged: bool
    acknowledged_by: Optional[str]
    acknowledged_at: Optional[datetime]
    is_false_alarm: bool
    note: Optional[str]
    triggered_at: datetime
    created_at: Optional[datetime]

    class Config:
        from_attributes = True

    @field_serializer("triggered_at", "created_at", "acknowledged_at")
    def _serialize_utc(self, dt: Optional[datetime], _info):
        """Emit timezone-aware UTC ISO strings.

        Datetimes are stored naive in the DB but are UTC by convention.
        Without an explicit offset, JS ``new Date()`` interprets the
        string as *local* time, shifting every timestamp by the client's
        UTC offset (e.g. +5:30 IST). Tagging naive values as UTC makes
        the frontend convert correctly to local time for display.
        """
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()


class EventAcknowledge(BaseModel):
    note: Optional[str] = None


class EventMarkFalseAlarm(BaseModel):
    note: Optional[str] = None


class EventBulkDelete(BaseModel):
    """Body for POST /events/bulk-delete. Pass ids, OR filter fields."""
    event_ids: Optional[List[str]] = None
    camera_id: Optional[str] = None
    event_type: Optional[str] = None
    severity: Optional[str] = None
    acknowledged: Optional[bool] = None
    before: Optional[datetime] = None


# =============================================================================
# Pydantic Schemas — Event Linkage Rules
# =============================================================================

class LinkageActionConfig(BaseModel):
    action: str
    config: Optional[Dict[str, Any]] = None


class LinkageRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    trigger_type: str
    trigger_config: Optional[Dict[str, Any]] = None
    actions: List[LinkageActionConfig]
    camera_ids: Optional[List[str]] = None
    enabled: bool = True
    schedule: Optional[Dict[str, Any]] = None
    cooldown_seconds: int = Field(30, ge=0, le=3600)


class LinkageRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger_config: Optional[Dict[str, Any]] = None
    actions: Optional[List[LinkageActionConfig]] = None
    camera_ids: Optional[List[str]] = None
    enabled: Optional[bool] = None
    schedule: Optional[Dict[str, Any]] = None
    cooldown_seconds: Optional[int] = Field(None, ge=0, le=3600)


class LinkageRuleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    trigger_type: str
    trigger_config: Optional[Dict[str, Any]]
    actions: Any
    camera_ids: Optional[List[str]]
    enabled: bool
    schedule: Optional[Dict[str, Any]]
    cooldown_seconds: int
    created_by: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
