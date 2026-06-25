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


@router.delete("/transit/sessions/{session_id}")
def delete_transit_session(session_id: str, _: None = Depends(require_service_token)) -> dict:
    """Delete one transit session. The NVR backend has already re-verified the
    operator's platform password before proxying this (destructive action)."""
    with session() as s:
        sess = s.get(TransitSession, session_id)
        if not sess:
            raise HTTPException(404, "session not found")
        s.delete(sess); s.commit()
    return {"ok": True, "id": session_id}


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

        # Resolve names: prefer the name stored on the session at sighting time;
        # fall back to a lookup in the persons table (covers older sessions that
        # only stored a person_id, so the UI never has to show "Person <id>").
        rule_names = {r.id: r.name for r in s.execute(select(TransitRule)).scalars()}
        from db.models import FRSPerson
        need = {x.person_id for x in rows
                if x.person_id and not (x.attributes or {}).get("person_name")}
        name_by_id = {}
        if need:
            for p in s.execute(select(FRSPerson).where(FRSPerson.id.in_(need))).scalars():
                name_by_id[p.id] = p.full_name

        sessions = []
        for x in rows:
            attrs = x.attributes or {}
            sessions.append({
                "id": x.id, "rule_id": x.rule_id, "rule_name": rule_names.get(x.rule_id),
                "person_id": x.person_id,
                "person_name": attrs.get("person_name") or name_by_id.get(x.person_id),
                "status": x.status, "started_at": iso(x.started_at),
                "ended_at": iso(x.ended_at),
                "entry_camera": attrs.get("entry_camera"),
                "exit_camera": attrs.get("exit_camera"),
                "entry_snapshot": attrs.get("entry_snapshot"),
                "exit_snapshot": attrs.get("exit_snapshot"),
                "deadline": attrs.get("deadline"),
                "duration_seconds": attrs.get("duration_seconds"),
                "attributes": attrs,
            })
    return {"sessions": sessions, "total": total}
