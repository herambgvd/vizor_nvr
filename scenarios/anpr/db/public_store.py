"""ANPR public dashboard + third-party ingest — wired on the shared Vizor SDK.

`store`           — SDK SettingsStore over the singleton ANPRSettings row (the four
                    public/ingest columns).
`build_dashboard` — the aggregate stats callable handed to build_public_router.
`ingest`          — maps a posted third-party plate read onto record_event, running
                    the user-list matcher so an externally-ingested plate still
                    hits alert/allow/log lists.

Aggregate-only: the dashboard NEVER exposes snapshots or raw images. Plates are
sensitive PII — plate text (top_plates) is shown ONLY when public_show_names is on.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from vizor_sdk import SettingsStore, save_ingest_snapshot

import config
from db import session
from db.events import record_event
from db.list_store import match_plate, normalize_plate
from db.models import ANPRPlateRead, ANPRSettings
from schemas import parse_dt, utcnow

# Singleton settings store on the ANPR settings row (key prefix "anpr").
store = SettingsStore(session, ANPRSettings, key_prefix="anpr")


def _iso_utc(dt) -> str:
    """ISO-8601 with a UTC marker so the browser parses naive-UTC as UTC."""
    s = dt.isoformat()
    return s if (dt.tzinfo is not None) else s + "Z"


def build_dashboard(settings: dict) -> dict:
    """Aggregate ANPR analytics for the public dashboard. No auth, no snapshots."""
    show_names = bool(settings.get("public_show_names"))
    now = utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with session() as s:
        def _count(*conds):
            q = select(func.count()).select_from(ANPRPlateRead)
            for c in conds:
                q = q.where(c)
            return int(s.scalar(q) or 0)

        reads_today = _count(ANPRPlateRead.triggered_at >= day_start)
        blacklist_today = _count(ANPRPlateRead.event_type == "blacklist_hit",
                                 ANPRPlateRead.triggered_at >= day_start)
        whitelist_today = _count(ANPRPlateRead.event_type == "whitelist_hit",
                                 ANPRPlateRead.triggered_at >= day_start)
        unique_plates_today = int(s.scalar(
            select(func.count(func.distinct(ANPRPlateRead.plate)))
            .where(ANPRPlateRead.triggered_at >= day_start)
        ) or 0)

        # Per-camera counts today.
        per_cam = s.execute(
            select(ANPRPlateRead.camera_id, func.count())
            .where(ANPRPlateRead.triggered_at >= day_start)
            .group_by(ANPRPlateRead.camera_id)
        ).all()
        by_camera = [{"camera_id": c or "unknown", "count": int(n)}
                     for c, n in per_cam]

        # By vehicle type today.
        per_vt = s.execute(
            select(ANPRPlateRead.vehicle_type, func.count())
            .where(ANPRPlateRead.triggered_at >= day_start)
            .group_by(ANPRPlateRead.vehicle_type)
        ).all()
        by_vehicle_type = [{"vehicle_type": vt or "unknown", "count": int(n)}
                           for vt, n in per_vt]

        # Hourly trend (last 24h) — bucket by hour.
        since = now - timedelta(hours=24)
        rows = s.execute(
            select(ANPRPlateRead.triggered_at)
            .where(ANPRPlateRead.triggered_at >= since)
        ).all()
        buckets: dict[str, int] = {}
        for (t,) in rows:
            if t is None:
                continue
            key = t.strftime("%H:00")
            buckets[key] = buckets.get(key, 0) + 1
        hourly = [{"hour": h, "count": buckets[h]} for h in sorted(buckets.keys())]

        # Top plates today — sensitive, only when the operator opts in.
        top_plates = []
        if show_names:
            tp = s.execute(
                select(ANPRPlateRead.plate, func.count())
                .where(ANPRPlateRead.triggered_at >= day_start)
                .group_by(ANPRPlateRead.plate)
                .order_by(func.count().desc())
                .limit(5)
            ).all()
            top_plates = [{"plate": p, "count": int(n)} for p, n in tp]

    return {
        # Stamp a UTC marker so the browser parses it as UTC, not local time.
        "generated_at": _iso_utc(now),
        "show_names": show_names,
        "totals": {
            "reads_today": reads_today,
            "blacklist_hits_today": blacklist_today,
            "whitelist_hits_today": whitelist_today,
            "unique_plates_today": unique_plates_today,
        },
        "by_camera": by_camera,
        "by_vehicle_type": by_vehicle_type,
        "hourly_trend": hourly,
        "top_plates": top_plates,
    }


# Sample payload for the Settings UI / third-party integrators.
SAMPLE_INGEST_PAYLOAD = {
    "camera_id": "gate-1",
    "camera_name": "North Gate",
    "plate": "MH12AB1234",
    "vehicle_type": "car",
    "direction": "in",
    "speed_kmh": 34.0,
    "confidence": 0.92,
    "timestamp": "2026-06-20T14:30:00Z",
    "bbox": {"x": 100, "y": 80, "w": 160, "h": 60},
    "source": "milesight-nvr",
    "snapshot_base64": "<base64 JPEG/PNG or data: URL — stored + served as the plate-read snapshot>",
}


def ingest(payload: dict) -> dict:
    """Turn a posted third-party plate read into a recorded ANPRPlateRead.

    Normalises the plate, runs the user-list matcher (so an externally-ingested
    plate still hits alert/allow/log lists), derives the event_type from the
    matched action exactly as the live worker does, and records via the shared
    record_event path. payload: {camera_id, camera_name?, plate, vehicle_type?,
    direction?, speed_kmh?, confidence?, timestamp?, bbox?, source?,
    snapshot_base64?}. snapshot_base64 (base64 JPEG/PNG or data URL) is saved +
    served as the plate-read snapshot (best-effort — a bad/absent image never
    fails the ingest)."""
    camera_id = payload.get("camera_id")
    plate = payload.get("plate")
    if not camera_id or not plate:
        return {"ok": False, "detail": "camera_id and plate are required"}

    norm = normalize_plate(str(plate))
    if not norm:
        return {"ok": False, "detail": "plate normalises to empty"}

    # Run the user lists — alert -> blacklist_hit, allow -> whitelist_hit, else read.
    list_hit = None
    list_label = None
    event_type = "plate_read"
    hit = match_plate(norm)
    if hit:
        list_hit = hit.get("list_name")
        list_label = hit.get("label")
        action = hit.get("action")
        if action == "alert":
            event_type = "blacklist_hit"
        elif action == "allow":
            event_type = "whitelist_hit"
        else:
            event_type = "plate_read"

    def _f(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    ts = parse_dt(payload.get("timestamp")) or utcnow()
    # Persist the plate-read image (base64 -> /snapshot?key=ingest:<id>). Best-effort:
    # a bad/absent image returns None and the read still records without a snapshot.
    snapshot_path = save_ingest_snapshot(payload.get("snapshot_base64"), config.DATA_PATH)
    event_id = record_event(
        str(camera_id),
        norm,
        _f(payload.get("confidence")),
        event_type=event_type,
        vehicle_type=payload.get("vehicle_type"),
        direction=payload.get("direction"),
        speed_kmh=_f(payload.get("speed_kmh")),
        list_hit=list_hit,
        list_label=list_label,
        track_id=None,
        n_frames=None,
        bbox=payload.get("bbox"),
        snapshot_path=snapshot_path,
        ts=ts,
    )
    return {
        "ok": True,
        "event_id": event_id,
        "event_type": event_type,
        "list_hit": list_hit,
    }
