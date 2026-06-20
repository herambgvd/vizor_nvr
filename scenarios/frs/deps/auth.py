"""Shared router dependencies + small cross-router helpers.

The service-token guard + camera-scope dependency now come from the shared Vizor
SDK (the SDK was extracted from this exact code — same fail-CLOSED + hmac +
insecure-token-set behaviour, no change). `recount_person` stays here: it's
FRS-specific gallery logic, not shared plumbing. Re-exported under the original
names so every router's `Depends(require_service_token)` /
`Depends(allowed_camera_ids)` is unchanged.
"""
from __future__ import annotations

from sqlalchemy import func, select

from vizor_sdk import allowed_camera_ids, service_token_guard  # noqa: F401

from config import VIZOR_SERVICE_TOKEN
from db.models import FRSPerson, FRSPhoto

require_service_token = service_token_guard(VIZOR_SERVICE_TOKEN)


def recount_person(s, person_id: str) -> None:
    """Recompute a person's photo counters + enrollment_status after a photo
    change (ported from the NVR FRSService._recount_person)."""
    person = s.get(FRSPerson, person_id)
    if person is None:
        return
    photo_count = s.scalar(select(func.count(FRSPhoto.id)).where(FRSPhoto.person_id == person_id)) or 0
    enrolled = s.scalar(select(func.count(FRSPhoto.id)).where(
        FRSPhoto.person_id == person_id, FRSPhoto.status == "enrolled")) or 0
    pending = s.scalar(select(func.count(FRSPhoto.id)).where(
        FRSPhoto.person_id == person_id, FRSPhoto.status == "pending")) or 0
    person.photo_count = int(photo_count)
    person.enrolled_photo_count = int(enrolled)
    if photo_count == 0:
        person.enrollment_status = "unenrolled"
    elif enrolled > 0:
        person.enrollment_status = "enrolled"
    elif pending > 0:
        person.enrollment_status = "pending"
    else:
        person.enrollment_status = "failed"
    # Person avatar = earliest enrolled photo (or any earliest photo as fallback).
    avatar = s.scalar(
        select(FRSPhoto.id).where(FRSPhoto.person_id == person_id, FRSPhoto.status == "enrolled")
        .order_by(FRSPhoto.created_at.asc()).limit(1)
    ) or s.scalar(
        select(FRSPhoto.id).where(FRSPhoto.person_id == person_id)
        .order_by(FRSPhoto.created_at.asc()).limit(1)
    )
    person.thumbnail_key = avatar
    s.commit()
