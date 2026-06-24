# =============================================================================
# AI scenario catalog + licensing API.
#   GET  /api/ai/scenarios            — catalog (all, with license/enable state)
#   GET  /api/ai/scenarios/active     — operable scenarios (licensed + enabled)
#   GET  /api/ai/scenarios/{id}       — one scenario
#   PUT  /api/ai/scenarios/{id}/enable — operator toggle (requires licensed)
# =============================================================================
from __future__ import annotations

import hmac
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.audit_logger import client_ip, write_audit
from app.database import get_db
from app.core.dependencies import get_current_user, require_permission
from app.core.permissions import has_permission
from app.auth.api_keys import require_scope
from app.ai.models import CameraAIConfig, ScenarioResponse, ScenarioToggle
from app.ai.core.service import ai_service, ScenarioNotOperable
from app.ai.core.registry import register_manifest, unregister, ManifestError
from app.recordings.service import RecordingService

router = APIRouter(prefix="/api/ai", tags=["AI Scenarios"])
logger = logging.getLogger("app.ai.router")
recording_service = RecordingService()


def _manifest(scenario) -> dict[str, Any]:
    manifest = scenario.manifest or {}
    return manifest if isinstance(manifest, dict) else {}


def _service_url(scenario) -> str | None:
    manifest = _manifest(scenario)
    container = manifest.get("container") if isinstance(manifest.get("container"), dict) else {}
    return (manifest.get("service_url") or container.get("service_url") or "").rstrip("/") or None


def _route_regex(path: str) -> re.Pattern[str]:
    escaped = re.escape(path.strip("/"))
    escaped = re.sub(r"\\\{[^/]+\\\}", r"[^/]+", escaped)
    return re.compile(rf"^{escaped}/?$")


def is_proxy_route_allowed(manifest: Mapping[str, Any], method: str, path: str) -> bool:
    """Return True when a manifest proxy_routes entry allows method/path."""
    routes = manifest.get("proxy_routes") or []
    if not isinstance(routes, list):
        return False
    clean_path = path.strip("/")
    for route in routes:
        if isinstance(route, str):
            route_method = "*"
            route_path = route
        elif isinstance(route, Mapping):
            route_method = str(route.get("method") or "*").upper()
            route_path = str(route.get("path") or "")
        else:
            continue
        if route_method not in ("*", method.upper()):
            continue
        if _route_regex(route_path).match(clean_path):
            return True
    return False


def _to_response(scenario, active_count: int) -> ScenarioResponse:
    from app.license.service import get_license_service

    r = ScenarioResponse.model_validate(scenario)
    r.active_camera_count = active_count
    manifest = _manifest(scenario)
    r.service_url = _service_url(scenario)
    r.proxy_routes = manifest.get("proxy_routes") or []
    r.resource_requirements = manifest.get("resource_requirements") or {}
    r.tabs = manifest.get("tabs") or scenario.module_tabs or []
    r.entitlement_options = get_license_service().feature_options(scenario.slug)
    return r


def _require_scenario_option(slug: str, path: str) -> None:
    """Gate licensed sub-features inside a licensed scenario.

    Example: FRS can be licensed while Attendance and Investigation are sold as
    separate sub-features. UI hides those tabs, and this backend check prevents
    direct API access through the scenario proxy.
    """
    if slug != "frs":
        return
    from app.license.service import get_license_service

    p = path.strip("/")
    required = None
    if p == "attendance" or p.startswith("attendance/"):
        required = "attendance"
    elif p == "investigate" or p == "investigations" or p.startswith("investigations/"):
        required = "investigation"
    if required and not get_license_service().has_feature_option("frs", required):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"FRS {required.replace('_', ' ')} is not included in this license",
        )


