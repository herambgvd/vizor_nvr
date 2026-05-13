# =============================================================================
# Audit Logger — fire-and-forget helper to write audit rows
# =============================================================================

import logging
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def write_audit(
    db: AsyncSession,
    *,
    action: str,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    ip_address: Optional[str] = None,
    severity: str = "info",
    description: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Insert an audit log row.  Best-effort — exceptions are logged, not raised.
    """
    try:
        from app.audit.models import AuditLog  # lazy to avoid circular

        entry = AuditLog(
            action=action,
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            severity=severity,
            description=description,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        db.add(entry)
        await db.flush()  # flush inside the caller's transaction
    except Exception:
        logger.exception("Failed to write audit log")


def client_ip(request) -> str:
    """Extract client IP from a FastAPI Request."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"
