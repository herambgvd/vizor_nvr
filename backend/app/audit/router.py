# =============================================================================
# Audit Router
# =============================================================================

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
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
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.query(
        db, action=action, user_id=user_id, severity=severity,
        resource_type=resource_type, start_time=start_time, end_time=end_time,
        search=search, limit=limit, offset=offset,
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
    request: Request,
    days: int = Query(365, ge=365),   # floor: cannot purge audit < 1 year old
    user: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Retention purge of OLD audit logs only. Tamper-resistance: a hard 365-day
    floor prevents an actor from erasing recent evidence, and the purge itself is
    audited (who, when, how many) so the deletion is recorded in the trail."""
    deleted = await svc.cleanup(db, days)
    # Record the purge in the audit trail it just trimmed.
    from app.core.audit_logger import write_audit, client_ip
    await write_audit(
        db,
        action="audit_log_cleanup",
        user_id=str(user.get("id") or ""),
        username=user.get("username", "admin"),
        ip_address=client_ip(request),
        severity="warning",
        description=f"Purged {deleted} audit entries older than {days} days",
        details={"days": days, "deleted": deleted},
    )
    await db.commit()
    return {"deleted": deleted}


# ─────────────────────────────────────────────────────────────────────────────
# Security audit report (Phase 5.8) + GDPR personal data export (Phase 5.7)
# ─────────────────────────────────────────────────────────────────────────────

from fastapi.responses import StreamingResponse, PlainTextResponse
import csv
import io
from datetime import datetime


@router.get("/logs/export")
async def export_audit_logs(
    format: str = Query("csv", regex="^(csv|json)$"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    admin: dict = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream a full audit log export as CSV or JSON (admin only).
    Query params: format=csv|json, from=<iso>, to=<iso>, user_id=, action=
    Suitable for compliance audits; uses StreamingResponse to avoid OOM on large sets."""
    from sqlalchemy import text

    where_clauses = []
    params: dict = {}
    if from_date:
        where_clauses.append("created_at >= :from_date")
        params["from_date"] = from_date
    if to_date:
        where_clauses.append("created_at <= :to_date")
        params["to_date"] = to_date
    if user_id:
        where_clauses.append("user_id = :user_id")
        params["user_id"] = user_id
    if action:
        where_clauses.append("action = :action")
        params["action"] = action

    sql = (
        "SELECT created_at, user_id, username, action, resource_type, "
        "resource_id, ip_address, severity, description FROM audit_logs"
    )
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY created_at DESC"

    rows = (await db.execute(text(sql), params)).fetchall()
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

    if format == "json":
        import json

        def _iter_json():
            yield '{"count":' + str(len(rows)) + ',"rows":['
            cols = ["created_at", "user_id", "username", "action",
                    "resource_type", "resource_id", "ip_address", "severity", "description"]
            for i, row in enumerate(rows):
                rec = {}
                for col, val in zip(cols, row):
                    rec[col] = str(val) if val is not None else None
                yield ("," if i else "") + json.dumps(rec)
            yield "]}"

        return StreamingResponse(
            _iter_json(),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="audit-{timestamp}.json"'},
        )

    # CSV streaming — yield header then rows in chunks to avoid memory pressure
    COLS = ["timestamp", "user_id", "username", "action", "resource_type",
            "resource_id", "ip_address", "severity", "description"]

    def _iter_csv():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(COLS)
        yield buf.getvalue()
        for row in rows:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow([str(v) if v is not None else "" for v in row])
            yield buf.getvalue()

    return StreamingResponse(
        _iter_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit-{timestamp}.csv"'},
    )


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
