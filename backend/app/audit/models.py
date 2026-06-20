# =============================================================================
# Audit Models
# =============================================================================

from sqlalchemy import Column, String, DateTime, Text, JSON, Integer
from sqlalchemy.sql import func
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    action = Column(String(100), nullable=False, index=True)
    user_id = Column(String, nullable=True, index=True)
    username = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)
    severity = Column(String(20), default="info")      # info / warning / error / critical
    resource_type = Column(String(50), nullable=True)   # camera / recording / user / setting
    resource_id = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)


# =============================================================================
# Pydantic
# =============================================================================

class AuditLogResponse(BaseModel):
    id: str
    action: str
    user_id: Optional[str]
    username: Optional[str]
    ip_address: Optional[str]
    severity: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    description: Optional[str]
    details: Optional[Dict[str, Any]]
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogPage(BaseModel):
    items: List[AuditLogResponse]
    total: int
    limit: int
    offset: int