def _require_plugin_service_token(x_vizor_service_token: str | None = Header(None)) -> None:
    if not settings.AI_PLUGIN_SERVICE_TOKEN:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI plugin service token not configured")
    # Constant-time compare so the shared secret can't be probed via timing.
    if not x_vizor_service_token or not hmac.compare_digest(
            str(x_vizor_service_token), str(settings.AI_PLUGIN_SERVICE_TOKEN)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid AI plugin service token")


async def _enabled_camera_ids_for_scenario(db: AsyncSession, scenario_id: str) -> list[str]:
    rows = (await db.execute(
        select(CameraAIConfig.camera_id)
        .where(
            CameraAIConfig.scenario_id == scenario_id,
            CameraAIConfig.enabled.is_(True),
        )
    )).scalars().all()
    return [str(x) for x in rows]


async def _assigned_camera_ids_for_scenario(db: AsyncSession, scenario_id: str) -> list[str]:
    rows = (await db.execute(
        select(CameraAIConfig.camera_id)
        .where(CameraAIConfig.scenario_id == scenario_id)
    )).scalars().all()
    return [str(x) for x in rows]


def _intersect_requested_camera_ids(
    requested_camera_id: str | None,
    requested_camera_ids: str | None,
    allowed: list[str],
) -> list[str]:
    requested: list[str] = []
    if requested_camera_ids:
        requested.extend([x.strip() for x in requested_camera_ids.split(",") if x.strip()])
    if requested_camera_id:
        requested.append(requested_camera_id)
    if not requested:
        return allowed
    allowed_set = set(allowed)
    return [x for x in requested if x in allowed_set]


@router.get("/scenarios", response_model=list[ScenarioResponse])
async def list_scenarios(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scenarios = await ai_service.list_scenarios(db)
    out = []
    for s in scenarios:
        cnt = await ai_service.active_camera_count(db, s.id)
        out.append(_to_response(s, cnt))
    return out


@router.get("/scenarios/active", response_model=list[ScenarioResponse])
async def list_active_scenarios(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scenarios = await ai_service.list_scenarios(db, operable_only=True)
    out = []
    for s in scenarios:
        cnt = await ai_service.active_camera_count(db, s.id)
        out.append(_to_response(s, cnt))
    return out


# ── Plugin registry (Phase 1) ───────────────────────────────────────────────
# Scenarios self-register from their manifest (scenario.json); the bridge may
# also register manifests from a scenarios.d/ dir. Auth via the bridge API key
# (events:ingest scope) so unattended scenario containers can register on boot.

@router.post("/scenarios/register", response_model=ScenarioResponse)
async def register_scenario(
    manifest: dict,
    key=Depends(require_scope("ai:register")),
    db: AsyncSession = Depends(get_db),
):
    """Upsert a scenario catalog row from its manifest, then re-project the
    signed license so an entitled-but-just-registered scenario flips licensed."""
    try:
        row = await register_manifest(db, manifest)
    except ManifestError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    await db.commit()
    await ai_service.sync_licensing(db)        # entitlement ↔ manifest match
    await db.refresh(row)
    cnt = await ai_service.active_camera_count(db, row.id)
    return _to_response(row, cnt)


@router.get("/internal/recordings")
async def internal_recording_catalog(
    camera_id: str | None = None,
    camera_ids: str | None = None,
    start_after: datetime | None = None,
    end_before: datetime | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    x_vizor_scenario: str | None = Header(None),
    _service=Depends(_require_plugin_service_token),
    db: AsyncSession = Depends(get_db),
):
    """Recording catalog for trusted scenario plugins.

    Plugins get metadata only; they still run in separate containers and must
    have read-only storage mounted to access files.
    """
    if not x_vizor_scenario:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Vizor-Scenario header required")
    scenario = await ai_service.get_scenario_by_slug(db, x_vizor_scenario)
    if not scenario:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")
    allowed = await _enabled_camera_ids_for_scenario(db, scenario.id)
    ids = _intersect_requested_camera_ids(camera_id, camera_ids, allowed)
    if not ids:
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "allowed_camera_ids": allowed}
    records = await recording_service.search(
        db,
        camera_ids=ids,
        start_time=start_after,
        end_time=end_before,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [
            {
                "id": rec.id,
                "camera_id": rec.camera_id,
                "file_path": rec.file_path,
                "start_time": rec.start_time.isoformat() if rec.start_time else None,
                "end_time": rec.end_time.isoformat() if rec.end_time else None,
                "duration": rec.duration,
                "fps": rec.fps,
                "resolution": rec.resolution,
                "stream_type": rec.stream_type,
                "file_size": rec.file_size,
            }
            for rec in records
        ],
        "total": len(records),
        "limit": limit,
        "offset": offset,
        "allowed_camera_ids": allowed,
    }


@router.get("/internal/cameras")
async def internal_camera_catalog(
    enabled_only: bool = Query(True),
    x_vizor_scenario: str | None = Header(None),
    _service=Depends(_require_plugin_service_token),
    db: AsyncSession = Depends(get_db),
):
    """Live-camera catalog for trusted scenario plugins.

    Returns the cameras a scenario is enabled (or assigned) on, with each
    camera's per-camera AI config. Plugins use this to spin up live-stream
    workers — they pull frames from go2rtc at rtsp://go2rtc:8554/{camera_id}
    (or the _sub variant). Metadata + config only; no credentials are exposed.
    """
    if not x_vizor_scenario:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Vizor-Scenario header required")
    scenario = await ai_service.get_scenario_by_slug(db, x_vizor_scenario)
    if not scenario:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")

    from app.cameras.models import Camera  # local import — avoid import cycle

    q = select(CameraAIConfig).where(CameraAIConfig.scenario_id == scenario.id)
    if enabled_only:
        q = q.where(CameraAIConfig.enabled.is_(True))
    configs = (await db.execute(q)).scalars().all()

    cam_ids = [c.camera_id for c in configs]
    cam_rows = {}
    if cam_ids:
        rows = (await db.execute(select(Camera).where(Camera.id.in_(cam_ids)))).scalars().all()
        cam_rows = {str(c.id): c for c in rows}

    items = []
    for cfg in configs:
        cam = cam_rows.get(str(cfg.camera_id))
        items.append({
            "config_id": cfg.id,
            "camera_id": cfg.camera_id,
            "camera_name": getattr(cam, "name", None),
            "enabled": cfg.enabled,
            "config": cfg.config or {},
            "stream_state": cfg.stream_state,
            # go2rtc stream ids (the plugin builds rtsp://go2rtc:8554/<id>).
            "stream_id": str(cfg.camera_id),
            "sub_stream_id": f"{cfg.camera_id}_sub",
        })
    return {"items": items, "total": len(items)}


@router.put("/internal/camera-configs/{config_id}/state")
async def internal_report_stream_state(
    config_id: str,
    body: dict,
    x_vizor_scenario: str | None = Header(None),
    _service=Depends(_require_plugin_service_token),
    db: AsyncSession = Depends(get_db),
):
    """Service-token variant of stream-state reporting — lets an unattended
    scenario plugin report its per-camera worker state (running/stopped/error)
    without a logged-in operator. Mirrors PUT /camera-configs/{id}/state."""
    state = str(body.get("state") or "").strip()
    if state not in ("running", "stopped", "error"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid state")
    from app.ai.core.camera_config_service import camera_config_service
    config = await camera_config_service.set_stream_state(
        db, config_id, state, body.get("error")
    )
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "camera config not found")
    return {"ok": True, "config_id": config_id, "state": state}


@router.get("/scenarios/{slug}/health")
async def scenario_health(
    slug: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scenario = await ai_service.get_scenario_by_slug(db, slug)
    if not scenario or not scenario.registered:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")
    url = _service_url(scenario)
    if not url:
        return {"slug": slug, "status": "unknown", "detail": "service_url not configured"}
    headers = {"X-Vizor-Scenario": slug, "X-Vizor-Request-Id": str(uuid.uuid4())}
    if settings.AI_PLUGIN_SERVICE_TOKEN:
        headers["X-Vizor-Service-Token"] = settings.AI_PLUGIN_SERVICE_TOKEN
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{url}/health", headers=headers)
        detail = resp.json() if "json" in resp.headers.get("content-type", "") else resp.text
        return {
            "slug": slug,
            "status": "healthy" if resp.status_code < 400 else "degraded",
            "status_code": resp.status_code,
            "detail": detail,
        }
    except Exception as exc:  # noqa: BLE001 - health must not break NVR
        return {"slug": slug, "status": "unreachable", "detail": str(exc)}


def _required_face_permission(method: str, path: str) -> str | None:
    """RBAC for biometric actions. Returns the PermissionAction the caller must
    hold, or None for unprivileged routes. Enroll/delete mutate the gallery
    (manage_ai_faces); investigate/recognize search faces (search_ai_faces)."""
    p = path.strip("/")
    m = method.upper()
    if m == "POST" and p.startswith("persons/") and p.endswith("/photos"):
        return "manage_ai_faces"
    if m == "DELETE" and (p.startswith("persons/") or p.startswith("photos/")):
        return "manage_ai_faces"
    if m in ("POST", "PUT") and (p == "persons" or p.startswith("persons/")
                                 or p == "groups" or p.startswith("groups/")):
        return "manage_ai_faces"
    if m == "POST" and p in ("investigate", "recognize"):
        return "search_ai_faces"
    return None


def _biometric_audit_action(method: str, path: str) -> tuple[str, str] | None:
    """Classify a proxied request as a biometric-data access worth auditing.
    Returns (audit_action, description) or None. Covers face-image views,
    forensic search, enrollment, and erasure across face scenarios."""
    p = path.strip("/")
    m = method.upper()
    # Forensic search over captured faces.
    if m == "POST" and p == "investigate":
        return ("ai_face_investigate", "forensic face search")
    # Recognize a face against the gallery.
    if m == "POST" and p == "recognize":
        return ("ai_face_recognize", "face recognition query")
    # Enrollment (adding a face to the gallery).
    if m == "POST" and p.startswith("persons/") and p.endswith("/photos"):
        return ("ai_face_enroll", "enrolled a face photo")
    # Erasure of a person (right-to-erasure of biometrics).
    if m == "DELETE" and p.startswith("persons/"):
        return ("ai_face_person_delete", f"deleted person + biometrics ({p})")
    return None


async def _proxy_to_scenario(
    slug: str,
    path: str,
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    scenario = await ai_service.get_scenario_by_slug(db, slug)
    if not scenario or not scenario.registered:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")
    if not scenario.licensed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "scenario not licensed")
    if not scenario.enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "scenario not enabled")
    _require_scenario_option(slug, path)
    manifest = _manifest(scenario)
    if not is_proxy_route_allowed(manifest, request.method, path):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "proxy route not allowed by scenario manifest")
    # Biometric RBAC. Face scenario (FRS): enroll/delete/search need elevated
    # perms. Suspect-search: forensic person search is a privileged action too.
    if slug == "frs":
        needed = _required_face_permission(request.method, path)
        if needed and not await has_permission(db, user, needed):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"requires '{needed}' permission")
    elif slug == "suspect-search":
        p_clean = path.strip("/")
        if request.method == "POST" and (p_clean in ("search", "jobs/search", "jobs/index")
                                         or p_clean.endswith("/search-similar")):
            if not await has_permission(db, user, "search_ai_faces"):
                raise HTTPException(status.HTTP_403_FORBIDDEN,
                                    "requires 'search_ai_faces' permission")
    service_url = _service_url(scenario)
    if not service_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "scenario service_url not configured")
    enabled_camera_ids = await _enabled_camera_ids_for_scenario(db, scenario.id)
    assigned_camera_ids = await _assigned_camera_ids_for_scenario(db, scenario.id)
    path_clean = path.strip("/")
    # Forensic / similarity search over HISTORICAL sightings — like GET history, these
    # must span every ASSIGNED camera (a camera the operator turned off still has past
    # snapshots worth searching), not just the currently-enabled set.
    is_search = (
        path_clean in ("search", "jobs/search", "investigate")
        or (path_clean.startswith("results/") and path_clean.endswith("/search-similar"))
    )
    if request.method == "POST" and path_clean == "jobs/index" and not enabled_camera_ids:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "No cameras are enabled for this scenario. Enable the scenario on at least one camera before indexing.",
        )
    if request.method == "POST" and is_search and not assigned_camera_ids:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "No cameras have been assigned to this scenario. Assign at least one camera before searching.",
        )
    # Read scope vs write scope. GET requests (event/plate/report history) must
    # see data from every ASSIGNED camera — a camera the operator turned OFF still
    # has historical events the operator should be able to review. Only writes /
    # search use the narrower enabled set.
    if request.method == "GET" or is_search:
        allowed_camera_ids = assigned_camera_ids
    else:
        allowed_camera_ids = enabled_camera_ids

    target = urljoin(f"{service_url}/", path)
    body = await request.body()
    headers = {
        "X-Vizor-User-Id": str(user.get("id") or ""),
        "X-Vizor-Username": str(user.get("username") or ""),
        "X-Vizor-Scenario": slug,
        "X-Vizor-Request-Id": request.headers.get("X-Request-Id") or str(uuid.uuid4()),
    }
    if settings.AI_PLUGIN_SERVICE_TOKEN:
        headers["X-Vizor-Service-Token"] = settings.AI_PLUGIN_SERVICE_TOKEN
    headers["X-Vizor-Allowed-Camera-Ids"] = ",".join(allowed_camera_ids)
    headers["X-Vizor-Enabled-Camera-Ids"] = ",".join(enabled_camera_ids)
    content_type = request.headers.get("content-type")
    if content_type:
        headers["content-type"] = content_type

    try:
        async with httpx.AsyncClient(timeout=settings.AI_PLUGIN_PROXY_TIMEOUT) as client:
            upstream = await client.request(
                request.method,
                target,
                params=request.query_params,
                content=body,
                headers=headers,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "scenario plugin timed out") from exc
    except httpx.RequestError as exc:
        logger.warning("[ai-proxy] %s %s failed: %s", slug, path, exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "scenario plugin unavailable") from exc

    response_headers = {}
    if upstream.headers.get("content-type"):
        response_headers["content-type"] = upstream.headers["content-type"]
    if request.method == "POST" and path.strip("/") in ("search", "jobs/search") and upstream.status_code < 400:
        details: dict[str, Any] = {"scenario": slug, "path": path}
        try:
            details["plugin_response"] = upstream.json()
        except Exception:
            details["plugin_response"] = upstream.text[:500]
        await write_audit(
            db,
            action="ai_suspect_search_job_create" if slug == "suspect-search" else "ai_scenario_job_create",
            user_id=str(user.get("id") or ""),
            username=str(user.get("username") or ""),
            ip_address=client_ip(request),
            resource_type="ai_scenario",
            resource_id=slug,
            description=f"AI scenario search job created for {slug}",
            details=details,
        )
        await db.commit()
    # Biometric audit trail (GDPR/BIPA): record who viewed/searched/mutated face
    # data and when. Reads of face images and forensic searches are logged too,
    # not just mutations — regulators require access logging for biometric data.
    audited = _biometric_audit_action(request.method, path)
    if audited and upstream.status_code < 400:
        action, desc = audited
        await write_audit(
            db,
            action=action,
            user_id=str(user.get("id") or ""),
            username=str(user.get("username") or ""),
            ip_address=client_ip(request),
            resource_type="ai_scenario",
            resource_id=slug,
            description=f"[{slug}] {desc}",
            details={"scenario": slug, "method": request.method, "path": path},
        )
        await db.commit()
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


