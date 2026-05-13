# =============================================================================
# IP allow-list middleware (Phase 5.4)
# =============================================================================
#
# Optional whitelist applied only to admin routes. Configured via the
# `admin_ip_allowlist` setting (CIDR strings, comma-separated). Localhost
# is always allowed so the operator can recover from a misconfiguration via
# `curl http://localhost:8000/...`.
# =============================================================================

import ipaddress
import logging
from typing import Iterable, Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def _parse_cidrs(raw: str) -> list:
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.warning(f"IP allowlist: ignoring invalid CIDR {part!r}")
    return out


def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real
    return request.client.host if request.client else None


def _ip_allowed(ip: str, cidrs: Iterable) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback:
        return True
    for net in cidrs:
        if addr in net:
            return True
    return False


# Paths that count as "admin" surface. Anything under these prefixes is
# gated when the allow-list is non-empty.
_ADMIN_PREFIXES = (
    "/api/settings",
    "/api/storage",
    "/api/auth/users",
    "/api/auth/roles",
    "/api/auth/sessions/all",
    "/api/audit",
)


class IPAllowlistMiddleware(BaseHTTPMiddleware):
    """Lookup is cheap — settings are cached via the Settings service."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not any(path.startswith(p) for p in _ADMIN_PREFIXES):
            return await call_next(request)

        cidrs = await self._load_cidrs()
        if not cidrs:
            return await call_next(request)

        ip = _client_ip(request)
        if not _ip_allowed(ip, cidrs):
            logger.warning(f"IP allowlist: blocked {ip} → {path}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Source IP not permitted for admin routes"},
            )
        return await call_next(request)

    @staticmethod
    async def _load_cidrs():
        """Read the comma-separated CIDR list from the settings table.
        Empty / unset → middleware is a no-op. Cached at-load to avoid a DB
        hit per request; refreshes on a 30 s clock."""
        import time
        cache = IPAllowlistMiddleware._cache
        now = time.time()
        if cache["expires"] > now:
            return cache["cidrs"]
        try:
            from app.database import async_session_maker
            from app.settings.service import SettingsService
            async with async_session_maker() as db:
                raw = await SettingsService.get_value(db, "admin_ip_allowlist", "")
        except Exception:
            raw = ""
        cidrs = _parse_cidrs(raw)
        cache["cidrs"] = cidrs
        cache["expires"] = now + 30
        return cidrs

    _cache: dict = {"cidrs": [], "expires": 0.0}
