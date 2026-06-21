"""Public (un-authenticated) AI scenario endpoints.

These bypass the operator-JWT proxy on purpose — they are the third-party ingest
API (gated by the scenario's own ingest API key) and the public realtime
dashboard (gated by the scenario's public-dashboard toggle). The NVR backend only
forwards to the plugin with the service token; the PLUGIN enforces the API key /
public toggle (single source of truth = plugin settings).

Currently wired for FRS; the path is slug-namespaced so other scenarios can be
added the same way.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.config import settings
from app.database import get_db
from app.ai.core.service import ai_service

logger = logging.getLogger(__name__)

# No auth dependency — these endpoints are intentionally public.
router = APIRouter(prefix="/api/ai", tags=["AI Public"])

def _manifest(scenario) -> dict:
    return scenario.manifest if isinstance(scenario.manifest, dict) else {}


def _service_url(scenario) -> str | None:
    m = _manifest(scenario)
    container = m.get("container") or {}
    return (m.get("service_url") or container.get("service_url") or "").rstrip("/") or None


async def _resolve(slug: str, db: AsyncSession):
    """Resolve any registered + licensed scenario's plugin URL. The plugin itself
    enforces the public toggle / ingest key, so the NVR just forwards — every
    scenario gets a public surface uniformly (no per-slug allowlist)."""
    scenario = await ai_service.get_scenario_by_slug(db, slug)
    if not scenario or not scenario.registered or not scenario.licensed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    url = _service_url(scenario)
    if not url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "scenario unavailable")
    return url


def _service_headers(extra: dict | None = None) -> dict:
    headers = {}
    if settings.AI_PLUGIN_SERVICE_TOKEN:
        headers["X-Vizor-Service-Token"] = settings.AI_PLUGIN_SERVICE_TOKEN
    if extra:
        headers.update(extra)
    return headers


@router.post("/{slug}/ingest")
async def ingest_event(slug: str, request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    """Third-party event ingest. The caller supplies the scenario ingest API key
    in X-Scn-Ingest-Key (or the legacy X-FRS-Ingest-Key); the plugin verifies it
    (returns 401 if invalid/disabled)."""
    service_url = await _resolve(slug, db)
    body = await request.body()
    headers = _service_headers({"content-type": request.headers.get("content-type", "application/json")})
    # Forward the ingest key the plugin checks (accept generic + legacy FRS header;
    # forward both so the plugin can read whichever it expects).
    key = (request.headers.get("X-Scn-Ingest-Key")
           or request.headers.get("x-scn-ingest-key")
           or request.headers.get("X-FRS-Ingest-Key")
           or request.headers.get("x-frs-ingest-key"))
    if key:
        headers["X-Scn-Ingest-Key"] = key
        headers["X-FRS-Ingest-Key"] = key
    try:
        async with httpx.AsyncClient(timeout=settings.AI_PLUGIN_PROXY_TIMEOUT) as client:
            up = await client.post(f"{service_url}/ingest/event", content=body, headers=headers)
    except httpx.RequestError as exc:
        logger.warning("[ai-public] %s ingest failed: %s", slug, exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "scenario plugin unavailable") from exc
    return Response(content=up.content, status_code=up.status_code,
                    media_type=up.headers.get("content-type"))


@router.get("/{slug}/public/dashboard")
async def public_dashboard(slug: str, db: AsyncSession = Depends(get_db)) -> Response:
    """Aggregate public dashboard data. Plugin returns 404 if the public toggle
    is off."""
    service_url = await _resolve(slug, db)
    try:
        async with httpx.AsyncClient(timeout=settings.AI_PLUGIN_PROXY_TIMEOUT) as client:
            up = await client.get(f"{service_url}/public/dashboard", headers=_service_headers())
    except httpx.RequestError as exc:
        logger.warning("[ai-public] %s dashboard failed: %s", slug, exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "scenario plugin unavailable") from exc
    return Response(content=up.content, status_code=up.status_code,
                    media_type=up.headers.get("content-type"))


@router.get("/{slug}/public/stream")
async def public_stream(slug: str, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    """Proxy the plugin's SSE realtime stream to the public dashboard."""
    service_url = await _resolve(slug, db)

    async def _relay():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", f"{service_url}/public/stream",
                                         headers=_service_headers()) as up:
                    if up.status_code != 200:
                        return
                    async for chunk in up.aiter_raw():
                        yield chunk
        except httpx.RequestError as exc:
            logger.warning("[ai-public] %s stream failed: %s", slug, exc)
            return

    return StreamingResponse(
        _relay(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
