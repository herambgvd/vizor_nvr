"""Serializers (DB row → wire dict) + datetime helpers.

ANPR stores naive-UTC timestamps in Postgres and stamps +00:00 on the wire, so
the whole plugin is timezone-consistent regardless of the host/DB server timezone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from db.models import ANPRListDef, ANPRPlateList, ANPRPlateRead


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


def read_dict(e: ANPRPlateRead) -> dict[str, Any]:
    return {
        "id": e.id,
        "camera_id": e.camera_id,
        "event_type": e.event_type,
        "severity": e.severity,
        "title": e.title,
        "plate": e.plate,
        "confidence": e.confidence,
        "vehicle_type": e.vehicle_type,
        "direction": e.direction,
        "speed_kmh": e.speed_kmh,
        "list_hit": e.list_hit,
        "list_label": e.list_label,
        "track_id": e.track_id,
        "n_frames": e.n_frames,
        "bbox": e.bbox,
        "snapshot_path": e.snapshot_path,
        "triggered_at": iso(e.triggered_at),
    }


def list_def_dict(d: ANPRListDef, entry_count: Optional[int] = None) -> dict[str, Any]:
    out = {
        "id": d.id,
        "name": d.name,
        "action": d.action,
        "color": d.color,
        "description": d.description,
        "created_at": iso(d.created_at),
    }
    if entry_count is not None:
        out["entry_count"] = int(entry_count)
    return out


def list_dict(e: ANPRPlateList, ldef: Optional[ANPRListDef] = None) -> dict[str, Any]:
    """A plate entry on the wire. When the owning list def is passed (joined), the
    list's name/action/color are inlined so the UI can render the badge without a
    second call."""
    out = {
        "id": e.id,
        "plate": e.plate,
        "list_id": e.list_id,
        "label": e.label,
        "valid_from": iso(e.valid_from),
        "valid_to": iso(e.valid_to),
        "created_at": iso(e.created_at),
    }
    if ldef is not None:
        out["list_name"] = ldef.name
        out["list_action"] = ldef.action
        out["list_color"] = ldef.color
    return out
