# =============================================================================
# Continuous Aggregate Views — read-only SQLAlchemy mappings
#
# These are TimescaleDB continuous aggregates created by the
# `phase9_timescale` migration. They live as materialized views and are
# refreshed on a schedule by Timescale's background workers. The Python
# code only reads from them; never write directly.
#
# Aggregates trade resolution for query latency:
#   events_5min  — drives timeline marker density layer
#   events_1h    — drives hourly dashboards
#   events_1d    — drives 30-day trends + monthly reports
# =============================================================================

from sqlalchemy import Column, DateTime, Integer, Float, String

from app.database import Base


class EventsAggregate5Min(Base):
    """5-minute continuous aggregate of events."""

    __tablename__ = "events_5min"
    __table_args__ = {"info": {"is_view": True}}

    bucket = Column(DateTime, primary_key=True)
    camera_id = Column(String, primary_key=True)
    detection_type = Column(String, primary_key=True)
    severity = Column(String, primary_key=True)
    event_count = Column(Integer, nullable=False)
    avg_confidence = Column(Float, nullable=True)


class EventsAggregate1H(Base):
    __tablename__ = "events_1h"
    __table_args__ = {"info": {"is_view": True}}

    bucket = Column(DateTime, primary_key=True)
    camera_id = Column(String, primary_key=True)
    detection_type = Column(String, primary_key=True)
    severity = Column(String, primary_key=True)
    event_count = Column(Integer, nullable=False)
    avg_confidence = Column(Float, nullable=True)


class EventsAggregate1D(Base):
    __tablename__ = "events_1d"
    __table_args__ = {"info": {"is_view": True}}

    bucket = Column(DateTime, primary_key=True)
    camera_id = Column(String, primary_key=True)
    detection_type = Column(String, primary_key=True)
    severity = Column(String, primary_key=True)
    event_count = Column(Integer, nullable=False)
    avg_confidence = Column(Float, nullable=True)
