# =============================================================================
# Recording Models
# =============================================================================

from sqlalchemy import (
    Column, String, DateTime, Integer, BigInteger, Float, ForeignKey, Boolean, JSON,
)
from sqlalchemy.sql import func
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

from app.database import Base


class Recording(Base):
    __tablename__ = "recordings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id = Column(String, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(String(500), nullable=False)
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=True)
    duration = Column(Integer, nullable=True)         # seconds
    file_size = Column(BigInteger, nullable=True)      # bytes
    resolution = Column(String(20), nullable=True)
    fps = Column(Float, nullable=True)
    codec = Column(String(20), nullable=True)
    stream_type = Column(String(10), default="main")   # main / sub
    storage_pool_id = Column(String, ForeignKey("storage_pools.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    trigger_type = Column(String(30), nullable=True, default="continuous")  # continuous, motion, event, manual

    # ── Lock / Protect ──────────────────────────────────────────────────
    locked = Column(Boolean, default=False, nullable=False)
    locked_by = Column(String(100), nullable=True)   # username who locked it
    locked_at = Column(DateTime, nullable=True)

    # ── Motion / Event markers ────────────────────────────────────────
    has_motion = Column(Boolean, default=False, nullable=True)
    event_markers = Column(JSON, nullable=True)  # [{"type": "motion", "offset_seconds": 45.2}]

    # ── Integrity / evidence ────────────────────────────────────────────
    checksum = Column(String(64), nullable=True)   # SHA-256 hex digest
    integrity_status = Column(String(20), nullable=True, default="unchecked")  # verified|corrupted|unchecked|missing_file
    redundant_path = Column(String(500), nullable=True)  # mirror copy on failover pool


# =============================================================================
# Pydantic
# =============================================================================

class RecordingResponse(BaseModel):
    id: str
    camera_id: str
    file_path: str
    start_time: datetime
    end_time: Optional[datetime]
    duration: Optional[int]
    file_size: Optional[int]
    resolution: Optional[str]
    fps: Optional[float]
    codec: Optional[str]
    stream_type: str
    storage_pool_id: Optional[str]
    created_at: datetime
    trigger_type: Optional[str] = "continuous"
    has_motion: bool = False
    event_markers: Optional[List[Dict[str, Any]]] = None
    locked: bool = False
    locked_by: Optional[str] = None
    locked_at: Optional[datetime] = None
    checksum: Optional[str] = None
    integrity_status: Optional[str] = "unchecked"
    redundant_path: Optional[str] = None

    class Config:
        from_attributes = True


class TimelineSegment(BaseModel):
    start: datetime
    end: datetime
    recording_id: str


class TimelineResponse(BaseModel):
    camera_id: str
    date: str
    segments: List[TimelineSegment]
    total_seconds: int


class RecordingStatsResponse(BaseModel):
    camera_id: str
    total_recordings: int
    total_size_bytes: int
    oldest_recording: Optional[datetime]
    newest_recording: Optional[datetime]
    total_duration_seconds: int


class ExportRequest(BaseModel):
    camera_id: str
    start_time: datetime
    end_time: datetime
    format: str = Field("mp4", pattern="^(mp4|mkv|avi)$")


class ExportResponse(BaseModel):
    export_id: str
    status: str  # queued / processing / done / failed
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    progress: float = 0.0


class BulkDeleteRequest(BaseModel):
    recording_ids: List[str]

    class Config:
        json_schema_extra = {"example": {"recording_ids": ["abc", "def"]}}


class ClipSegment(BaseModel):
    camera_id: str
    start_time: datetime
    end_time: datetime


class MultiSegmentExportRequest(BaseModel):
    segments: List[ClipSegment] = Field(..., min_length=1, max_length=20)
    format: str = Field("mp4", pattern="^(mp4|mkv|avi)$")
    burn_timestamp: bool = False
