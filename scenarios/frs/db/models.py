"""Plugin-owned SQLAlchemy models (own Postgres, isolated from the NVR DB)."""
from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class FRSGroup(Base):
    __tablename__ = "frs_groups"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False, unique=True)
    group_type = Column(String(50), nullable=True)
    color_code = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)
    alert_sound = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class FRSPerson(Base):
    __tablename__ = "frs_persons"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    full_name = Column(String(200), nullable=False)
    external_id = Column(String(100), nullable=True, unique=True)
    group_id = Column(String, ForeignKey("frs_groups.id", ondelete="SET NULL"), nullable=True)
    category = Column(String(20), nullable=False, default="standard")
    priority = Column(Integer, nullable=False, default=0)
    enrollment_status = Column(String(20), nullable=False, default="unenrolled")
    photo_count = Column(Integer, nullable=False, default=0)
    enrolled_photo_count = Column(Integer, nullable=False, default=0)
    thumbnail_key = Column(String(500), nullable=True)
    attributes = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index("ix_frs_persons_group", "group_id"),
        Index("ix_frs_persons_category", "category"),
    )


class FRSPhoto(Base):
    __tablename__ = "frs_photos"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    person_id = Column(String, ForeignKey("frs_persons.id", ondelete="CASCADE"), nullable=False)
    storage_key = Column(String(500), nullable=True)
    thumbnail_key = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    embedding_id = Column(String(100), nullable=True)
    quality_score = Column(Float, nullable=True)
    liveness_score = Column(Float, nullable=True)
    sharpness_score = Column(Float, nullable=True)
    error_code = Column(String(50), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (Index("ix_frs_photos_person", "person_id"),)


class FRSAttendance(Base):
    __tablename__ = "frs_attendance"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    person_id = Column(String, ForeignKey("frs_persons.id", ondelete="CASCADE"), nullable=False)
    camera_id = Column(String, nullable=True)
    day_key = Column(String(10), nullable=False)
    check_in_at = Column(DateTime, nullable=True)
    check_out_at = Column(DateTime, nullable=True)
    check_in_snapshot = Column(String(500), nullable=True)   # face crop at check-in
    check_out_snapshot = Column(String(500), nullable=True)  # face crop at check-out
    sighting_type = Column(String(20), nullable=True)
    event_id = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("person_id", "day_key", name="uq_person_day"),
        Index("ix_frs_attendance_day", "day_key"),
    )


class FRSEvent(Base):
    """Recognition events owned by the FRS plugin (full isolation — these do not
    flow into the NVR generic event store)."""
    __tablename__ = "frs_events"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id = Column(String, nullable=True)
    event_type = Column(String(50), nullable=False, default="face_recognized")
    severity = Column(String(20), nullable=True, default="info")
    title = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    detection_type = Column(String(50), nullable=True, default="face")
    person_id = Column(String, nullable=True)
    track_id = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=True)
    bbox = Column(JSON, nullable=True)
    attributes = Column(JSON, nullable=True)
    snapshot_path = Column(String(500), nullable=True)
    triggered_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        Index("ix_frs_events_person", "person_id"),
        Index("ix_frs_events_triggered", "triggered_at"),
    )


class TransitRule(Base):
    __tablename__ = "frs_transit_rules"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    config = Column(JSON, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class TransitSession(Base):
    __tablename__ = "frs_transit_sessions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    rule_id = Column(String, nullable=True)
    person_id = Column(String, nullable=True)
    status = Column(String(20), nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    attributes = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class FRSFeedback(Base):
    """Operator ground-truth on a recognition event (correct/wrong + correction)."""
    __tablename__ = "frs_feedback"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id = Column(String, nullable=False)
    is_correct = Column(Boolean, nullable=False)
    matched_person_id = Column(String, nullable=True)   # who the model said
    actual_person_id = Column(String, nullable=True)    # who it really is (if wrong)
    note = Column(Text, nullable=True)
    operator = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("event_id", "operator", name="uq_feedback_event_operator"),)


class InvestigationJob(Base):
    """Forensic search job — persisted so results survive restarts."""
    __tablename__ = "frs_investigations"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="done")  # queued/running/done/failed
    similarity_threshold = Column(Float, nullable=True)
    max_results = Column(Integer, nullable=True)
    result_count = Column(Integer, nullable=True)
    results = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
