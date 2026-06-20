"""Public FRS dashboard — UNAUTHENTICATED, aggregate analytics only.

Gated by the public_dashboard_enabled toggle (FRS settings); returns 404 when
off so the surface simply doesn't exist. Exposes only AGGREGATE stats + a
realtime SSE stream — never snapshots or raw face images. Person names appear
only when the operator opts in (public_show_names).
"""
from __future__ import annotations

import json
import queue
from datetime import timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from db import session
from db.events import subscribe, unsubscribe
from db.models import FRSEvent, FRSPerson
from db.settings_store import get_settings
from schemas import utcnow

router = APIRouter(prefix="/public", tags=["public"])


def _guard() -> dict:
    st = get_settings()
    if not st["public_dashboard_enabled"]:
        raise HTTPException(404, "not found")
    return st


@router.get("/dashboard")
def public_dashboard() -> dict:
    """Aggregate FRS analytics for the public dashboard. No auth, no snapshots."""
    st = _guard()
    show_names = st["public_show_names"]
    now = utcnow()
    today = now.date()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with session() as s:
        def _count(*conds):
            q = select(func.count()).select_from(FRSEvent)
            for c in conds:
                q = q.where(c)
            return int(s.scalar(q) or 0)

        recognized = _count(FRSEvent.event_type == "face_recognized")
        recognized_today = _count(FRSEvent.event_type == "face_recognized",
                                  FRSEvent.triggered_at >= day_start)
        unknown_today = _count(FRSEvent.event_type == "face_unknown",
                               FRSEvent.triggered_at >= day_start)
        total_today = _count(FRSEvent.triggered_at >= day_start)
        enrolled_persons = int(s.scalar(select(func.count()).select_from(FRSPerson)) or 0)

        # Per-camera counts today.
        per_cam = s.execute(
            select(FRSEvent.camera_id, func.count())
            .where(FRSEvent.triggered_at >= day_start)
            .group_by(FRSEvent.camera_id)
        ).all()
        by_camera = [{"camera_id": c or "unknown", "count": int(n)} for c, n in per_cam]

        # Hourly trend (last 24h) — bucket by hour.
        since = now - timedelta(hours=24)
        rows = s.execute(
            select(FRSEvent.triggered_at)
            .where(FRSEvent.triggered_at >= since)
        ).all()
        buckets: dict[str, int] = {}
        for (t,) in rows:
            if t is None:
                continue
            key = t.strftime("%H:00")
            buckets[key] = buckets.get(key, 0) + 1
        hourly = [{"hour": h, "count": buckets.get(h, 0)}
                  for h in sorted(buckets.keys())]

        # Top recognised persons today (names only if opted in).
        top = []
        if show_names:
            tp = s.execute(
                select(FRSEvent.person_id, func.count())
                .where(FRSEvent.event_type == "face_recognized",
                       FRSEvent.triggered_at >= day_start,
                       FRSEvent.person_id.isnot(None))
                .group_by(FRSEvent.person_id)
                .order_by(func.count().desc())
                .limit(5)
            ).all()
            for pid, n in tp:
                p = s.get(FRSPerson, pid)
                top.append({"name": p.full_name if p else "—", "count": int(n)})

    return {
        # Stamp +00:00 so the browser parses it as UTC, not local time.
        "generated_at": now.isoformat() + "Z",
        "show_names": show_names,
        "totals": {
            "recognized_all_time": recognized,
            "recognized_today": recognized_today,
            "unknown_today": unknown_today,
            "events_today": total_today,
            "enrolled_persons": enrolled_persons,
        },
        "by_camera": by_camera,
        "hourly_trend": hourly,
        "top_persons": top,
    }


@router.get("/stream")
def public_stream() -> StreamingResponse:
    """SSE realtime feed of new FRS events (aggregate-safe: type/camera/name/
    confidence only — no snapshots). Gated by the public toggle."""
    _guard()
    q = subscribe()

    def _gen():
        try:
            # Initial comment so the connection opens promptly.
            yield ": connected\n\n"
            while True:
                try:
                    item = q.get(timeout=20)
                    yield f"data: {json.dumps(item)}\n\n"
                except queue.Empty:
                    # Heartbeat keeps proxies from closing an idle stream.
                    yield ": ping\n\n"
        finally:
            unsubscribe(q)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
