"""Serializers (DB row → wire dict) + datetime helpers.

PPE stores naive-UTC timestamps in Postgres and stamps +00:00 on the wire, so the
whole plugin is timezone-consistent regardless of the host/DB server timezone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from db.models import PPEEvent


def utcnow() -> datetime:
    """Single source of truth for 'now': naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalise a (possibly aware) datetime to naive-UTC for DB comparison."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_dt(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return None


def event_dict(e: PPEEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "camera_id": e.camera_id,
        "event_type": e.event_type,
        "severity": e.severity,
        "title": e.title,
        "worker_track_id": e.worker_track_id,
        "ppe_item": e.ppe_item,
        "missing_items": e.missing_items,
        "present_items": e.present_items,
        "confidence": e.confidence,
        "bbox": e.bbox,
        "snapshot_path": e.snapshot_path,
        "triggered_at": iso(e.triggered_at),
    }
