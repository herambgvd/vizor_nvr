"""Person CRUD (gallery)."""
from __future__ import annotations

import os
import shutil
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, or_, select

from qdrant import store as qdrant_store
from config import DATA_PATH
from db import session
from deps import require_service_token
from db.models import FRSPerson, FRSGroup, FRSPhoto
from schemas import person_dict

router = APIRouter(tags=["persons"])


@router.get("/persons")
def list_persons(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                 search: Optional[str] = None, group_id: Optional[str] = None,
                 category: Optional[str] = None, _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        conds = []
        if search:
            like = f"%{search.strip()}%"
            conds.append(or_(FRSPerson.full_name.ilike(like), FRSPerson.external_id.ilike(like)))
        if group_id:
            conds.append(FRSPerson.group_id == group_id)
        if category:
            conds.append(FRSPerson.category == category)
        cq = select(func.count(FRSPerson.id))
        rq = select(FRSPerson)
        for c in conds:
            cq = cq.where(c); rq = rq.where(c)
        total = int(s.scalar(cq) or 0)
        rows = s.execute(rq.order_by(FRSPerson.created_at.desc()).limit(limit).offset(offset)).scalars().all()
        return {"items": [person_dict(p) for p in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/persons", status_code=201)
def create_person(body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    if not body.get("full_name"):
        raise HTTPException(400, "full_name required")
    with session() as s:
        if body.get("group_id") and not s.get(FRSGroup, body["group_id"]):
            raise HTTPException(400, "group not found")
        p = FRSPerson(
            full_name=body["full_name"], external_id=body.get("external_id"),
            group_id=body.get("group_id"), category=body.get("category") or "standard",
            priority=int(body.get("priority") or 0), attributes=body.get("attributes"),
        )
        s.add(p); s.commit(); s.refresh(p)
        return person_dict(p)


@router.get("/persons/{person_id}")
def get_person(person_id: str, _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        p = s.get(FRSPerson, person_id)
        if not p:
            raise HTTPException(404, "person not found")
        return person_dict(p)


@router.put("/persons/{person_id}")
def update_person(person_id: str, body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        p = s.get(FRSPerson, person_id)
        if not p:
            raise HTTPException(404, "person not found")
        if body.get("group_id") and not s.get(FRSGroup, body["group_id"]):
            raise HTTPException(400, "group not found")
        for k in ("full_name", "external_id", "group_id", "category", "priority", "attributes"):
            if k in body:
                setattr(p, k, body[k])
        s.commit(); s.refresh(p)
        return person_dict(p)


@router.delete("/persons/{person_id}", status_code=204)
def delete_person(person_id: str, _: None = Depends(require_service_token)):
    with session() as s:
        p = s.get(FRSPerson, person_id)
        if not p:
            raise HTTPException(404, "person not found")
        for ph in s.execute(select(FRSPhoto).where(FRSPhoto.person_id == person_id)).scalars().all():
            s.delete(ph)
        s.delete(p); s.commit()
    # Remove all face vectors for this person (main + augment points).
    qdrant_store.delete_by("person_id", person_id)
    photo_dir = DATA_PATH / "persons" / person_id
    if photo_dir.exists():
        shutil.rmtree(photo_dir, ignore_errors=True)
    return Response(status_code=204)
