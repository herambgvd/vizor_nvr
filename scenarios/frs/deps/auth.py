"""Shared router dependencies + small cross-router helpers."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException
from sqlalchemy import func, select

from config import VIZOR_SERVICE_TOKEN
from db.models import FRSPerson, FRSPhoto

# Reject a missing/placeholder service token at import time — fail CLOSED. A blank
# or shipped-default token would otherwise leave every route open on the internal
# network. The operator MUST set a strong AI_PLUGIN_SERVICE_TOKEN.
_INSECURE_TOKENS = {"", "dev-ai-service-token", "changeme", "default"}
_TOKEN_OK = bool(VIZOR_SERVICE_TOKEN) and VIZOR_SERVICE_TOKEN not in _INSECURE_TOKENS


def require_service_token(x_vizor_service_token: str | None = Header(None)) -> None:
    """Gate every plugin route behind the shared NVR↔plugin service token.
    Fails CLOSED (503) when no strong token is configured, and uses a
    constant-time compare to avoid leaking the secret via timing."""
    if not _TOKEN_OK:
        raise HTTPException(503, "service token not configured")
    if not x_vizor_service_token or not hmac.compare_digest(
            str(x_vizor_service_token), str(VIZOR_SERVICE_TOKEN)):
        raise HTTPException(401, "invalid service token")


def allowed_camera_ids(
    x_vizor_allowed_camera_ids: str | None = Header(None),
) -> list[str] | None:
    """Camera-scope from the NVR proxy. The proxy forwards the operator's
    authorised cameras in X-Vizor-Allowed-Camera-Ids; read routes MUST constrain
    their queries to this set so a user can't see faces/events from cameras they
    aren't assigned to.

    Returns:
        list[str] — the explicit set of camera ids the caller may read, or
        None    — header absent (no scoping; only when called outside the proxy,
                  e.g. internal jobs) → caller treats as "no restriction".
    An empty list means "scoped to nothing" → the route returns no rows.
    """
    if x_vizor_allowed_camera_ids is None:
        return None
    return [c.strip() for c in x_vizor_allowed_camera_ids.split(",") if c.strip()]


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
