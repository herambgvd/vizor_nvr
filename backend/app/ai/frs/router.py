"""
FRS API — attendance + investigation.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid as _uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai/frs", tags=["AI · FRS"])


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------


@router.get("/attendance")
async def get_attendance(
    day: str,
    user=Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Return rolled-up attendance for a YYYY-MM-DD day."""
    from app.ai.frs.attendance import list_day
    return await list_day(db, day)


# ---------------------------------------------------------------------------
# Investigation
# ---------------------------------------------------------------------------


class InvestigationHit(BaseModel):
    person_id: Optional[str]
    score: float
    photo_id: Optional[str] = None
    ts: Optional[str] = None
    event_id: Optional[str] = None
    camera_id: Optional[str] = None
    snapshot_path: Optional[str] = None


class InvestigationResult(BaseModel):
    matches: int
    results: List[InvestigationHit]


@router.post("/investigate", response_model=InvestigationResult)
async def investigate(
    file: UploadFile = File(...),
    since: Optional[str] = Form(None),
    until: Optional[str] = Form(None),
    camera_ids: Optional[str] = Form(None),   # comma-separated
    top_k: int = Form(20),
    user=Depends(require_permission("view_live")),
    db: AsyncSession = Depends(get_db),
):
    """Embed query photo + Qdrant cosine search + event-table join.

    `since` / `until` are ISO datetimes (URL-decoded). `camera_ids` is an
    optional CSV of camera_id values to scope the event join. Without a time
    window we still return Qdrant nearest persons (gallery hits with no
    matching events).
    """
    from app.ai.frs.enrollment import _load_bgr, _detect_largest_face, _crop_face, _embed, _HAS_CV
    from app.ai import qdrant_client

    if not _HAS_CV:
        raise HTTPException(503, "OpenCV not installed in backend")

    suffix = ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        bgr = _load_bgr(tmp_path)
        if bgr is None:
            raise HTTPException(415, "Cannot decode image")

        bbox = await _detect_largest_face(bgr)
        if bbox is None:
            raise HTTPException(422, "No face detected (or Triton offline)")

        crop = _crop_face(bgr, bbox)
        vec = await _embed(crop)
        if vec is None or vec.shape[-1] != 512:
            raise HTTPException(503, "Embedding service unavailable")

        try:
            hits = await qdrant_client.search(vec, top_k=top_k, score_threshold=0.40)
        except Exception as e:
            raise HTTPException(503, f"Qdrant search failed: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    person_ids = [h.get("person_id") for h in hits if h.get("person_id")]
    events_by_person: dict = {}
    if person_ids and (since or until or camera_ids):
        from app.events.models import Event
        from sqlalchemy import select, and_

        conditions = [Event.person_id.in_(person_ids)]
        if since:
            try:
                conditions.append(Event.triggered_at >= datetime.fromisoformat(since))
            except ValueError:
                pass
        if until:
            try:
                conditions.append(Event.triggered_at <= datetime.fromisoformat(until))
            except ValueError:
                pass
        if camera_ids:
            cams = [c.strip() for c in camera_ids.split(",") if c.strip()]
            if cams:
                conditions.append(Event.camera_id.in_(cams))

        ev_q = (
            select(Event)
            .where(and_(*conditions))
            .order_by(Event.triggered_at.desc())
            .limit(200)
        )
        for ev in (await db.execute(ev_q)).scalars().all():
            events_by_person.setdefault(ev.person_id, []).append(ev)

    results: List[InvestigationHit] = []
    for h in hits:
        pid = h.get("person_id")
        score = float(h.get("score", 0.0))
        photo_id = h.get("photo_id")
        evs = events_by_person.get(pid, [])
        if evs:
            for ev in evs:
                results.append(
                    InvestigationHit(
                        person_id=pid,
                        score=score,
                        photo_id=photo_id,
                        ts=ev.triggered_at.isoformat() if ev.triggered_at else None,
                        event_id=ev.id,
                        camera_id=ev.camera_id,
                        snapshot_path=ev.snapshot_path,
                    ),
                )
        else:
            results.append(
                InvestigationHit(person_id=pid, score=score, photo_id=photo_id),
            )

    return InvestigationResult(matches=len(results), results=results)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health")
async def frs_health(
    user=Depends(require_permission("view_live")),
):
    """Reports Triton + Qdrant readiness for the operator's status pill."""
    from app.ai import triton_client, qdrant_client
    return {
        "triton_server": await triton_client.is_ready(),
        "scrfd": await triton_client.is_ready("scrfd"),
        "arcface": await triton_client.is_ready("arcface"),
        "qdrant": await qdrant_client.health(),
    }
