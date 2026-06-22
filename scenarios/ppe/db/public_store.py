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

from typing import Optional

from sqlalchemy import func, select
from vizor_sdk import NvrClient, SettingsStore, save_ingest_snapshot

import config
from db import session
from db.events import record_event
from db.models import PPEEvent, PPESettings
from schemas import parse_dt, utcnow

# Singleton settings store on the PPE settings row (key prefix "ppe").
store = SettingsStore(session, PPESettings, key_prefix="ppe")

# Camera id -> name resolver (TTL-cached) so dashboard rows read as names, not UUIDs.
_nvr = NvrClient(config.VIZOR_BASE_URL, config.VIZOR_API_KEY, config.SCENARIO_SLUG)

# Friendly labels for the violation types shown in "Top violations".
_TYPE_LABELS = {
    "ppe_missing": "PPE Missing",
    "ppe_removed": "PPE Removed",
    "ppe_compliant": "Compliant",
}
# Friendly labels for canonical PPE items.
_ITEM_LABELS = {"helmet": "Helmet", "vest": "Vest", "hardhat": "Helmet",
                "safety_vest": "Vest"}


def _item_label(it) -> str:
    if not it:
        return "PPE"
    return _ITEM_LABELS.get(str(it).lower(), str(it).replace("_", " ").title())


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
        by_missing_item = [{"item": _item_label(it), "count": int(n)}
                           for it, n in by_item_rows]

        # Per-camera counts today — resolved to camera NAMES (not UUIDs).
        names = _nvr.camera_names(config.VIZOR_SERVICE_TOKEN)
        per_cam = s.execute(
            select(PPEEvent.camera_id, func.count())
            .where(PPEEvent.triggered_at >= day_start)
            .group_by(PPEEvent.camera_id)
            .order_by(func.count().desc())
        ).all()
        by_camera = [{
            "camera_id": c or "unknown",
            "camera_name": names.get(str(c)) or (str(c)[:8] if c else "Unknown"),
            "count": int(n),
        } for c, n in per_cam]

        # Hourly trend — TODAY ONLY (day_start 00:00 -> current hour), zero-filled.
        # Each bucket carries its UTC ISO timestamp so the browser renders the hour
        # in the OPERATOR's local timezone (events are stored UTC; a UTC hour label
        # looked wrong to a non-UTC operator).
        rows = s.execute(
            select(PPEEvent.triggered_at).where(PPEEvent.triggered_at >= day_start)
        ).all()
        buckets: dict[int, int] = {}
        for (t,) in rows:
            if t is None:
                continue
            buckets[t.hour] = buckets.get(t.hour, 0) + 1
        hourly = []
        for hr in range(0, now.hour + 1):
            ht = day_start.replace(hour=hr)
            hourly.append({
                "hour": f"{hr:02d}:00",     # UTC fallback label
                "ts": _iso_utc(ht),         # browser renders local hour
                "count": buckets.get(hr, 0),
            })

        # Top violations today — by the actual missing ITEM (Helmet / Vest), which
        # is what an operator wants to see, not the internal event_type. Falls
        # back to the event-type label when no item is recorded.
        ti = s.execute(
            select(PPEEvent.ppe_item, func.count())
            .where(PPEEvent.event_type.in_(_VIOLATION_TYPES),
                   PPEEvent.triggered_at >= day_start)
            .group_by(PPEEvent.ppe_item)
            .order_by(func.count().desc())
        ).all()
        top_violation_types = [{
            "type": _item_label(it) if it else "PPE Missing",
            "event_type": "ppe_missing",
            "count": int(n),
        } for it, n in ti]

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
    "snapshot_base64": "<base64 JPEG/PNG or data: URL — stored + served as the event snapshot>",
}


def ingest(payload: dict) -> dict:
    """Turn a posted third-party PPE event into a recorded PPEEvent.

    payload: {camera_id, camera_name?, event_type(ppe_missing/ppe_removed/
    ppe_compliant), worker_id?, missing_items?[], present_items?[], confidence?,
    timestamp?, bbox?, source?, snapshot_base64?}. Tagged attributes.source=
    "external:..." via the event title; the recorder owns the single insert path.
    snapshot_base64 (base64 JPEG/PNG or data URL) is saved + served as the event
    snapshot (best-effort — a bad/absent image never fails the ingest)."""
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

    # Persist the event image (base64 -> /snapshot?key=ingest:<id>). Best-effort:
    # a bad/absent image returns None and the event still records without a snapshot.
    snapshot_path = save_ingest_snapshot(payload.get("snapshot_base64"), config.DATA_PATH)

    event_id = record_event(
        camera_id=str(camera_id),
        event_type=event_type,
        worker_track_id=worker_track_id,
        ppe_item=ppe_item,
        missing_items=list(missing_items) if missing_items else None,
        present_items=list(present_items) if present_items else None,
        confidence=confidence,
        snapshot_path=snapshot_path,
        ts=ts,
        bbox=payload.get("bbox"),
    )
    return {"ok": True, "event_id": event_id, "event_type": event_type}
