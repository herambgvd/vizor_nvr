"""User-defined plate lists management — PER-SCENARIO GLOBAL.

List definitions (categories, each with an action alert/allow/log):
  GET    /lists/defs        — all list definitions (with entry counts).
  POST   /lists/defs        — create a list (name, action, color, description).
  PUT    /lists/defs/{id}   — update a list.
  DELETE /lists/defs/{id}   — delete a list (cascade-deletes its entries).

Plate entries (each belongs to a list_id):
  GET    /lists             — paginated entries (filter by list_id / plate).
  POST   /lists             — add one entry (needs list_id).
  DELETE /lists/{id}        — remove one entry.
  POST   /lists/import      — CSV bulk import into a target list (list_id or name).

Service-token gated. Not camera-scoped — the lists are global to the ANPR
scenario.
"""
from __future__ import annotations

import csv
import io
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import and_, func, select

from db import session
from db.list_store import (
    create_list_def,
    delete_list_def,
    find_list_def_by_name,
    get_list_def,
    list_defs,
    normalize_plate,
    update_list_def,
)
from db.models import ANPRListDef, ANPRPlateList
from deps import require_service_token
from schemas import list_def_dict, list_dict, parse_dt

router = APIRouter(tags=["lists"], dependencies=[Depends(require_service_token)])


# ── list definitions (categories) ────────────────────────────────────────────
@router.get("/lists/defs")
def list_definitions() -> dict:
    items = list_defs()
    return {"items": items, "total": len(items)}


@router.post("/lists/defs", status_code=201)
def create_definition(body: dict = Body(...)) -> dict:
    try:
        return create_list_def(
            name=str(body.get("name") or ""),
            action=str(body.get("action") or "alert"),
            color=(str(body["color"]) if body.get("color") else None),
            description=(str(body["description"]) if body.get("description") else None),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.put("/lists/defs/{list_id}")
def update_definition(list_id: str, body: dict = Body(...)) -> dict:
    try:
        updated = update_list_def(
            list_id,
            name=(str(body["name"]) if "name" in body else None),
            action=(str(body["action"]) if "action" in body else None),
            color=(str(body["color"]) if "color" in body else None),
            description=(str(body["description"]) if "description" in body else None),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if updated is None:
        raise HTTPException(404, "list not found")
    return updated


@router.delete("/lists/defs/{list_id}")
def delete_definition(list_id: str) -> dict:
    result = delete_list_def(list_id)
    if result is None:
        raise HTTPException(404, "list not found")
    return result


# ── plate entries ────────────────────────────────────────────────────────────
@router.get("/lists")
def list_entries(
    list_id: Optional[str] = None,
    plate: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    with session() as s:
        conds = []
        if list_id:
            conds.append(ANPRPlateList.list_id == list_id)
        if plate:
            conds.append(ANPRPlateList.plate.ilike(f"%{normalize_plate(plate)}%"))
        where = and_(*conds) if conds else None
        cq = select(func.count()).select_from(ANPRPlateList)
        rq = (select(ANPRPlateList, ANPRListDef)
              .join(ANPRListDef, ANPRPlateList.list_id == ANPRListDef.id))
        if where is not None:
            cq = cq.where(where)
            rq = rq.where(where)
        total = int(s.scalar(cq) or 0)
        rows = s.execute(
            rq.order_by(ANPRPlateList.created_at.desc()).limit(limit).offset(offset)
        ).all()
        return {"items": [list_dict(e, d) for e, d in rows], "total": total,
                "limit": limit, "offset": offset}


@router.post("/lists", status_code=201)
def add_entry(body: dict = Body(...)) -> dict:
    plate = normalize_plate(str(body.get("plate") or ""))
    if not plate:
        raise HTTPException(400, "plate is required")
    list_id = str(body.get("list_id") or "").strip()
    if not list_id:
        raise HTTPException(400, "list_id is required")
    with session() as s:
        ldef = s.get(ANPRListDef, list_id)
        if not ldef:
            raise HTTPException(400, "unknown list_id")
        entry = ANPRPlateList(
            plate=plate,
            list_id=list_id,
            label=(str(body["label"]) if body.get("label") else None),
            valid_from=parse_dt(body.get("valid_from")),
            valid_to=parse_dt(body.get("valid_to")),
        )
        s.add(entry)
        s.commit()
        s.refresh(entry)
        return list_dict(entry, ldef)


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
    list_id: Optional[str] = Query(None),
    list_name: Optional[str] = Query(None),
    body: Optional[str] = Body(None),
) -> dict:
    """Bulk import plate entries into a TARGET list from a CSV upload (multipart
    `file`) or a raw CSV string body.

    Columns (header optional, case-insensitive): plate, label, valid_from,
    valid_to. Every row imports into the target list resolved from the `list_id`
    query (preferred) or, failing that, a `list_name` query."""
    if file is not None:
        raw = (await file.read()).decode("utf-8", errors="replace")
    elif body:
        raw = body
    else:
        raise HTTPException(400, "provide a CSV file upload or a raw CSV body")

    # Resolve the target list.
    target = get_list_def(list_id) if list_id else None
    if target is None and list_name:
        target = find_list_def_by_name(list_name)
    if target is None:
        raise HTTPException(400, "a valid target list_id (or list_name) is required")
    target_id = target["id"]

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
            label = r[1].strip() if len(r) > 1 and r[1].strip() else None
            vf = parse_dt(r[2]) if len(r) > 2 and r[2].strip() else None
            vt = parse_dt(r[3]) if len(r) > 3 and r[3].strip() else None
            s.add(ANPRPlateList(plate=plate, list_id=target_id, label=label,
                                valid_from=vf, valid_to=vt))
            imported += 1
        s.commit()
    return {"imported": imported, "skipped": skipped}
