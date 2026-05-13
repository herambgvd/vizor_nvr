# =============================================================================
# Audit Router
# =============================================================================

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.audit.models import AuditLogPage
from app.audit.service import AuditService
from app.core.dependencies import get_admin_user

router = APIRouter(prefix="/audit", tags=["Audit"])
svc = AuditService()


@router.get("/logs", response_model=AuditLogPage)
async def query_audit_logs(
    action: Optional[str] = None,
    user_id: Optional[str] = None,
    severity: Optional[str] = None,
    resource_type: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.query(
        db, action=action, user_id=user_id, severity=severity,
        resource_type=resource_type, start_time=start_time, end_time=end_time,
        search=search, page=page, per_page=per_page,
    )


@router.get("/actions")
async def list_action_types(
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    actions = await svc.get_actions(db)
    return {"actions": actions}


@router.delete("/cleanup")
async def cleanup_old_logs(
    days: int = Query(90, ge=1),
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await svc.cleanup(db, days)
    return {"deleted": deleted}


# ─────────────────────────────────────────────────────────────────────────────
# Security audit report (Phase 5.8) + GDPR personal data export (Phase 5.7)
# ─────────────────────────────────────────────────────────────────────────────

from fastapi.responses import StreamingResponse, PlainTextResponse
import csv
import io
from datetime import datetime


@router.get("/report")
async def audit_report(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    format: str = Query("csv", regex="^(csv|json)$"),
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Compliance-style audit report scoped to a date range. Covers logins,
    failures, recording access, exports, config changes."""
    from sqlalchemy import text
    where = []
    params = {}
    if from_date:
        where.append("created_at >= :f"); params["f"] = from_date
    if to_date:
        where.append("created_at <= :t"); params["t"] = to_date
    sql = "SELECT created_at, action, severity, user_id, username, ip_address, " \
          "resource_type, resource_id, description FROM audit_logs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT 50000"
    rows = (await db.execute(text(sql), params)).fetchall()

    if format == "json":
        return {"count": len(rows), "rows": [dict(r._mapping) for r in rows]}

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["created_at", "action", "severity", "user_id", "username",
                "ip_address", "resource_type", "resource_id", "description"])
    for r in rows:
        w.writerow(list(r))
    buf.seek(0)
    fname = f"audit_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/export")
async def export_user_data(
    user_id: str = Query(...),
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """GDPR data portability: dump every audit_logs row tied to *user_id* as CSV.
    Operator hands this to the data subject on request."""
    from sqlalchemy import text
    rows = (await db.execute(text(
        "SELECT created_at, action, severity, ip_address, resource_type, "
        "resource_id, description FROM audit_logs WHERE user_id = :uid "
        "ORDER BY created_at"
    ), {"uid": user_id})).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["created_at", "action", "severity", "ip_address",
                "resource_type", "resource_id", "description"])
    for r in rows:
        w.writerow(list(r))
    buf.seek(0)
    fname = f"user_data_{user_id}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
