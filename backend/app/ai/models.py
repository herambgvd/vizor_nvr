# =============================================================================
# AI Scenario + FRS data models (SQLAlchemy ORM + Pydantic schemas).
#
# Scope: the NVR side of the AI integration. Scenarios (FRS, PPE, …) are
# standalone gRPC services; the NVR owns the catalog, per-camera enablement,
# the person gallery UI, and the recognition-event store. Face EMBEDDINGS live
# in the scenario service (Qdrant) — the NVR keeps person metadata + a stable
# person_id the scenario keys its vectors on.
# =============================================================================
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_serializer
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text,
    Index, UniqueConstraint, func,
)

from app.database import Base


# =============================================================================
# AI Scenario catalog
# =============================================================================

class AIScenario(Base):
    """Catalog entry for one AI use-case. Seeded at startup; licensing flips
    `licensed`/`enabled`. `module_tabs` drives the generic scenario UI."""
    __tablename__ = "ai_scenarios"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    slug = Column(String(50), nullable=False, unique=True, index=True)   # "frs", "ppe"
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)          # "security", "safety"
    icon = Column(String(50), nullable=True)              # lucide icon name

    # gRPC endpoint of the standalone scenario service (host:port).
    grpc_endpoint = Column(String(200), nullable=True)    # "frs:50051"

    # Licensing — driven by the signed license `features` + per-feature cap.
    licensed = Column(Boolean, nullable=False, default=False)   # feature present in license
    enabled = Column(Boolean, nullable=False, default=False)    # operator toggle (needs licensed)
    camera_limit = Column(Integer, nullable=False, default=0)   # max cameras (0 = unset)

    # UI: which tabs the generic ScenarioWorkspace renders, in order.
    module_tabs = Column(JSON, nullable=True)   # ["cameras","live","events","persons","attendance","reports"]
    # Per-camera config form (JSON-Schema-ish) the Cameras tab renders.
    camera_config_schema = Column(JSON, nullable=True)
    # Event types this scenario emits (for UI filters / validation).
    event_types = Column(JSON, nullable=True)   # ["face_recognized","face_unknown","spoof_detected"]

    # ── Plugin platform (Phase 1) ────────────────────────────────────────
    # A scenario is a self-describing plugin. These come from its manifest
    # (scenario.json), registered via POST /api/ai/scenarios/register.
    version = Column(String(30), nullable=True)             # manifest version, e.g. "1.2.0"
    capabilities = Column(JSON, nullable=True)              # ["rtsp","image","video","enroll",...]
    license_feature = Column(String(50), nullable=True)    # entitlement key (usually == slug)
    manifest = Column(JSON, nullable=True)                  # raw scenario.json as registered
    source = Column(String(20), nullable=False, default="builtin")  # "builtin"|"manifest"
    registered = Column(Boolean, nullable=False, default=True)      # manifest present / installed
    registered_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class CameraAIConfig(Base):
    """Per-(camera, scenario) enablement + tuning. The bridge reconciles this
    table against the scenario gRPC service (RegisterStream / StopStream)."""
    __tablename__ = "camera_ai_configs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id = Column(String, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
    scenario_id = Column(String, ForeignKey("ai_scenarios.id", ondelete="CASCADE"), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    config = Column(JSON, nullable=True)        # {roi, thresholds, required_ppe, ...}

    # Bridge bookkeeping (set by the bridge, read by UI for status).
    stream_state = Column(String(20), nullable=True)   # "running","stopped","error"
    last_synced_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("camera_id", "scenario_id", name="uq_camera_scenario"),
        Index("ix_camera_ai_scenario", "scenario_id", "enabled"),
    )


# =============================================================================
# FRS person gallery (groups / persons / photos / attendance) and FRS
# recognition events now live entirely in the standalone FRS scenario
# microservice (scenarios/frs), which owns its own Postgres, Qdrant face index
# and photo volume. The NVR no longer defines those tables — see the Alembic
# migration that drops the legacy frs_* tables after data is migrated.
# =============================================================================


# =============================================================================
# Pydantic schemas
# =============================================================================

class ScenarioResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: Optional[str]
    category: Optional[str]
    icon: Optional[str]
    licensed: bool
    enabled: bool
    camera_limit: int
    grpc_endpoint: Optional[str] = None
    module_tabs: Optional[List[str]] = None
    camera_config_schema: Optional[Dict[str, Any]] = None
    event_types: Optional[List[str]] = None
    active_camera_count: int = 0
    # plugin platform
    version: Optional[str] = None
    capabilities: Optional[List[str]] = None
    source: Optional[str] = None
    registered: bool = True
    # Manifest-derived plugin fields. Stored in AIScenario.manifest so we do
    # not need a migration every time the plugin contract grows.
    service_url: Optional[str] = None
    proxy_routes: Optional[List[Dict[str, Any]]] = None
    resource_requirements: Optional[Dict[str, Any]] = None
    tabs: Optional[List[str]] = None
    health: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class ScenarioToggle(BaseModel):
    enabled: bool


class CameraAIConfigCreate(BaseModel):
    camera_id: str
    # Optional in the body: the assign endpoint takes scenario_id from the path
    # and overwrites this field, so callers POST only {camera_id, enabled?, config?}.
    scenario_id: Optional[str] = None
    enabled: bool = True
    config: Optional[Dict[str, Any]] = None


class CameraAIConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None


class CameraAIConfigResponse(BaseModel):
    id: str
    camera_id: str
    scenario_id: str
    enabled: bool
    config: Optional[Dict[str, Any]] = None
    stream_state: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    last_error: Optional[str] = None

    class Config:
        from_attributes = True

    @field_serializer("last_synced_at")
    def _ser(self, dt: Optional[datetime], _info):
        return dt.isoformat() + "Z" if dt and dt.tzinfo is None else (dt.isoformat() if dt else None)


# FRS gallery request/response schemas (GroupCreate, PersonCreate, PhotoResponse,
# …) moved to the FRS scenario microservice (scenarios/frs) along with the data
# they describe. The NVR keeps only the scenario-catalog + camera-config schemas.
