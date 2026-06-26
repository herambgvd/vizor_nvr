"""Forensic investigate (search live sightings by query face) + cross-camera tour."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select

from qdrant import store as qdrant_store
import recognition
from db import session
from deps import require_service_token, allowed_camera_ids
from db.models import FRSEvent, FRSPerson, InvestigationJob
from schemas import iso

router = APIRouter(tags=["investigate"])


@router.post("/investigate")
async def investigate(file: UploadFile = File(...), top_k: int = Form(100),
                      min_score: float = Form(0.45), camera_ids: str = Form(""),
                      _: None = Depends(require_service_token),
                      allowed: Optional[list[str]] = Depends(allowed_camera_ids)) -> JSONResponse:
    """Forensic search (vizor-app parity): match the query face against the
    SNAPSHOTS collection — the time-series of captured live sightings — to answer
    "where/when was this face seen", NOT against the enrolled gallery.

    Camera scope (S1): the requested camera_ids are intersected with the
    operator's authorised cameras; the user can never search cameras they aren't
    assigned to."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    vector = recognition.query_embedding(data)
    if vector is None:
        raise HTTPException(422, "no usable face in query image (or engine unavailable)")
    requested = [c.strip() for c in (camera_ids or "").split(",") if c.strip()]
    if allowed is None:
        cam_filter = requested or None                      # no proxy scope (internal)
    else:
        cam_filter = [c for c in requested if c in set(allowed)] if requested else list(allowed)
        if not cam_filter:                                  # scoped to nothing
            return JSONResponse({"job_id": None, "hits": [], "total": 0})
    hits = qdrant_store.search(vector, limit=top_k,
                               collection=qdrant_store.SNAPSHOTS_COLLECTION,
                               camera_ids=cam_filter)
    out = []
    for h in hits:
        score = round(float(h.get("score", 0.0)), 4)
        if score < min_score:
            continue
        out.append({
            "event_id": h.get("event_id"),
            "person_id": h.get("person_id"),
            "person_name": h.get("person_name"),
            "camera_id": h.get("camera_id"),
            "event_type": h.get("event_type"),
            "similarity_score": score,
            "score": score,                       # back-compat alias for the UI
            "frame_timestamp": h.get("frame_timestamp"),
            "timestamp": h.get("frame_timestamp"),
            "snapshot_path": h.get("face_snapshot") or h.get("snapshot_path"),
            "liveness_score": h.get("liveness_score"),
            "age": h.get("age"), "age_range": h.get("age_range"),
            "gender": h.get("gender"), "gender_confidence": h.get("gender_confidence"),
        })
    out.sort(key=lambda r: r["similarity_score"], reverse=True)
    with session() as s:
        job = InvestigationJob(status="done", max_results=top_k,
                               result_count=len(out), results=out)
        s.add(job); s.commit(); s.refresh(job)
        job_id = job.id
    return JSONResponse({"job_id": job_id, "hits": out, "total": len(out)})


@router.get("/investigations")
def list_investigations(limit: int = 50, _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        rows = s.execute(select(InvestigationJob)
                         .order_by(InvestigationJob.created_at.desc()).limit(limit)).scalars().all()
        return {"items": [{"id": j.id, "name": j.name, "status": j.status,
                           "result_count": j.result_count, "created_at": iso(j.created_at)}
                          for j in rows]}


@router.get("/investigations/{job_id}")
def get_investigation(job_id: str, _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        j = s.get(InvestigationJob, job_id)
        if not j:
            raise HTTPException(404, "investigation not found")
        return {"id": j.id, "name": j.name, "status": j.status, "result_count": j.result_count,
                "results": j.results or [], "error": j.error, "created_at": iso(j.created_at)}


@router.get("/tour/timeline/{person_id}")
def tour_timeline(person_id: str, _: None = Depends(require_service_token),
                  allowed: Optional[list[str]] = Depends(allowed_camera_ids)) -> dict:
    with session() as s:
        conds = [FRSEvent.person_id == person_id]
        # Camera scope (S1): only sightings on cameras the operator may read.
        if allowed is not None:
            if not allowed:
                return {"person_id": person_id, "entries": [], "total": 0}
            conds.append(FRSEvent.camera_id.in_(allowed))
        rows = s.execute(
            select(FRSEvent).where(*conds)
            .order_by(FRSEvent.triggered_at.desc()).limit(500)
        ).scalars().all()
        entries = [
            {"camera_id": e.camera_id, "triggered_at": iso(e.triggered_at),
             "confidence": e.confidence, "event_type": e.event_type,
             "snapshot_path": e.snapshot_path}
            for e in rows
        ]
    return {"person_id": person_id, "entries": entries, "total": len(entries)}
