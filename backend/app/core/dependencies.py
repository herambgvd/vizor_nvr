# =============================================================================
# FastAPI Dependencies — auth, RBAC, database
# =============================================================================

from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.security import verify_token
from app.core.permissions import has_permission

_bearer = HTTPBearer()


# ---------------------------------------------------------------------------
# Current user from JWT
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Extract and validate current user from Bearer token."""
    payload = verify_token(credentials.credentials, expected_type="access")
    if payload is None or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "id": payload["sub"],
        "username": payload.get("username"),
        "email": payload.get("email"),
        "role": payload.get("role", "viewer"),
        "role_id": payload.get("role_id"),
    }


# ---------------------------------------------------------------------------
# Role shortcuts
# ---------------------------------------------------------------------------

async def get_admin_user(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin privileges required")
    return user


# ---------------------------------------------------------------------------
# Permission-gated dependency factory
# ---------------------------------------------------------------------------

def require_permission(action: str):
    """
    Returns a FastAPI dependency that checks the given permission.

    Usage::

        @router.post("/{camera_id}/start-recording")
        async def start(
            camera_id: str,
            user=Depends(require_permission("control_recording")),
            db: AsyncSession = Depends(get_db),
        ): ...
    """

    async def _check(
        request: Request,
        user: dict = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        # Try to extract camera_id from path params (if route has one)
        camera_id: Optional[str] = request.path_params.get("camera_id")
        allowed = await has_permission(db, user, action, camera_id)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {action}",
            )
        return user

    return _check
