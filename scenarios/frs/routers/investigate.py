"""Forensic investigate (search gallery by query face) + cross-camera tour."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select

from qdrant import store as qdrant_store
import recognition
from db import session
from deps import require_service_token
from db.models import FRSEvent, FRSPerson, InvestigationJob
from schemas import iso

router = APIRouter(tags=["investigate"])


@router.post("/investigate")
async def investigate(file: UploadFile = File(...), top_k: int = Form(50),
                      _: None = Depends(require_service_token)) -> JSONResponse:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    vector = recognition.query_embedding(data)
    hits = qdrant_store.search(vector, limit=top_k)
    out = []
    with session() as s:
        for h in hits:
            pid = h.get("person_id")
            person = s.get(FRSPerson, pid) if pid else None
            out.append({
                "person_id": pid,
                "person_name": person.full_name if person else h.get("person_name"),
                "photo_id": h.get("photo_id"),
                "score": round(float(h.get("score", 0.0)), 4),
                "snapshot_path": f"/photos/{h.get('photo_id')}/image" if h.get("photo_id") else None,
            })
        # Persist the job so results survive a restart and appear in history.
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
def tour_timeline(person_id: str, _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        rows = s.execute(
            select(FRSEvent).where(FRSEvent.person_id == person_id)
            .order_by(FRSEvent.triggered_at.desc()).limit(500)
        ).scalars().all()
        entries = [
            {"camera_id": e.camera_id, "triggered_at": iso(e.triggered_at),
             "confidence": e.confidence, "event_type": e.event_type,
             "snapshot_path": e.snapshot_path}
            for e in rows
        ]
    return {"person_id": person_id, "entries": entries, "total": len(entries)}
