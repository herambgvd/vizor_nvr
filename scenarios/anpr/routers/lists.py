"""Whitelist / blacklist management — PER-SCENARIO GLOBAL list.

GET    /lists           — paginated list (filter by list_type / plate).
POST   /lists           — add one entry.
DELETE /lists/{id}      — remove one entry.
POST   /lists/import    — CSV bulk import (columns: plate,list_type,label,
                          valid_from,valid_to; header optional).
Service-token gated. Not camera-scoped — the list is global to the ANPR scenario.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import and_, func, select

from db import session
from db.list_store import normalize_plate
from db.models import ANPRPlateList
from deps import require_service_token
from schemas import list_dict, parse_dt

router = APIRouter(tags=["lists"], dependencies=[Depends(require_service_token)])

_VALID_TYPES = {"whitelist", "blacklist"}


@router.get("/lists")
def list_entries(
    list_type: Optional[str] = None,
    plate: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    with session() as s:
        conds = []
        if list_type:
            conds.append(ANPRPlateList.list_type == list_type)
        if plate:
            conds.append(ANPRPlateList.plate.ilike(f"%{normalize_plate(plate)}%"))
        where = and_(*conds) if conds else None
        cq = select(func.count()).select_from(ANPRPlateList)
        rq = select(ANPRPlateList)
        if where is not None:
            cq = cq.where(where)
            rq = rq.where(where)
        total = int(s.scalar(cq) or 0)
        rows = s.execute(
            rq.order_by(ANPRPlateList.created_at.desc()).limit(limit).offset(offset)
        ).scalars().all()
        return {"items": [list_dict(e) for e in rows], "total": total,
                "limit": limit, "offset": offset}


@router.post("/lists", status_code=201)
def add_entry(body: dict = Body(...)) -> dict:
    plate = normalize_plate(str(body.get("plate") or ""))
    if not plate:
        raise HTTPException(400, "plate is required")
    list_type = str(body.get("list_type") or "blacklist").lower()
    if list_type not in _VALID_TYPES:
        raise HTTPException(400, "list_type must be whitelist or blacklist")
    with session() as s:
        entry = ANPRPlateList(
            plate=plate,
            list_type=list_type,
            label=(str(body["label"]) if body.get("label") else None),
            valid_from=parse_dt(body.get("valid_from")),
            valid_to=parse_dt(body.get("valid_to")),
        )
        s.add(entry)
        s.commit()
        s.refresh(entry)
        return list_dict(entry)


@router.delete("/lists/{entry_id}", status_code=204)
def delete_entry(entry_id: str):
    with session() as s:
        entry = s.get(ANPRPlateList, entry_id)
        if not entry:
            raise HTTPException(404, "list entry not found")
        s.delete(entry)
        s.commit()
    return Response(status_code=204)


@router.post("/lists/import")
async def import_csv(
    file: Optional[UploadFile] = None,
    list_type: str = Query("blacklist"),
    body: Optional[str] = Body(None),
) -> dict:
    """Bulk import from a CSV upload (multipart `file`) or a raw CSV string body.

    Columns (header optional, case-insensitive): plate, list_type, label,
    valid_from, valid_to. A row's list_type overrides the query default; rows
    missing a type fall back to the `list_type` query parameter."""
    if file is not None:
        raw = (await file.read()).decode("utf-8", errors="replace")
    elif body:
        raw = body
    else:
        raise HTTPException(400, "provide a CSV file upload or a raw CSV body")

    default_type = list_type.lower() if list_type.lower() in _VALID_TYPES else "blacklist"
    reader = csv.reader(io.StringIO(raw))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        return {"imported": 0, "skipped": 0}

    # Detect + skip a header row (first cell == "plate", case-insensitive).
    start = 1 if rows and rows[0] and rows[0][0].strip().lower() == "plate" else 0
    imported = skipped = 0
    with session() as s:
        for r in rows[start:]:
            plate = normalize_plate(r[0] if len(r) > 0 else "")
            if not plate:
                skipped += 1
                continue
            row_type = (r[1].strip().lower() if len(r) > 1 and r[1].strip() else default_type)
            if row_type not in _VALID_TYPES:
                row_type = default_type
            label = r[2].strip() if len(r) > 2 and r[2].strip() else None
            vf = parse_dt(r[3]) if len(r) > 3 and r[3].strip() else None
            vt = parse_dt(r[4]) if len(r) > 4 and r[4].strip() else None
            s.add(ANPRPlateList(plate=plate, list_type=row_type, label=label,
                                valid_from=vf, valid_to=vt))
            imported += 1
        s.commit()
    return {"imported": imported, "skipped": skipped}
