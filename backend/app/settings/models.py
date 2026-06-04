# =============================================================================
# Settings Models
# =============================================================================

from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

from app.database import Base


class Settings(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True, nullable=False)
    value = Column(Text, nullable=True)
    value_type = Column(String(20), default="string")  # string / int / bool / json
    category = Column(String(50), default="general")
    description = Column(Text, nullable=True)
    is_sensitive = Column(Boolean, default=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# Default settings
DEFAULT_SETTINGS = {
    # General
    "system_name": {"value": "Vizor NVR", "type": "string", "category": "general", "desc": "System display name"},
    "timezone": {"value": "UTC", "type": "string", "category": "general", "desc": "System timezone"},

    # Retention
    "retention_enabled": {"value": "true", "type": "bool", "category": "retention", "desc": "Enable auto-deletion"},
    "retention_days": {"value": "30", "type": "int", "category": "retention", "desc": "Days to keep recordings"},
    "retention_max_storage_gb": {"value": "0", "type": "int", "category": "retention", "desc": "Max storage GB (0=unlimited)"},
    "retention_check_interval_min": {"value": "60", "type": "int", "category": "retention", "desc": "Retention check interval (minutes)"},

    # Recording
    "default_segment_duration": {"value": "900", "type": "int", "category": "recording", "desc": "Segment duration (seconds)"},
    "default_recording_fps": {"value": "0", "type": "int", "category": "recording", "desc": "Default FPS (0=source)"},
    "recording_format": {"value": "mp4", "type": "string", "category": "recording", "desc": "mp4 or mkv"},

    # License
    "max_cameras": {"value": "64", "type": "int", "category": "license", "desc": "Maximum cameras allowed"},
    "license_key": {"value": "", "type": "string", "category": "license", "desc": "License key"},

    # FFmpeg
    "ffmpeg_recovery_enabled": {"value": "true", "type": "bool", "category": "recording", "desc": "Auto-restart FFmpeg on crash"},
    "ffmpeg_health_check_interval": {"value": "30", "type": "int", "category": "recording", "desc": "FFmpeg health check (seconds)"},

    # Email / SMTP
    "smtp_enabled":    {"value": "false",       "type": "bool",   "category": "notifications", "desc": "Enable email notifications"},
    "smtp_host":       {"value": "",             "type": "string", "category": "notifications", "desc": "SMTP server hostname"},
    "smtp_port":       {"value": "587",          "type": "int",    "category": "notifications", "desc": "SMTP server port (587=TLS, 465=SSL)"},
    "smtp_username":   {"value": "",             "type": "string", "category": "notifications", "desc": "SMTP login username"},
    "smtp_password":   {"value": "",             "type": "string", "category": "notifications", "desc": "SMTP login password", "sensitive": True},
    "smtp_use_tls":    {"value": "true",         "type": "bool",   "category": "notifications", "desc": "Use STARTTLS (port 587)"},
    "smtp_use_ssl":    {"value": "false",        "type": "bool",   "category": "notifications", "desc": "Use implicit SSL (port 465)"},
    "smtp_from_email": {"value": "",             "type": "string", "category": "notifications", "desc": "Sender email address"},
    "smtp_from_name":  {"value": "Vizor NVR",     "type": "string", "category": "notifications", "desc": "Sender display name"},
    "smtp_recipients": {"value": "",             "type": "string", "category": "notifications", "desc": "Comma-separated recipient email addresses"},
    "smtp_alert_events": {
        "value": "camera_offline,recording_error,storage_low,storage_full,recording_gap",
        "type": "string", "category": "notifications",
        "desc": "Comma-separated event types that trigger emails"
    },

    # Twilio / SMS / WhatsApp
    "twilio_account_sid":  {"value": "", "type": "string", "category": "notifications", "desc": "Twilio Account SID"},
    "twilio_auth_token":   {"value": "", "type": "string", "category": "notifications", "desc": "Twilio Auth Token", "sensitive": True},
    "twilio_phone_number": {"value": "", "type": "string", "category": "notifications", "desc": "Twilio phone number for SMS (E.164, e.g. +1234567890)"},
    "twilio_whatsapp_number": {"value": "", "type": "string", "category": "notifications", "desc": "Twilio WhatsApp sender number (E.164)"},
    "sms_recipients":      {"value": "", "type": "string", "category": "notifications", "desc": "Comma-separated phone numbers for SMS alerts"},
    "whatsapp_recipients": {"value": "", "type": "string", "category": "notifications", "desc": "Comma-separated phone numbers for WhatsApp alerts"},
    "sms_alert_events": {
        "value": "camera_offline,recording_error,storage_full",
        "type": "string", "category": "notifications",
        "desc": "Comma-separated event types that trigger SMS"
    },
    "whatsapp_alert_events": {
        "value": "camera_offline,recording_error,storage_full",
        "type": "string", "category": "notifications",
        "desc": "Comma-separated event types that trigger WhatsApp"
    },
}


# =============================================================================
# Pydantic
# =============================================================================

class SettingResponse(BaseModel):
    key: str
    value: Optional[str]
    value_type: Optional[str] = "string"
    category: str
    description: Optional[str] = None
    is_sensitive: bool = False
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class SettingUpdate(BaseModel):
    value: str


class BulkSettingsUpdate(BaseModel):
    settings: Dict[str, str]   # key → value


class RetentionConfig(BaseModel):
    enabled: bool = True
    days: int = Field(30, ge=1)
    max_storage_gb: int = Field(0, ge=0)
    check_interval_min: int = Field(60, ge=5)


class RecordingConfig(BaseModel):
    segment_duration: int = Field(900, ge=60, le=7200)
    default_fps: int = Field(0, ge=0, le=60)
    format: str = "mp4"
    ffmpeg_recovery: bool = True
    health_check_interval: int = Field(30, ge=10)
