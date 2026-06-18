"""Transit rules + sessions (plugin-owned)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select

from db import session
from deps import require_service_token
from db.models import TransitRule, TransitSession
from schemas import iso, naive, parse_dt

router = APIRouter(tags=["transit"])


@router.post("/transit/rules")
def create_transit_rule(body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        r = TransitRule(name=body.get("name") or "rule", config=body.get("config") or body,
                        enabled=bool(body.get("enabled", True)))
        s.add(r); s.commit(); s.refresh(r)
        return {"id": r.id, "name": r.name, "config": r.config, "enabled": r.enabled}


@router.get("/transit/rules")
def list_transit_rules(_: None = Depends(require_service_token)) -> dict:
    with session() as s:
        rows = s.execute(select(TransitRule).order_by(TransitRule.created_at.desc())).scalars().all()
        return {"rules": [{"id": r.id, "name": r.name, "config": r.config, "enabled": r.enabled} for r in rows]}


@router.put("/transit/rules/{rule_id}")
def update_transit_rule(rule_id: str, body: dict = Body(...), _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        r = s.get(TransitRule, rule_id)
        if not r:
            raise HTTPException(404, "rule not found")
        if "name" in body:
            r.name = body["name"]
        if "config" in body:
            r.config = body["config"]
        if "enabled" in body:
            r.enabled = bool(body["enabled"])
        s.commit(); s.refresh(r)
        return {"id": r.id, "name": r.name, "config": r.config, "enabled": r.enabled}


@router.delete("/transit/rules/{rule_id}")
def delete_transit_rule(rule_id: str, _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        r = s.get(TransitRule, rule_id)
        if not r:
            raise HTTPException(404, "rule not found")
        s.delete(r); s.commit()
    return {"ok": True, "id": rule_id}


@router.get("/transit/sessions")
def list_transit_sessions(status: Optional[str] = None, since: Optional[str] = None,
                          until: Optional[str] = None, limit: int = 100, offset: int = 0,
                          _: None = Depends(require_service_token)) -> dict:
    with session() as s:
        q = select(TransitSession)
        if status:
            q = q.where(TransitSession.status == status)
        if since:
            q = q.where(TransitSession.started_at >= naive(parse_dt(since)))
        if until:
            q = q.where(TransitSession.started_at <= naive(parse_dt(until)))
        total = int(s.scalar(select(func.count()).select_from(q.subquery())) or 0)
        rows = s.execute(q.order_by(TransitSession.created_at.desc()).limit(limit).offset(offset)).scalars().all()
        sessions = [{"id": x.id, "rule_id": x.rule_id, "person_id": x.person_id,
                     "status": x.status, "started_at": iso(x.started_at),
                     "ended_at": iso(x.ended_at), "attributes": x.attributes} for x in rows]
    return {"sessions": sessions, "total": total}
