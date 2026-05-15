"""
Attendance service — appends/updates FRSAttendance rows from
face_recognized events.

Schema:
  frs_attendance is a TimescaleDB hypertable keyed (id, ts). We don't
  upsert directly — instead each recognition becomes a "punch" entry
  in the `punches` JSON array on the *first* row of the day for that
  person. Multiple recognitions on the same day collapse into one row.

Row identity:
  (person_id, day_key) where day_key = YYYY-MM-DD of ts (UTC).

Punch direction:
  Comes from the camera's FRS config: attendance_role ∈ entry|exit|both.
  "both" → in/out direction inferred from current state (last punch
  direction toggled, defaults to "in" on first sighting).
"""

from __future__ import annotations

import asyncio
import logging
import uuid as _uuid
from datetime import datetime, timezone, date
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import FRSAttendance, CameraAIConfig, AIScenario

logger = logging.getLogger(__name__)


def _day_key(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d")


async def _camera_attendance_role(db: AsyncSession, camera_id: str) -> str:
    """Pull `attendance_role` from camera_ai_configs.config for FRS."""
    result = await db.execute(
        select(CameraAIConfig.config)
        .join(AIScenario, AIScenario.id == CameraAIConfig.scenario_id)
        .where(
            CameraAIConfig.camera_id == camera_id,
            AIScenario.slug == "frs",
            CameraAIConfig.enabled.is_(True),
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return "both"
    return (row or {}).get("attendance_role", "both")


async def record_recognition(
    db: AsyncSession,
    person_id: str,
    camera_id: str,
    ts: datetime,
    confidence: Optional[float] = None,
    event_id: Optional[str] = None,
    snapshot_key: Optional[str] = None,
) -> None:
    """Idempotent: collapses repeated recognitions of the same person on
    the same day into one attendance row with appended punches."""

    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    day = _day_key(ts)
    role = await _camera_attendance_role(db, camera_id)

    # Find the day's existing row (search by ts >= start of day on
    # hypertable index — keeps the query fast even at millions of rows).
    start = datetime.strptime(day, "%Y-%m-%d")
    end = start.replace(hour=23, minute=59, second=59, microsecond=999_999)

    existing = await db.execute(
        select(FRSAttendance)
        .where(
            FRSAttendance.person_id == person_id,
            FRSAttendance.ts >= start,
            FRSAttendance.ts <= end,
        )
        .order_by(FRSAttendance.ts.asc())
        .limit(1)
    )
    row: Optional[FRSAttendance] = existing.scalar_one_or_none()

    if role == "entry":
        direction = "in"
    elif role == "exit":
        direction = "out"
    else:
        # Toggle from previous punch — default to "in" on first sighting
        if row and row.punches:
            last = row.punches[-1].get("direction", "in")
            direction = "out" if last == "in" else "in"
        else:
            direction = "in"

    punch = {
        "direction": direction,
        "at": ts.isoformat(),
        "camera_id": camera_id,
        "event_id": event_id,
        "snapshot_key": snapshot_key,
        "confidence": confidence,
    }

    if row is None:
        row = FRSAttendance(
            id=str(_uuid.uuid4()),
            person_id=person_id,
            camera_id=camera_id,
            ts=ts,
            sighting_type="entry" if direction == "in" else "exit",
            confidence=confidence,
            event_id=event_id,
            punches=[punch],
        )
        db.add(row)
    else:
        # Append punch — but ignore duplicate rapid-fire (<2s gap)
        punches = list(row.punches or [])
        if punches:
            last_at = punches[-1].get("at")
            try:
                last_ts = datetime.fromisoformat(last_at.replace("Z", ""))
                if (ts - last_ts).total_seconds() < 2:
                    return
            except Exception:
                pass
        punches.append(punch)
        row.punches = punches
        # Bump ts to the latest sighting so the row sits at "last seen"
        if ts > row.ts:
            row.ts = ts

    await db.commit()


# ---------------------------------------------------------------------------
# Query helpers used by the API
# ---------------------------------------------------------------------------


async def list_day(db: AsyncSession, day: str) -> Dict[str, Any]:
    """Return rolled-up attendance for a YYYY-MM-DD day."""
    try:
        start = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return {"rows": []}
    end = start.replace(hour=23, minute=59, second=59, microsecond=999_999)

    result = await db.execute(
        select(FRSAttendance)
        .where(FRSAttendance.ts >= start, FRSAttendance.ts <= end)
        .order_by(FRSAttendance.ts.desc())
    )
    rows = result.scalars().all()

    # Collapse to one row per person (hypertable allows multiple)
    by_person: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        punches = r.punches or []
        if not punches:
            continue
        firsts = punches[0].get("at")
        lasts = punches[-1].get("at")
        total_min = None
        try:
            f = datetime.fromisoformat(firsts.replace("Z", ""))
            l = datetime.fromisoformat(lasts.replace("Z", ""))
            total_min = max(0, int((l - f).total_seconds() // 60))
        except Exception:
            pass
        entry = by_person.setdefault(
            r.person_id,
            {
                "person_id": r.person_id,
                "person_name": None,
                "first_seen": firsts,
                "last_seen": lasts,
                "punches": punches,
                "total_minutes": total_min,
            },
        )
        # Merge if more rows for same person (rare but possible)
        if firsts < entry["first_seen"]:
            entry["first_seen"] = firsts
        if lasts > entry["last_seen"]:
            entry["last_seen"] = lasts

    # Hydrate person_name
    if by_person:
        from app.ai.models import FRSPerson
        from sqlalchemy import select as _sel
        result = await db.execute(
            _sel(FRSPerson.id, FRSPerson.name).where(
                FRSPerson.id.in_(list(by_person.keys()))
            )
        )
        for pid, name in result.all():
            if pid in by_person:
                by_person[pid]["person_name"] = name

    return {"rows": list(by_person.values())}
