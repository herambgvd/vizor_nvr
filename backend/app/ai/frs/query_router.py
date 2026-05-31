# =============================================================================
# FRS Query API (F6) — live / events / attendance / reports read endpoints.
#
#   GET /api/ai/frs/events             — recognition events (filters)
#   GET /api/ai/frs/attendance         — attendance list (person name joined)
#   GET /api/ai/frs/attendance/report  — per-person attendance aggregate
#   GET /api/ai/frs/reports/summary    — dashboard summary aggregates
#   GET /api/ai/frs/live               — recent events for FE polling (last 50)
#
# Prefix coordination: this router and frs_router.py both mount under
# /api/ai/frs. They use disjoint subpaths so there is no route collision:
#   - frs_query_router (this file): /events, /attendance, /reports, /live
#   - frs_router      (sibling)   : /persons, /groups, /photos
#
# LIVE choice: the NVR already exposes a Server-Sent-Events stream at
# /api/events/stream (app/events/sse_router.py) that fans out *all* NVR events,
# including FRS recognition events the bridge ingests. Rather than stand up a
# second SSE channel, the FRS live tab subscribes to that stream filtered by
# camera_id, and uses GET /api/ai/frs/live for the initial backfill / a
# polling fallback (returns the most recent recognition events). This keeps a
# single pub/sub fan-out and avoids duplicate keep-alive bookkeeping.
# =============================================================================
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.frs.query_service import frs_query_service
from app.core.dependencies import get_current_user
from app.database import get_db

router = APIRouter(prefix="/api/ai/frs", tags=["FRS Query"])


# ── Events ────────────────────────────────────────────────────────────────


@router.get("/events")
async def list_recognition_events(
    camera_id: Optional[List[str]] = Query(None, description="Filter by camera id(s)"),
    person_id: Optional[str] = Query(None, description="Filter by FRS person id"),
    event_type: Optional[str] = Query(None, description="e.g. face_recognized"),
    since: Optional[datetime] = Query(None, description="triggered_at >= since"),
    until: Optional[datetime] = Query(None, description="triggered_at <= until"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    rows, total = await frs_query_service.query_recognition_events(
        db,
        scenario_slug="frs",
        camera_ids=camera_id,
        person_id=person_id,
        event_type=event_type,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


# ── Attendance ──────────────────────────────────────────────────────────────


@router.get("/attendance")
async def list_attendance(
    person_id: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None, description="check_in_at >= since"),
    until: Optional[datetime] = Query(None, description="check_in_at <= until"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    rows, total = await frs_query_service.list_attendance(
        db,
        person_id=person_id,
        camera_id=camera_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/attendance/report")
async def attendance_report(
    day_from: str = Query(..., description="YYYY-MM-DD (inclusive)"),
    day_to: str = Query(..., description="YYYY-MM-DD (inclusive)"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    if day_from > day_to:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "day_from must not be after day_to"
        )
    rows = await frs_query_service.attendance_report(db, day_from, day_to)
    return {"items": rows, "day_from": day_from, "day_to": day_to}


# ── Reports ────────────────────────────────────────────────────────────────


@router.get("/reports/summary")
async def reports_summary(
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await frs_query_service.summary(
        db, scenario_slug="frs", since=since, until=until
    )


# ── Live (recent events for FE polling / SSE backfill) ──────────────────────


@router.get("/live")
async def live_recent_events(
    camera_id: Optional[List[str]] = Query(None, description="Filter by camera id(s)"),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Most-recent FRS recognition events (newest first).

    Used as the initial backfill for the live tab and as a polling fallback
    when the shared SSE stream (/api/events/stream) is unavailable. See the
    module docstring for the live-delivery design choice.
    """
    rows, _ = await frs_query_service.query_recognition_events(
        db,
        scenario_slug="frs",
        camera_ids=camera_id,
        limit=limit,
        offset=0,
    )
    return {"items": rows, "stream_url": "/api/events/stream"}
