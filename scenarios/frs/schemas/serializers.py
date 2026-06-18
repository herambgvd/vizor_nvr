"""Serializers (DB row → wire dict) + datetime helpers.

Plain dict serializers keep the wire contract identical to the NVR's former FRS
API so the frontend tabs are unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from db.models import FRSEvent, FRSGroup, FRSPerson, FRSPhoto


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
    except Exception:
        return None


def person_dict(p: FRSPerson) -> dict[str, Any]:
    return {
        "id": p.id, "full_name": p.full_name, "external_id": p.external_id,
        "group_id": p.group_id, "category": p.category, "priority": p.priority,
        "enrollment_status": p.enrollment_status, "photo_count": p.photo_count,
        "enrolled_photo_count": p.enrolled_photo_count, "thumbnail_key": p.thumbnail_key,
        "attributes": p.attributes,
        "created_at": iso(p.created_at), "updated_at": iso(p.updated_at),
    }


def group_dict(g: FRSGroup, member_count: int) -> dict[str, Any]:
    return {
        "id": g.id, "name": g.name, "group_type": g.group_type,
        "color_code": g.color_code, "description": g.description,
        "alert_sound": g.alert_sound, "member_count": member_count,
    }


def photo_dict(ph: FRSPhoto) -> dict[str, Any]:
    return {
        "id": ph.id, "person_id": ph.person_id, "storage_key": ph.storage_key,
        "thumbnail_key": ph.thumbnail_key, "status": ph.status, "embedding_id": ph.embedding_id,
        "quality_score": ph.quality_score, "liveness_score": ph.liveness_score,
        "sharpness_score": ph.sharpness_score, "error_code": ph.error_code, "error": ph.error,
        "created_at": iso(ph.created_at), "updated_at": iso(ph.updated_at),
    }


def event_dict(e: FRSEvent) -> dict[str, Any]:
    return {
        "id": e.id, "camera_id": e.camera_id, "event_type": e.event_type, "severity": e.severity,
        "title": e.title, "description": e.description, "detection_type": e.detection_type,
        "person_id": e.person_id, "track_id": e.track_id, "confidence": e.confidence,
        "bbox": e.bbox, "attributes": e.attributes, "snapshot_path": e.snapshot_path,
        "triggered_at": iso(e.triggered_at),
    }
