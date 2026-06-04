# =============================================================================
# Events Router — event CRUD, acknowledge, linkage rules, CSV export
# =============================================================================

import csv
import io
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import get_current_user, require_permission
from app.events.models import (
    EventCreate,
    EventResponse,
    EventAcknowledge,
    EventMarkFalseAlarm,
    EventBulkDelete,
    LinkageRuleCreate,
    LinkageRuleUpdate,
    LinkageRuleResponse,
)
from app.events.service import EventService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


# =============================================================================
# Events
# =============================================================================

@router.get("", response_model=dict)
async def list_events(
    camera_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    acknowledged: Optional[bool] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    source_service: Optional[str] = Query(None),
    detection_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_permission("view_cameras")),
    db: AsyncSession = Depends(get_db),
):
    """List events with filters."""
    events, total = await EventService.list_events(
        db,
        camera_id=camera_id,
        event_type=event_type,
        severity=severity,
        acknowledged=acknowledged,
        start_date=start_date,
        end_date=end_date,
        source_service=source_service,
        detection_type=detection_type,
        limit=limit,
        offset=offset,
    )
    return {
        "events": [EventResponse.model_validate(e) for e in events],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/stats")
async def event_stats(
    user: dict = Depends(require_permission("view_cameras")),
    db: AsyncSession = Depends(get_db),
):
    """Get event statistics."""
    return await EventService.get_event_stats(db)


@router.get("/unacknowledged-count")
async def unacknowledged_count(
    camera_id: Optional[str] = Query(None),
    user: dict = Depends(require_permission("view_cameras")),
    db: AsyncSession = Depends(get_db),
):
    """Get count of unacknowledged events."""
    count = await EventService.get_unacknowledged_count(db, camera_id)
    return {"count": count}


@router.get("/export/csv")
async def export_events_csv(
    camera_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    user: dict = Depends(require_permission("view_cameras")),
    db: AsyncSession = Depends(get_db),
):
    """Export events as CSV."""
    events, _ = await EventService.list_events(
        db,
        camera_id=camera_id,
        event_type=event_type,
        severity=severity,
        start_date=start_date,
        end_date=end_date,
        limit=10000,
        offset=0,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Camera ID", "Event Type", "Severity", "Title",
        "Description", "Acknowledged", "False Alarm", "Triggered At",
    ])
    for e in events:
        writer.writerow([
            e.id, e.camera_id, e.event_type, e.severity, e.title,
            e.description or "", e.acknowledged, e.is_false_alarm,
            e.triggered_at.isoformat() if e.triggered_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=events.csv"},
    )


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    user: dict = Depends(require_permission("view_cameras")),
    db: AsyncSession = Depends(get_db),
):
    """Get a single event."""
    event = await EventService.get_event(db, event_id)
    if not event:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return EventResponse.model_validate(event)


@router.post("/{event_id}/acknowledge", response_model=EventResponse)
async def acknowledge_event(
    event_id: str,
    body: EventAcknowledge,
    user: dict = Depends(require_permission("view_cameras")),
    db: AsyncSession = Depends(get_db),
):
    """Acknowledge an event."""
    event = await EventService.acknowledge_event(db, event_id, user["id"], body.note)
    if not event:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return EventResponse.model_validate(event)


@router.post("/acknowledge-all")
async def acknowledge_all_events(
    camera_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    user: dict = Depends(require_permission("view_cameras")),
    db: AsyncSession = Depends(get_db),
):
    """Acknowledge all matching unacknowledged events."""
    count = await EventService.acknowledge_all(db, user["id"], camera_id, event_type)
    return {"acknowledged": count}


@router.delete("/bulk", status_code=200)
async def bulk_delete_events(
    body: EventBulkDelete,
    user: dict = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-delete events. Pass `event_ids` for explicit selection, OR any
    of camera_id / event_type / severity / acknowledged / before for
    filter-based deletion. Refuses unfiltered wipes."""
    count = await EventService.delete_events_bulk(
        db,
        event_ids=body.event_ids,
        camera_id=body.camera_id,
        event_type=body.event_type,
        severity=body.severity,
        acknowledged=body.acknowledged,
        before=body.before,
    )
    return {"deleted": count}


@router.delete("/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    user: dict = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single event by id."""
    ok = await EventService.delete_event(db, event_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return None


@router.post("/{event_id}/false-alarm", response_model=EventResponse)
async def mark_false_alarm(
    event_id: str,
    body: EventMarkFalseAlarm,
    user: dict = Depends(require_permission("view_cameras")),
    db: AsyncSession = Depends(get_db),
):
    """Mark an event as a false alarm."""
    event = await EventService.mark_false_alarm(db, event_id, body.note)
    if not event:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return EventResponse.model_validate(event)


# =============================================================================
# Linkage Rules
# =============================================================================

@router.get("/rules/list", response_model=list[LinkageRuleResponse])
async def list_rules(
    user: dict = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """List all event linkage rules."""
    rules = await EventService.list_rules(db)
    return [LinkageRuleResponse.model_validate(r) for r in rules]


@router.post("/rules", response_model=LinkageRuleResponse, status_code=201)
async def create_rule(
    data: LinkageRuleCreate,
    user: dict = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new event linkage rule."""
    rule = await EventService.create_rule(db, data, user["id"])
    return LinkageRuleResponse.model_validate(rule)


@router.get("/rules/{rule_id}", response_model=LinkageRuleResponse)
async def get_rule(
    rule_id: str,
    user: dict = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Get a linkage rule."""
    rule = await EventService.get_rule(db, rule_id)
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    return LinkageRuleResponse.model_validate(rule)


@router.patch("/rules/{rule_id}", response_model=LinkageRuleResponse)
async def update_rule(
    rule_id: str,
    data: LinkageRuleUpdate,
    user: dict = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Update a linkage rule."""
    rule = await EventService.update_rule(db, rule_id, data)
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    return LinkageRuleResponse.model_validate(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    user: dict = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a linkage rule."""
    deleted = await EventService.delete_rule(db, rule_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
