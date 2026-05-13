# =============================================================================
# Bookmark Models
# =============================================================================

from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Text
from sqlalchemy.sql import func
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid

from app.database import Base


class Bookmark(Base):
    __tablename__ = "bookmarks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id = Column(String, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True)
    recording_id = Column(String, ForeignKey("recordings.id", ondelete="SET NULL"), nullable=True, index=True)
    timestamp = Column(Float, nullable=False)  # seconds into the recording
    note = Column(Text, nullable=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())


# =============================================================================
# Pydantic
# =============================================================================

class BookmarkCreate(BaseModel):
    camera_id: str
    recording_id: Optional[str] = None
    timestamp: float
    note: Optional[str] = Field(None, max_length=500)


class BookmarkUpdate(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


class BookmarkResponse(BaseModel):
    id: str
    camera_id: str
    recording_id: Optional[str]
    timestamp: float
    note: Optional[str]
    user_id: str
    created_at: datetime

    class Config:
        from_attributes = True
