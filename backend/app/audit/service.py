# =============================================================================
# Audit Service — query, export
# =============================================================================

import math
from typing import Optional, List
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog


class AuditService:

    @staticmethod
    async def query(
        db: AsyncSession,
        action: Optional[str] = None,
        user_id: Optional[str] = None,
        severity: Optional[str] = None,
        resource_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        search: Optional[str] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> dict:
        q = select(AuditLog)
        count_q = select(func.count(AuditLog.id))

        if action:
            q = q.where(AuditLog.action == action)
            count_q = count_q.where(AuditLog.action == action)
        if user_id:
            q = q.where(AuditLog.user_id == user_id)
            count_q = count_q.where(AuditLog.user_id == user_id)
        if severity:
            q = q.where(AuditLog.severity == severity)
            count_q = count_q.where(AuditLog.severity == severity)
        if resource_type:
            q = q.where(AuditLog.resource_type == resource_type)
            count_q = count_q.where(AuditLog.resource_type == resource_type)
        if start_time:
            q = q.where(AuditLog.created_at >= start_time)
            count_q = count_q.where(AuditLog.created_at >= start_time)
        if end_time:
            q = q.where(AuditLog.created_at <= end_time)
            count_q = count_q.where(AuditLog.created_at <= end_time)
        if search:
            pattern = f"%{search}%"
            q = q.where(
                AuditLog.description.ilike(pattern)
                | AuditLog.username.ilike(pattern)
                | AuditLog.action.ilike(pattern)
            )
            count_q = count_q.where(
                AuditLog.description.ilike(pattern)
                | AuditLog.username.ilike(pattern)
                | AuditLog.action.ilike(pattern)
            )

        total = (await db.execute(count_q)).scalar()
        q = q.order_by(AuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(q)
        items = list(result.scalars().all())

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if per_page else 0,
        }

    @staticmethod
    async def get_actions(db: AsyncSession) -> List[str]:
        """Get distinct action types for filter dropdown."""
        result = await db.execute(
            select(AuditLog.action).distinct().order_by(AuditLog.action)
        )
        return [row[0] for row in result.fetchall()]

    @staticmethod
    async def cleanup(db: AsyncSession, days: int = 90):
        """Delete audit entries older than N days."""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        result = await db.execute(
            select(AuditLog).where(AuditLog.created_at < cutoff)
        )
        count = 0
        for log in result.scalars().all():
            await db.delete(log)
            count += 1
        await db.commit()
        return count
