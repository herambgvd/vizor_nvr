"""Plugin-owned SQLAlchemy models (own Postgres, isolated from the NVR DB)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, Index, Integer, String, Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _utcnow() -> datetime:
    """Naive-UTC timestamp default. Python-side (not Postgres func.now()) so the
    stored value is UTC regardless of the database server's local timezone."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PPEEvent(Base):
    """PPE compliance events owned by the PPE plugin (full isolation — these do
    not flow into the NVR generic event store; the NVR reads them via the proxy).

    event_type ∈ {ppe_missing, ppe_removed, ppe_compliant}:
      * ppe_missing  — required PPE was NEVER seen on this worker track.
      * ppe_removed  — PPE was present (stable ≥ min_present) then disappeared.
      * ppe_compliant— worker confirmed wearing all required PPE (positive event).
    """
    __tablename__ = "ppe_events"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id = Column(String, nullable=True)
    event_type = Column(String(50), nullable=False, default="ppe_missing")
    severity = Column(String(20), nullable=True, default="warning")
    title = Column(String(200), nullable=True)
    # Stable per-worker track id (relinked across short occlusions).
    worker_track_id = Column(Integer, nullable=True)
    # The single PPE item this event is about (when applicable), canonical label.
    ppe_item = Column(String(50), nullable=True)
    # Full lists for the operator UI / reports.
    missing_items = Column(JSON, nullable=True)   # ["helmet", ...]
    present_items = Column(JSON, nullable=True)    # ["vest", ...]
    confidence = Column(Float, nullable=True)
    bbox = Column(JSON, nullable=True)             # {x,y,w,h} normalised 0..1
    snapshot_path = Column(String(500), nullable=True)
    triggered_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_ppe_events_camera", "camera_id"),
        Index("ix_ppe_events_type", "event_type"),
        Index("ix_ppe_events_triggered", "triggered_at"),
    )


class PPESettings(Base):
    """Singleton PPE feature config (one row, id='singleton'). Operator-facing
    defaults applied when a camera does not override them. Plugin-owned so PPE
    config stays with PPE."""
    __tablename__ = "ppe_settings"
    id = Column(String, primary_key=True, default="singleton")
    # Default required PPE items (canonical labels) for cameras without a per-cam
    # override. Stored as JSON list.
    required_ppe = Column(JSON, nullable=True)
    # Whether to also emit positive ppe_compliant events (off by default — most
    # deployments only want violations).
    emit_compliant = Column(Boolean, nullable=False, default=False)
    missing_grace = Column(Float, nullable=True)
    min_present = Column(Float, nullable=True)
    cooldown = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
