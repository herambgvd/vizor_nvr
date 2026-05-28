# =============================================================================
# Spot Output Models — Physical monitor / decoder output configuration
# =============================================================================

from sqlalchemy import Column, String, Integer, Boolean, DateTime, JSON
from sqlalchemy.sql import func
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid

from app.database import Base


class SpotOutput(Base):
    __tablename__ = "spot_outputs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    # Layout: 1x1, 2x2, 3x3, 4x4, 1+5, etc.
    layout = Column(String(20), default="2x2", nullable=False)
    # Ordered list of camera IDs to display in each pane
    camera_ids = Column(JSON, default=list)
    # Stream quality for spot output (low/medium/high)
    quality = Column(String(10), default="medium", nullable=False)
    # go2rtc stream name generated for this spot output
    stream_name = Column(String(100), unique=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SpotOutputCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    layout: str = "2x2"
    camera_ids: List[str] = []
    quality: str = "medium"
    is_active: bool = True


class SpotOutputUpdate(BaseModel):
    name: Optional[str] = None
    layout: Optional[str] = None
    camera_ids: Optional[List[str]] = None
    quality: Optional[str] = None
    is_active: Optional[bool] = None


class SpotOutputResponse(BaseModel):
    id: str
    name: str
    layout: str
    camera_ids: List[str]
    quality: str
    stream_name: str
    is_active: bool
    rtsp_url: str = ""
    created_at: datetime

    class Config:
        from_attributes = True
