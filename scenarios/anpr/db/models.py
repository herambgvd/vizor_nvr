"""Plugin-owned SQLAlchemy models (own Postgres, isolated from the NVR DB).

Three tables:
  * anpr_plate_reads — one voted read per vehicle pass (the ANPR events).
  * anpr_plate_list  — PER-SCENARIO GLOBAL whitelist/blacklist (one list across
    all ANPR cameras), matched on every read.
  * anpr_settings    — singleton feature config (region/regex, speed, thresholds).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, Index, Integer, String,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _utcnow() -> datetime:
    """Naive-UTC timestamp default. Python-side (not Postgres func.now()) so the
    stored value is UTC regardless of the database server's local timezone."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ANPRPlateRead(Base):
    """One license-plate read per vehicle pass (the ANPR event).

    Produced by the per-track plate session: every tracked vehicle accumulates
    OCR reads while its plate is visible, and a single voted result is written
    when the track exits the scene. event_type ∈ {plate_read, whitelist_hit,
    blacklist_hit} — set from the whitelist/blacklist match at emit time.
    """
    __tablename__ = "anpr_plate_reads"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id = Column(String, nullable=True)
    event_type = Column(String(40), nullable=False, default="plate_read")
    severity = Column(String(20), nullable=True, default="info")
    title = Column(String(200), nullable=True)
    plate = Column(String(32), nullable=False)
    confidence = Column(Float, nullable=True)            # voted OCR conf 0..1
    vehicle_type = Column(String(20), nullable=True)     # car/motorcycle/bus/truck/other
    direction = Column(String(10), nullable=True)        # in/out (line crossing)
    speed_kmh = Column(Float, nullable=True)             # ESTIMATE; only if calibrated
    list_hit = Column(String(20), nullable=True)         # whitelist/blacklist/None
    list_label = Column(String(200), nullable=True)      # matched list entry label
    # Stable per-vehicle track id (ByteTrack) the read was voted from.
    track_id = Column(Integer, nullable=True)
    n_frames = Column(Integer, nullable=True)            # reads that fed the vote
    bbox = Column(JSON, nullable=True)                   # {x,y,w,h} normalised 0..1 (plate box)
    snapshot_path = Column(String(500), nullable=True)
    triggered_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_anpr_reads_camera", "camera_id"),
        Index("ix_anpr_reads_plate", "plate"),
        Index("ix_anpr_reads_type", "event_type"),
        Index("ix_anpr_reads_list", "list_hit"),
        Index("ix_anpr_reads_triggered", "triggered_at"),
    )


class ANPRPlateList(Base):
    """PER-SCENARIO GLOBAL whitelist / blacklist entry (one list across all ANPR
    cameras). Plate is stored normalised (uppercase, A-Z0-9 only) so matching is
    exact. valid_from / valid_to bound an entry's active window (both optional —
    NULL = unbounded)."""
    __tablename__ = "anpr_plate_list"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    plate = Column(String(32), nullable=False)
    list_type = Column(String(20), nullable=False, default="blacklist")  # whitelist/blacklist
    label = Column(String(200), nullable=True)
    valid_from = Column(DateTime, nullable=True)
    valid_to = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_anpr_list_plate", "plate"),
        Index("ix_anpr_list_type", "list_type"),
    )


class ANPRSettings(Base):
    """Singleton ANPR feature config (one row, id='singleton'). Operator-facing
    defaults applied when a camera does not override them. Plugin-owned so ANPR
    config stays with ANPR."""
    __tablename__ = "anpr_settings"
    id = Column(String, primary_key=True, default="singleton")
    region = Column(String(16), nullable=True)           # e.g. "IN"
    plate_regex = Column(String(500), nullable=True)     # override the default regex
    allow_raw_reads = Column(Boolean, nullable=False, default=False)
    lowlight_enhance = Column(Boolean, nullable=False, default=True)
    det_conf = Column(Float, nullable=True)
    ocr_conf = Column(Float, nullable=True)
    min_plate_w = Column(Integer, nullable=True)
    min_reads = Column(Integer, nullable=True)
    speed_enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