@router.api_route(
    "/scenarios/{slug}/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy_scenario(
    slug: str,
    path: str,
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _proxy_to_scenario(slug, path, request, user=user, db=db)


@router.get("/scenarios/registry")
async def list_registry(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """All known scenarios with plugin/registration state."""
    scenarios = await ai_service.list_scenarios(db)
    return [
        {
            "slug": s.slug, "name": s.name, "version": s.version,
            "source": s.source, "registered": s.registered,
            "licensed": s.licensed, "enabled": s.enabled,
            "capabilities": s.capabilities or [],
            "registered_at": s.registered_at.isoformat() if s.registered_at else None,
        }
        for s in scenarios
    ]


@router.delete("/scenarios/{slug}/register")
async def unregister_scenario(
    slug: str,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    """Soft-uninstall a scenario (keeps row + per-camera config for re-install)."""
    ok = await unregister(db, slug)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")
    return {"ok": True, "slug": slug}


@router.get("/scenarios/{scenario_id}", response_model=ScenarioResponse)
async def get_scenario(
    scenario_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    s = await ai_service.get_scenario(db, scenario_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")
    cnt = await ai_service.active_camera_count(db, s.id)
    return _to_response(s, cnt)


@router.put("/scenarios/{scenario_id}/enable", response_model=ScenarioResponse)
async def toggle_scenario(
    scenario_id: str,
    body: ScenarioToggle,
    user=Depends(require_permission("manage_system")),
    db: AsyncSession = Depends(get_db),
):
    s = await ai_service.get_scenario(db, scenario_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found")
    try:
        s = await ai_service.set_enabled(db, s, body.enabled)
    except ScenarioNotOperable as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    cnt = await ai_service.active_camera_count(db, s.id)
    return _to_response(s, cnt)
