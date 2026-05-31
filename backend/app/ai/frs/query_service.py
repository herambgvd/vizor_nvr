# =============================================================================
# FRS Query Service (F6) — read-side aggregation over the NVR event store +
# the FRS attendance / person tables.
#
# This service is *read-only*. It powers the FRS workspace tabs:
#   - Events     : recognition events emitted by the FRS scenario (stored in the
#                  unified `events` table by the bridge with detection_type="face"
#                  and/or source_service="frs").
#   - Attendance : daily sighting log (FRSAttendance) joined to person names.
#   - Reports    : SQL aggregates for the attendance report + dashboard summary.
#
# It never writes. Enrollment / person CRUD lives in frs_router.py.
# =============================================================================
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import FRSAttendance, FRSPerson
from app.events.models import Event

logger = logging.getLogger(__name__)

# Event-type values the FRS scenario emits. Used to scope the "summary"
# spoof/unknown buckets and as a fallback filter when source attribution is
# missing. Kept loose on purpose — the bridge may attach any of these.
FACE_EVENT_TYPES = ("face_recognized", "face_unknown", "spoof_detected", "face_detected")
UNKNOWN_EVENT_TYPES = ("face_unknown",)
SPOOF_EVENT_TYPES = ("spoof_detected",)


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """Emit a timezone-aware UTC ISO string (DB stores naive-UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalise an incoming (possibly tz-aware) datetime to naive-UTC so it
    can be compared against the DB's TIMESTAMP WITHOUT TIME ZONE columns.
    asyncpg rejects aware datetimes bound to naive columns."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class FRSQueryService:
    """Read-side queries for the FRS workspace (events / attendance / reports)."""

    # ------------------------------------------------------------------
    # Scope helper
    # ------------------------------------------------------------------

    @staticmethod
    def _face_scope():
        """SQL predicate selecting FRS-originated events.

        An event belongs to FRS if it was attributed to the FRS service
        (source_service='frs') OR carries a face detection_type. The bridge
        sets source_service; older/edge events may only set detection_type.
        """
        return or_(
            Event.source_service == "frs",
            Event.detection_type == "face",
            Event.event_type.in_(FACE_EVENT_TYPES),
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @staticmethod
    async def query_recognition_events(
        db: AsyncSession,
        scenario_slug: str = "frs",
        camera_ids: Optional[List[str]] = None,
        person_id: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Return (rows, total) of FRS recognition events, newest first.

        Filters compose with AND. `scenario_slug` is accepted for API
        symmetry; FRS events are identified via _face_scope() rather than a
        per-scenario column.
        """
        conds = [FRSQueryService._face_scope()]
        if camera_ids:
            conds.append(Event.camera_id.in_(camera_ids))
        if person_id:
            conds.append(Event.person_id == person_id)
        if event_type:
            conds.append(Event.event_type == event_type)
        if since:
            conds.append(Event.triggered_at >= _naive(since))
        if until:
            conds.append(Event.triggered_at <= _naive(until))

        where = and_(*conds)

        total = (
            await db.execute(select(func.count()).select_from(Event).where(where))
        ).scalar_one()

        result = await db.execute(
            select(Event)
            .where(where)
            .order_by(Event.triggered_at.desc())
            .limit(limit)
            .offset(offset)
        )
        events = result.scalars().all()

        rows = [
            {
                "id": e.id,
                "camera_id": e.camera_id,
                "event_type": e.event_type,
                "severity": e.severity,
                "title": e.title,
                "description": e.description,
                "detection_type": e.detection_type,
                "person_id": e.person_id,
                "track_id": e.track_id,
                "confidence": e.confidence,
                "bbox": e.bbox,
                "attributes": e.attributes,
                "snapshot_path": e.snapshot_path,
                "triggered_at": _iso_utc(e.triggered_at),
            }
            for e in events
        ]
        return rows, int(total)

    # ------------------------------------------------------------------
    # Attendance
    # ------------------------------------------------------------------

    @staticmethod
    async def list_attendance(
        db: AsyncSession,
        person_id: Optional[str] = None,
        camera_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Return (rows, total) of attendance records joined to person names,
        newest day first. `since`/`until` filter on check_in_at."""
        conds = []
        if person_id:
            conds.append(FRSAttendance.person_id == person_id)
        if camera_id:
            conds.append(FRSAttendance.camera_id == camera_id)
        if since:
            conds.append(FRSAttendance.check_in_at >= _naive(since))
        if until:
            conds.append(FRSAttendance.check_in_at <= _naive(until))

        where = and_(*conds) if conds else None

        count_stmt = select(func.count()).select_from(FRSAttendance)
        if where is not None:
            count_stmt = count_stmt.where(where)
        total = (await db.execute(count_stmt)).scalar_one()

        stmt = (
            select(FRSAttendance, FRSPerson.full_name)
            .outerjoin(FRSPerson, FRSPerson.id == FRSAttendance.person_id)
            .order_by(FRSAttendance.day_key.desc(), FRSAttendance.check_in_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if where is not None:
            stmt = stmt.where(where)

        result = await db.execute(stmt)
        rows = [
            {
                "id": a.id,
                "person_id": a.person_id,
                "person_name": full_name,
                "camera_id": a.camera_id,
                "day_key": a.day_key,
                "check_in_at": _iso_utc(a.check_in_at),
                "check_out_at": _iso_utc(a.check_out_at),
                "sighting_type": a.sighting_type,
                "event_id": a.event_id,
            }
            for a, full_name in result.all()
        ]
        return rows, int(total)

    @staticmethod
    async def attendance_report(
        db: AsyncSession,
        day_from: str,
        day_to: str,
    ) -> List[Dict[str, Any]]:
        """Per-person attendance aggregate across the [day_from, day_to]
        inclusive range (YYYY-MM-DD strings).

        Returns one row per person with days_present, first_seen, last_seen.
        """
        where = and_(
            FRSAttendance.day_key >= day_from,
            FRSAttendance.day_key <= day_to,
        )

        stmt = (
            select(
                FRSAttendance.person_id,
                FRSPerson.full_name,
                func.count(func.distinct(FRSAttendance.day_key)).label("days_present"),
                func.min(FRSAttendance.check_in_at).label("first_seen"),
                func.max(
                    func.coalesce(FRSAttendance.check_out_at, FRSAttendance.check_in_at)
                ).label("last_seen"),
            )
            .outerjoin(FRSPerson, FRSPerson.id == FRSAttendance.person_id)
            .where(where)
            .group_by(FRSAttendance.person_id, FRSPerson.full_name)
            .order_by(func.count(func.distinct(FRSAttendance.day_key)).desc())
        )

        result = await db.execute(stmt)
        return [
            {
                "person_id": person_id,
                "person_name": full_name,
                "days_present": int(days_present or 0),
                "first_seen": _iso_utc(first_seen),
                "last_seen": _iso_utc(last_seen),
            }
            for person_id, full_name, days_present, first_seen, last_seen in result.all()
        ]

    # ------------------------------------------------------------------
    # Reports — dashboard summary
    # ------------------------------------------------------------------

    @staticmethod
    async def summary(
        db: AsyncSession,
        scenario_slug: str = "frs",
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Dashboard summary over FRS events in [since, until].

        Returns:
            {
              total_events, unique_persons, unknown_count, spoof_count,
              by_camera: [{camera_id, count}],
              by_hour:   [{hour, count}]   # hour = 0..23 (UTC)
            }
        """
        conds = [FRSQueryService._face_scope()]
        if since:
            conds.append(Event.triggered_at >= _naive(since))
        if until:
            conds.append(Event.triggered_at <= _naive(until))
        where = and_(*conds)

        # Single round-trip for the scalar counters.
        agg_stmt = select(
            func.count().label("total_events"),
            func.count(func.distinct(Event.person_id)).label("unique_persons"),
            func.count()
            .filter(Event.event_type.in_(UNKNOWN_EVENT_TYPES))
            .label("unknown_count"),
            func.count()
            .filter(Event.event_type.in_(SPOOF_EVENT_TYPES))
            .label("spoof_count"),
        ).where(where)
        agg = (await db.execute(agg_stmt)).one()

        # by_camera
        cam_stmt = (
            select(Event.camera_id, func.count().label("count"))
            .where(where)
            .group_by(Event.camera_id)
            .order_by(func.count().desc())
        )
        by_camera = [
            {"camera_id": cam_id, "count": int(cnt)}
            for cam_id, cnt in (await db.execute(cam_stmt)).all()
        ]

        # by_hour — hour-of-day bucket (UTC). extract('hour', ...) is portable
        # on Postgres; cast to int for clean JSON in the comprehension below.
        hour_stmt = (
            select(
                func.extract("hour", Event.triggered_at).label("hour"),
                func.count().label("count"),
            )
            .where(where)
            .group_by(func.extract("hour", Event.triggered_at))
            .order_by(func.extract("hour", Event.triggered_at))
        )
        by_hour = [
            {"hour": int(hour), "count": int(cnt)}
            for hour, cnt in (await db.execute(hour_stmt)).all()
        ]

        return {
            "total_events": int(agg.total_events or 0),
            "unique_persons": int(agg.unique_persons or 0),
            "unknown_count": int(agg.unknown_count or 0),
            "spoof_count": int(agg.spoof_count or 0),
            "by_camera": by_camera,
            "by_hour": by_hour,
        }


# Module-level singleton (house style — see ai_service).
frs_query_service = FRSQueryService()
