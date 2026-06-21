"""PPE public dashboard + third-party ingest — wired on the shared Vizor SDK.

`store`           — SDK SettingsStore over the singleton PPESettings row (the four
                    public/ingest columns). Used by the public + settings routers.
`build_dashboard` — the aggregate stats callable handed to build_public_router.
`ingest`          — maps a posted third-party PPE event onto record_event.

Aggregate-only: the dashboard NEVER exposes snapshots or raw images — only
counts, per-camera/per-item rollups, an hourly trend and violation-type totals.
PPE item / violation types are not PII, so they are always shown; public_show_names
gates any worker identity (worker_track_id) if surfaced.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select
from vizor_sdk import SettingsStore

from db import session
from db.events import record_event
from db.models import PPEEvent, PPESettings
from schemas import parse_dt, utcnow

# Singleton settings store on the PPE settings row (key prefix "ppe").
store = SettingsStore(session, PPESettings, key_prefix="ppe")


def _iso_utc(dt) -> str:
    """ISO-8601 with a UTC marker so the browser parses naive-UTC as UTC."""
    s = dt.isoformat()
    return s if (dt.tzinfo is not None) else s + "Z"


# Violation event types (negative events) vs. the positive compliant event.
_VIOLATION_TYPES = ("ppe_missing", "ppe_removed")


def build_dashboard(settings: dict) -> dict:
    """Aggregate PPE analytics for the public dashboard. No auth, no snapshots."""
    show_names = bool(settings.get("public_show_names"))
    now = utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with session() as s:
        def _count(*conds):
            q = select(func.count()).select_from(PPEEvent)
            for c in conds:
                q = q.where(c)
            return int(s.scalar(q) or 0)

        violations_today = _count(
            PPEEvent.event_type.in_(_VIOLATION_TYPES),
            PPEEvent.triggered_at >= day_start,
        )
        compliant_today = _count(
            PPEEvent.event_type == "ppe_compliant",
            PPEEvent.triggered_at >= day_start,
        )
        events_today = _count(PPEEvent.triggered_at >= day_start)

        # Missing-PPE-item breakdown today (by canonical ppe_item).
        by_item_rows = s.execute(
            select(PPEEvent.ppe_item, func.count())
            .where(PPEEvent.event_type.in_(_VIOLATION_TYPES),
                   PPEEvent.triggered_at >= day_start,
                   PPEEvent.ppe_item.isnot(None))
            .group_by(PPEEvent.ppe_item)
            .order_by(func.count().desc())
        ).all()
        by_missing_item = [{"item": it or "unknown", "count": int(n)}
                           for it, n in by_item_rows]

        # Per-camera counts today.
        per_cam = s.execute(
            select(PPEEvent.camera_id, func.count())
            .where(PPEEvent.triggered_at >= day_start)
            .group_by(PPEEvent.camera_id)
        ).all()
        by_camera = [{"camera_id": c or "unknown", "count": int(n)}
                     for c, n in per_cam]

        # Hourly trend (last 24h) — bucket by hour.
        since = now - timedelta(hours=24)
        rows = s.execute(
            select(PPEEvent.triggered_at).where(PPEEvent.triggered_at >= since)
        ).all()
        buckets: dict[str, int] = {}
        for (t,) in rows:
            if t is None:
                continue
            key = t.strftime("%H:00")
            buckets[key] = buckets.get(key, 0) + 1
        hourly = [{"hour": h, "count": buckets[h]} for h in sorted(buckets.keys())]

        # Top violation types today.
        tv = s.execute(
            select(PPEEvent.event_type, func.count())
            .where(PPEEvent.event_type.in_(_VIOLATION_TYPES),
                   PPEEvent.triggered_at >= day_start)
            .group_by(PPEEvent.event_type)
            .order_by(func.count().desc())
        ).all()
        top_violation_types = [{"event_type": et, "count": int(n)} for et, n in tv]

    return {
        # Stamp a UTC marker so the browser parses it as UTC, not local time.
        "generated_at": _iso_utc(now),
        "show_names": show_names,
        "totals": {
            "violations_today": violations_today,
            "compliant_today": compliant_today,
            "events_today": events_today,
            "by_missing_item": by_missing_item,
        },
        "by_camera": by_camera,
        "hourly_trend": hourly,
        "top_violation_types": top_violation_types,
    }


# Sample payload for the Settings UI / third-party integrators.
SAMPLE_INGEST_PAYLOAD = {
    "camera_id": "gate-1",
    "camera_name": "Plant Floor",
    "event_type": "ppe_missing",
    "worker_id": "W-1042",
    "missing_items": ["helmet"],
    "confidence": 0.88,
    "timestamp": "2026-06-20T14:30:00Z",
    "bbox": {"x": 100, "y": 80, "w": 120, "h": 220},
    "source": "edge-cam-ai",
}


def ingest(payload: dict) -> dict:
    """Turn a posted third-party PPE event into a recorded PPEEvent.

    payload: {camera_id, camera_name?, event_type(ppe_missing/ppe_removed/
    ppe_compliant), worker_id?, missing_items?[], present_items?[], confidence?,
    timestamp?, bbox?, source?}. Tagged attributes.source="external:..." via the
    event title; the recorder owns the single insert path."""
    camera_id = payload.get("camera_id")
    if not camera_id:
        return {"ok": False, "detail": "camera_id is required"}

    event_type = str(payload.get("event_type") or "ppe_missing")
    if event_type not in ("ppe_missing", "ppe_removed", "ppe_compliant"):
        event_type = "ppe_missing"

    missing_items = payload.get("missing_items") or None
    present_items = payload.get("present_items") or None
    # Single PPE item this event is about (first missing item if not given).
    ppe_item = payload.get("ppe_item")
    if not ppe_item and missing_items:
        ppe_item = missing_items[0]

    ts = parse_dt(payload.get("timestamp")) or utcnow()
    worker_id = payload.get("worker_id")
    # worker_track_id is an int column; an external worker_id may be a string —
    # only pass it through when it is integer-coercible.
    worker_track_id: Optional[int] = None
    try:
        if worker_id is not None:
            worker_track_id = int(worker_id)
    except (TypeError, ValueError):
        worker_track_id = None

    confidence = payload.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None

    event_id = record_event(
        camera_id=str(camera_id),
        event_type=event_type,
        worker_track_id=worker_track_id,
        ppe_item=ppe_item,
        missing_items=list(missing_items) if missing_items else None,
        present_items=list(present_items) if present_items else None,
        confidence=confidence,
        snapshot_path=None,
        ts=ts,
        bbox=payload.get("bbox"),
    )
    return {"ok": True, "event_id": event_id, "event_type": event_type}
