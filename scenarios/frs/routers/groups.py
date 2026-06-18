"""Person-group CRUD."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select

from db import session
from deps import require_service_token
from db.models import FRSGroup, FRSPerson
from schemas import group_dict

router = APIRouter(tags=["groups"])


@router.get("/groups")
def list_groups(_: None = Depends(require_service_token)) -> list[dict]:
    with session() as s:
        rows = s.execute(
            select(FRSGroup, func.count(FRSPerson.id))
            .outerjoin(FRSPerson, FRSPerson.group_id == FRSGroup.id)
            .group_by(FRSGroup.id).order_by(FRSGroup.name)
        ).all()
        return [group_dict(g, int(c or 0)) for g, c in rows]


@router.post("/groups", status_code=201)
def create_group(body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    if not body.get("name"):
        raise HTTPException(400, "name required")
    with session() as s:
        g = FRSGroup(
            name=body["name"], group_type=body.get("group_type"),
            color_code=body.get("color_code"), description=body.get("description"),
            alert_sound=bool(body.get("alert_sound", False)),
        )
        s.add(g); s.commit(); s.refresh(g)
        return group_dict(g, 0)


@router.get("/groups/{group_id}")
def get_group(group_id: str, _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        g = s.get(FRSGroup, group_id)
        if not g:
            raise HTTPException(404, "group not found")
        cnt = s.scalar(select(func.count(FRSPerson.id)).where(FRSPerson.group_id == group_id)) or 0
        return group_dict(g, int(cnt))


@router.put("/groups/{group_id}")
def update_group(group_id: str, body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        g = s.get(FRSGroup, group_id)
        if not g:
            raise HTTPException(404, "group not found")
        for k in ("name", "group_type", "color_code", "description", "alert_sound"):
            if k in body and body[k] is not None:
                setattr(g, k, body[k])
        s.commit(); s.refresh(g)
        cnt = s.scalar(select(func.count(FRSPerson.id)).where(FRSPerson.group_id == group_id)) or 0
        return group_dict(g, int(cnt))


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: str, _: None = Depends(require_service_token)):
    with session() as s:
        g = s.get(FRSGroup, group_id)
        if not g:
            raise HTTPException(404, "group not found")
        for p in s.execute(select(FRSPerson).where(FRSPerson.group_id == group_id)).scalars():
            p.group_id = None
        s.delete(g); s.commit()
    return Response(status_code=204)
