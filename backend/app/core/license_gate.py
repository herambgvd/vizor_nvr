# =============================================================================
# License Gate middleware
# =============================================================================
# When no valid license is installed, the platform is "off": every data API
# is rejected with 403 {"detail": "license_required"} so the product cannot be
# operated without a signed, valid .lic file.
#
# A small allowlist stays reachable so an admin can recover:
#   - authentication        (/api/auth/*)        → log in / refresh / logout
#   - license endpoints      (/api/license*)      → fingerprint + upload/activate
#   - health / metrics       (/api/health, /health, /metrics)
#   - CORS preflight         (any OPTIONS request)
#
# The frontend mirrors this with a route gate that redirects to the license
# upload screen; this middleware is the server-side enforcement so the rule
# holds even if the UI is bypassed.
# =============================================================================

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Path prefixes that remain reachable while unlicensed.
_ALLOWED_PREFIXES = (
    "/api/auth",
    "/api/license",
    "/api/health",
    "/health",
    "/metrics",
)


def _is_allowed(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") or path.startswith(p)
               for p in _ALLOWED_PREFIXES)


class LicenseGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Never gate CORS preflight or non-API/static asset requests.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        # Only gate API traffic. Static assets / SPA shell are served freely
        # so the frontend can load and present the license screen.
        if not path.startswith("/api"):
            return await call_next(request)

        if _is_allowed(path):
            return await call_next(request)

        # Lazy import keeps this module import-safe at startup.
        from app.license.service import get_license_service

        svc = get_license_service()
        if svc.is_active():
            return await call_next(request)

        status = svc.status
        return JSONResponse(
            status_code=403,
            content={
                "detail": "license_required",
                "license_required": True,
                "reason": status.reason or "no_license_installed",
            },
        )
