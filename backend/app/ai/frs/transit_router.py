# =============================================================================
# FRS transit rules + sessions (proxy → bridge HTTP).
#
#   Transit rules (CRUD):
#     POST   /api/ai/frs/transit/rules        (json) → rule       [manage_system]
#     GET    /api/ai/frs/transit/rules                → rules
#     PUT    /api/ai/frs/transit/rules/{id}   (json) → rule       [manage_system]
#     DELETE /api/ai/frs/transit/rules/{id}          → {ok}       [manage_system]
#   Transit sessions:
#     GET    /api/ai/frs/transit/sessions     (query status,since,until,limit,offset)
#
# The NVR backend stays gRPC-free: these endpoints proxy via httpx to the
# bridge HTTP API (BRIDGE_HTTP_URL), which holds the FRS gRPC client. Transit
# rules + sessions live in the FRS scenario db — NVR adds no tables, no logic.
# =============================================================================
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.core.dependencies import get_current_user, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai/frs", tags=["FRS Transit"])

BRIDGE_HTTP_URL = os.getenv("BRIDGE_HTTP_URL", "http://localhost:8099").rstrip("/")

_TIMEOUT = httpx.Timeout(30.0)


# =============================================================================
# Helpers
# =============================================================================

def _bridge_error(detail: str, exc: Optional[Exception] = None) -> HTTPException:
    if exc is not None:
        logger.warning("[frs-transit] bridge call failed: %s (%s)", detail, exc)
    else:
        logger.warning("[frs-transit] bridge call failed: %s", detail)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=detail)


def _passthrough(resp: httpx.Response):
    """Return the bridge JSON body, mapping non-2xx into a 502."""
    if resp.status_code >= 400:
        try:
            body = resp.json()
            detail = body.get("detail", body)
        except Exception:
            detail = resp.text or f"bridge returned {resp.status_code}"
        raise _bridge_error(f"bridge error: {detail}")
    try:
        return resp.json()
    except Exception as e:
        raise _bridge_error("bridge returned non-JSON response", e)


# =============================================================================
# Transit rules (CRUD)
# =============================================================================

@router.post("/transit/rules")
async def create_transit_rule(
    body: Dict[str, Any] = Body(...),
    user=Depends(require_permission("manage_system")),
):
    """Create a transit rule on the FRS scenario."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{BRIDGE_HTTP_URL}/transit/rules", json=body
            )
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)


@router.get("/transit/rules")
async def list_transit_rules(
    user=Depends(get_current_user),
):
    """List transit rules from the FRS scenario."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{BRIDGE_HTTP_URL}/transit/rules")
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)


@router.put("/transit/rules/{rule_id}")
async def update_transit_rule(
    rule_id: str,
    body: Dict[str, Any] = Body(...),
    user=Depends(require_permission("manage_system")),
):
    """Update a transit rule on the FRS scenario."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.put(
                f"{BRIDGE_HTTP_URL}/transit/rules/{rule_id}", json=body
            )
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)


@router.delete("/transit/rules/{rule_id}")
async def delete_transit_rule(
    rule_id: str,
    user=Depends(require_permission("manage_system")),
):
    """Delete a transit rule on the FRS scenario."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.delete(
                f"{BRIDGE_HTTP_URL}/transit/rules/{rule_id}"
            )
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)


# =============================================================================
# Transit sessions
# =============================================================================

@router.get("/transit/sessions")
async def list_transit_sessions(
    status: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user=Depends(get_current_user),
):
    """List transit sessions from the FRS scenario."""
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if status is not None:
        params["status"] = status
    if since is not None:
        params["since"] = since
    if until is not None:
        params["until"] = until
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{BRIDGE_HTTP_URL}/transit/sessions", params=params
            )
    except httpx.HTTPError as e:
        raise _bridge_error("failed to reach bridge", e)
    return _passthrough(resp)
