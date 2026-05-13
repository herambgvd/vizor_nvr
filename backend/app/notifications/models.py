# =============================================================================
# Notifications Models — webhook configurations, notification history
# =============================================================================

from sqlalchemy import (
    Column, String, Boolean, DateTime, Integer, Text, JSON, ForeignKey,
)
from sqlalchemy.sql import func
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import uuid

from app.database import Base


# =============================================================================
# Enums
# =============================================================================

class NotificationEvent(str, Enum):
    """Events that can trigger notifications."""
    CAMERA_ONLINE = "camera_online"
    CAMERA_OFFLINE = "camera_offline"
    CAMERA_ERROR = "camera_error"
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    RECORDING_ERROR = "recording_error"
    RECORDING_GAP = "recording_gap"        # No new segment for too long
    STORAGE_LOW = "storage_low"
    STORAGE_FULL = "storage_full"
    SYSTEM_ERROR = "system_error"
    USER_LOGIN = "user_login"
    USER_LOGIN_FAILED = "user_login_failed"


# =============================================================================
# ORM Models
# =============================================================================

class WebhookConfig(Base):
    """Webhook endpoint configuration."""
    __tablename__ = "webhook_configs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)
    secret = Column(String(200), nullable=True)  # For HMAC signing
    
    # Events to subscribe to (JSON array of event names)
    events = Column(JSON, nullable=False, default=list)
    
    # Filtering
    camera_ids = Column(JSON, nullable=True)  # null = all cameras
    
    # Settings
    is_active = Column(Boolean, default=True)
    retry_count = Column(Integer, default=3)
    timeout_seconds = Column(Integer, default=10)
    
    # Headers to include in webhook requests
    custom_headers = Column(JSON, nullable=True)
    
    # Stats
    last_triggered_at = Column(DateTime, nullable=True)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class NotificationLog(Base):
    """Log of sent notifications for debugging."""
    __tablename__ = "notification_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    webhook_id = Column(String, nullable=True)  # null for internal events
    event_type = Column(String(50), nullable=False)
    payload = Column(JSON, nullable=True)
    
    status = Column(String(20), default="pending")  # pending, sent, failed
    response_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    
    attempts = Column(Integer, default=0)
    
    created_at = Column(DateTime, server_default=func.now())


# =============================================================================
# Pydantic Schemas
# =============================================================================

class WebhookCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=1)
    secret: Optional[str] = None
    events: List[str] = Field(..., min_items=1)
    camera_ids: Optional[List[str]] = None
    is_active: bool = True
    retry_count: int = Field(3, ge=0, le=10)
    timeout_seconds: int = Field(10, ge=1, le=60)
    custom_headers: Optional[Dict[str, str]] = None


class WebhookUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    url: Optional[str] = None
    secret: Optional[str] = None
    events: Optional[List[str]] = None
    camera_ids: Optional[List[str]] = None
    is_active: Optional[bool] = None
    retry_count: Optional[int] = Field(None, ge=0, le=10)
    timeout_seconds: Optional[int] = Field(None, ge=1, le=60)
    custom_headers: Optional[Dict[str, str]] = None


class WebhookResponse(BaseModel):
    id: str
    name: str
    url: str
    secret: Optional[str]  # Masked in responses
    events: List[str]
    camera_ids: Optional[List[str]]
    is_active: bool
    retry_count: int
    timeout_seconds: int
    custom_headers: Optional[Dict[str, str]]
    last_triggered_at: Optional[datetime]
    success_count: int
    failure_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NotificationLogResponse(BaseModel):
    id: str
    webhook_id: Optional[str]
    event_type: str
    payload: Optional[Dict[str, Any]]
    status: str
    response_code: Optional[int]
    error_message: Optional[str]
    attempts: int
    created_at: datetime

    class Config:
        from_attributes = True


class TestWebhookRequest(BaseModel):
    url: str
    secret: Optional[str] = None
    custom_headers: Optional[Dict[str, str]] = None


# =============================================================================
# Push Notification Token (FCM)
# =============================================================================

class PushToken(Base):
    __tablename__ = "push_tokens"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(500), nullable=False, index=True)  # FCM registration token
    platform = Column(String(20), default="web")  # web, ios, android
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class PushTokenRegisterRequest(BaseModel):
    token: str = Field(..., min_length=1)
    platform: str = Field("web", pattern="^(web|ios|android)$")
