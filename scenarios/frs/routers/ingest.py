"""Third-party FRS event ingest.

External systems (a brand CCTV/NVR that already does its own face recognition)
POST a face-match here; we resolve the person in our gallery (by external_id or
name), record it as a normal FRSEvent via the shared record_event() path, and
tag attributes.source so it's distinguishable from live in-platform recognition.
Because Transit / Tour / Investigate / Attendance all read frs_events, an ingested
event flows into those features with no extra wiring.

Auth: the ingest API key (FRS settings). The NVR proxy gates the route on the
service token AND the API key; the plugin re-verifies the key (single source of
truth = plugin settings) as defense-in-depth.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

import config
from db import session
from db.events import record_event
from db.models import FRSPerson
from db.settings_store import verify_ingest_key
from schemas import utcnow

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestEvent(BaseModel):
    camera_id: str = Field(..., description="External camera/source id")
    camera_name: Optional[str] = None
    person_external_id: Optional[str] = Field(None, description="Resolve gallery person by external_id")
    person_name: Optional[str] = Field(None, description="Fallback resolve by name; also the displayed label")
    event_type: str = Field("face_recognized", description="face_recognized | face_unknown | face_detected")
    confidence: Optional[float] = None
    timestamp: Optional[datetime] = Field(None, description="ISO-8601; defaults to now")
    bbox: Optional[dict] = None
    attributes: Optional[dict] = None
    source: Optional[str] = Field(None, description="Free label for the originating system, e.g. 'hikvision'")
    snapshot_base64: Optional[str] = Field(
        None, description="Event image as base64 JPEG/PNG (or a data URL). Stored + served as the event snapshot.")


def _resolve_person(ext_id: Optional[str], name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Return (person_id, display_name). Match by external_id first, then exact
    name. Unmatched -> (None, name) so it records as an unknown sighting."""
    if not ext_id and not name:
        return None, None
    with session() as s:
        conds = []
        if ext_id:
            conds.append(FRSPerson.external_id == ext_id)
        if name:
            conds.append(FRSPerson.full_name == name)
        row = s.scalar(select(FRSPerson).where(or_(*conds))) if conds else None
        if row:
            return row.id, row.full_name
    return None, name


@router.post("/event")
def ingest_event(
    body: IngestEvent,
    x_frs_ingest_key: Optional[str] = Header(None),
) -> dict:
    """Ingest one third-party face event -> FRSEvent (+ attendance)."""
    if not verify_ingest_key(x_frs_ingest_key):
        raise HTTPException(401, "invalid or disabled ingest key")

    person_id, display_name = _resolve_person(body.person_external_id, body.person_name)
    ts = body.timestamp or utcnow()

    # Tag the source so operators can tell ingested events from live ones, and
    # keep any extra attributes the caller sent.
    attrs = dict(body.attributes or {})
    attrs["source"] = f"external:{body.source or body.camera_name or body.camera_id}"
    if body.camera_name:
        attrs.setdefault("camera_name", body.camera_name)

    # Persist the event image (base64 -> /snapshot?key=ingest:<id>). Best-effort.
    from vizor_sdk import save_ingest_snapshot
    snapshot_path = save_ingest_snapshot(body.snapshot_base64, config.DATA_PATH)

    event_id = record_event(
        camera_id=body.camera_id,
        person_id=person_id,
        person_name=display_name,
        confidence=body.confidence,
        snapshot_path=snapshot_path,
        event_type=body.event_type,
        ts=ts,
        bbox=body.bbox,
        attributes=attrs,
    )
    return {
        "ok": True,
        "event_id": event_id,
        "matched": person_id is not None,
        "person_id": person_id,
    }
