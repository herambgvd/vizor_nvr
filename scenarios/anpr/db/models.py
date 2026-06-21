"""Plugin-owned SQLAlchemy models (own Postgres, isolated from the NVR DB).

Tables:
  * anpr_plate_reads — one voted read per vehicle pass (the ANPR events).
  * anpr_list_def    — USER-DEFINED named plate lists (categories), each with an
    action (alert/allow/log) + colour + description. One row per list.
  * anpr_plate_list  — a plate entry belonging to a list_def (FK). PER-SCENARIO
    GLOBAL (one set of lists across all ANPR cameras), matched on every read.
  * anpr_settings    — singleton feature config (region/regex, speed, thresholds).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String,
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
    blacklist_hit} — set from the matched list's ACTION at emit time
    (alert → blacklist_hit, allow → whitelist_hit, else plate_read).
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
    list_hit = Column(String(120), nullable=True)        # matched LIST NAME / None
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


class ANPRListDef(Base):
    """A USER-DEFINED named plate list (category) — e.g. "VIP", "Staff",
    "Stolen Vehicles", "Banned". PER-SCENARIO GLOBAL (one set of lists across all
    ANPR cameras). Each list carries an ACTION that drives event handling on a
    match:
      * alert — raise a high-severity event (the old blacklist behaviour).
      * allow — positive / log-only match (the old whitelist behaviour, info).
      * log   — just tag the read, no special severity.
    Default action for a new list is "alert". Name is unique."""
    __tablename__ = "anpr_list_def"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(120), nullable=False, unique=True)
    action = Column(String(20), nullable=False, default="alert")  # alert/allow/log
    color = Column(String(20), nullable=True)            # hex, e.g. "#ef4444"
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_anpr_listdef_name", "name"),
    )


class ANPRPlateList(Base):
    """A plate entry belonging to a user list (anpr_list_def via list_id). Plate is
    stored normalised (uppercase, A-Z0-9 only) so matching is exact. valid_from /
    valid_to bound an entry's active window (both optional — NULL = unbounded)."""
    __tablename__ = "anpr_plate_list"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    plate = Column(String(32), nullable=False)
    list_id = Column(
        String, ForeignKey("anpr_list_def.id", ondelete="CASCADE"), nullable=False,
    )
    label = Column(String(200), nullable=True)
    valid_from = Column(DateTime, nullable=True)
    valid_to = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_anpr_list_plate", "plate"),
        Index("ix_anpr_list_listid", "list_id"),
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
    # Public dashboard + third-party ingest (SDK SettingsStore columns).
    public_dashboard_enabled = Column(Boolean, nullable=False, default=False)
    ingest_api_enabled = Column(Boolean, nullable=False, default=False)
    ingest_api_key = Column(String(128), nullable=True)
    # Privacy: plates are sensitive — only show plate text on the public
    # dashboard when the operator opts in (public_show_names).
    public_show_names = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
