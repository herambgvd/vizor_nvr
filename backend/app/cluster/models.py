# =============================================================================
# Cluster Models — N+1 Hot Standby
# =============================================================================

from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text
from sqlalchemy.sql import func
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid

from app.database import Base


class ClusterNode(Base):
    __tablename__ = "cluster_nodes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id = Column(String(100), unique=True, nullable=False)
    hostname = Column(String(200), nullable=False)
    role = Column(String(20), default="standby")  # active / standby
    is_leader = Column(Boolean, default=False, nullable=False)
    last_heartbeat_at = Column(DateTime, nullable=True)
    heartbeat_interval_sec = Column(Integer, default=5)
    lease_ttl_sec = Column(Integer, default=15)
    # Metadata
    ip_address = Column(String(45), nullable=True)
    version = Column(String(20), nullable=True)
    # Failover state
    promoted_at = Column(DateTime, nullable=True)
    demoted_at = Column(DateTime, nullable=True)
    failover_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class ClusterNodeCreate(BaseModel):
    node_id: str = Field(..., min_length=1, max_length=100)
    hostname: str = Field(..., min_length=1, max_length=200)
    ip_address: Optional[str] = None
    version: Optional[str] = None


class ClusterNodeResponse(BaseModel):
    id: str
    node_id: str
    hostname: str
    role: str
    is_leader: bool
    last_heartbeat_at: Optional[datetime] = None
    ip_address: Optional[str] = None
    version: Optional[str] = None
    promoted_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ClusterStatusResponse(BaseModel):
    this_node: str
    role: str
    is_leader: bool
    leader_node: Optional[str] = None
    nodes: list
    camera_count: int = 0
