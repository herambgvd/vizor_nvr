# =============================================================================
# Event Service — CRUD + event ingestion + stats
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.models import Event, EventLinkageRule

logger = logging.getLogger(__name__)


class EventService:
    """Service for creating, querying, and managing events."""

    # ------------------------------------------------------------------
    # Event CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def create_event(db: AsyncSession, data) -> Event:
        event = Event(
            camera_id=data.camera_id,
            event_type=data.event_type,
            severity=data.severity,
            title=data.title,
            description=data.description,
            event_metadata=data.metadata,
            snapshot_path=data.snapshot_path,
            recording_id=data.recording_id,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event

    @staticmethod
    async def create_event_direct(
        db: AsyncSession,
        camera_id: Optional[str],
        event_type: str,
        severity: str,
        title: str,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        snapshot_path: Optional[str] = None,
        recording_id: Optional[str] = None,
    ) -> Event:
        """Create an event directly (from internal services)."""
        event = Event(
            camera_id=camera_id,
            event_type=event_type,
            severity=severity,
            title=title,
            description=description,
            event_metadata=metadata,
            snapshot_path=snapshot_path,
            recording_id=recording_id,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event

    @staticmethod
    async def get_event(db: AsyncSession, event_id: str) -> Optional[Event]:
        result = await db.execute(select(Event).where(Event.id == event_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def list_events(
        db: AsyncSession,
        camera_id: Optional[str] = None,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        acknowledged: Optional[bool] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[Event], int]:
        """List events with filters. Returns (events, total_count)."""
        query = select(Event)
        count_query = select(func.count(Event.id))
        conditions = []

        if camera_id:
            conditions.append(Event.camera_id == camera_id)
        if event_type:
            conditions.append(Event.event_type == event_type)
        if severity:
            conditions.append(Event.severity == severity)
        if acknowledged is not None:
            conditions.append(Event.acknowledged == acknowledged)
        if start_date:
            conditions.append(Event.triggered_at >= start_date)
        if end_date:
            conditions.append(Event.triggered_at <= end_date)

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(desc(Event.triggered_at)).offset(offset).limit(limit)
        result = await db.execute(query)
        events = list(result.scalars().all())

        return events, total

    @staticmethod
    async def acknowledge_event(
        db: AsyncSession,
        event_id: str,
        user_id: str,
        note: Optional[str] = None,
    ) -> Optional[Event]:
        event = await EventService.get_event(db, event_id)
        if not event:
            return None
        event.acknowledged = True
        event.acknowledged_by = user_id
        event.acknowledged_at = datetime.utcnow()
        if note is not None:
            event.note = note
        await db.commit()
        await db.refresh(event)
        return event

    @staticmethod
    async def mark_false_alarm(
        db: AsyncSession,
        event_id: str,
        note: Optional[str] = None,
    ) -> Optional[Event]:
        event = await EventService.get_event(db, event_id)
        if not event:
            return None
        event.is_false_alarm = True
        event.acknowledged = True
        event.acknowledged_at = datetime.utcnow()
        if note is not None:
            event.note = note
        await db.commit()
        await db.refresh(event)
        return event

    @staticmethod
    async def acknowledge_all(
        db: AsyncSession,
        user_id: str,
        camera_id: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> int:
        """Acknowledge all unacknowledged events matching filters. Returns count."""
        from sqlalchemy import update
        stmt = (
            update(Event)
            .where(Event.acknowledged == False)
        )
        if camera_id:
            stmt = stmt.where(Event.camera_id == camera_id)
        if event_type:
            stmt = stmt.where(Event.event_type == event_type)

        stmt = stmt.values(
            acknowledged=True,
            acknowledged_by=user_id,
            acknowledged_at=datetime.utcnow(),
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount

    @staticmethod
    async def get_unacknowledged_count(
        db: AsyncSession,
        camera_id: Optional[str] = None,
    ) -> int:
        query = select(func.count(Event.id)).where(Event.acknowledged == False)
        if camera_id:
            query = query.where(Event.camera_id == camera_id)
        result = await db.execute(query)
        return result.scalar() or 0

    @staticmethod
    async def get_event_stats(db: AsyncSession) -> dict:
        """Get event counts by type and severity."""
        # By type
        type_result = await db.execute(
            select(Event.event_type, func.count(Event.id))
            .group_by(Event.event_type)
        )
        by_type = {row[0]: row[1] for row in type_result.fetchall()}

        # By severity
        sev_result = await db.execute(
            select(Event.severity, func.count(Event.id))
            .group_by(Event.severity)
        )
        by_severity = {row[0]: row[1] for row in sev_result.fetchall()}

        # Unacknowledged
        unack = await EventService.get_unacknowledged_count(db)

        return {
            "by_type": by_type,
            "by_severity": by_severity,
            "unacknowledged": unack,
        }

    # ------------------------------------------------------------------
    # Linkage Rule CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def create_rule(db: AsyncSession, data, user_id: Optional[str] = None) -> EventLinkageRule:
        actions_data = [a.model_dump() for a in data.actions] if data.actions else []
        rule = EventLinkageRule(
            name=data.name,
            description=data.description,
            trigger_type=data.trigger_type,
            trigger_config=data.trigger_config,
            actions=actions_data,
            camera_ids=data.camera_ids,
            enabled=data.enabled,
            schedule=data.schedule,
            cooldown_seconds=data.cooldown_seconds,
            created_by=user_id,
        )
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
        return rule

    @staticmethod
    async def get_rule(db: AsyncSession, rule_id: str) -> Optional[EventLinkageRule]:
        result = await db.execute(
            select(EventLinkageRule).where(EventLinkageRule.id == rule_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_rules(db: AsyncSession) -> List[EventLinkageRule]:
        result = await db.execute(
            select(EventLinkageRule).order_by(EventLinkageRule.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def update_rule(
        db: AsyncSession, rule_id: str, data
    ) -> Optional[EventLinkageRule]:
        rule = await EventService.get_rule(db, rule_id)
        if not rule:
            return None
        update_data = data.model_dump(exclude_unset=True)
        if "actions" in update_data and update_data["actions"] is not None:
            update_data["actions"] = [
                a.model_dump() if hasattr(a, "model_dump") else a
                for a in data.actions
            ]
        for k, v in update_data.items():
            setattr(rule, k, v)
        await db.commit()
        await db.refresh(rule)
        return rule

    @staticmethod
    async def delete_rule(db: AsyncSession, rule_id: str) -> bool:
        rule = await EventService.get_rule(db, rule_id)
        if not rule:
            return False
        await db.delete(rule)
        await db.commit()
        return True

    @staticmethod
    async def get_active_rules_for_trigger(
        db: AsyncSession, trigger_type: str, camera_id: Optional[str] = None,
    ) -> List[EventLinkageRule]:
        """Get all enabled rules matching a trigger type, optionally scoped to a camera."""
        result = await db.execute(
            select(EventLinkageRule).where(
                EventLinkageRule.enabled == True,
                EventLinkageRule.trigger_type == trigger_type,
            )
        )
        rules = list(result.scalars().all())
        if camera_id:
            rules = [
                r for r in rules
                if r.camera_ids is None or camera_id in r.camera_ids
            ]
        return rules
