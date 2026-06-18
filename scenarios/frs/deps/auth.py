"""Shared router dependencies + small cross-router helpers."""
from __future__ import annotations

from fastapi import Header, HTTPException
from sqlalchemy import func, select

from config import VIZOR_SERVICE_TOKEN
from db.models import FRSPerson, FRSPhoto


def require_service_token(x_vizor_service_token: str | None = Header(None)) -> None:
    """Gate every plugin route behind the shared NVR↔plugin service token."""
    if VIZOR_SERVICE_TOKEN and x_vizor_service_token != VIZOR_SERVICE_TOKEN:
        raise HTTPException(401, "invalid service token")


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
