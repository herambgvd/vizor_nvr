# =============================================================================
# GVD NVR — Application Factory
# =============================================================================
# Entry point: uvicorn app.main:app  (from backend/ directory)
# =============================================================================

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse

from app import __version__
from app.config import settings
from app.database import init_db, async_session_maker

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.ENV == "development" else logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)-30s  %(message)s",
    stream=sys.stdout,
)
# Silence noisy third-party loggers
for _noisy in (
    "watchfiles", "httpcore", "httpx", "hpack", "urllib3", "multipart",
    # zeep emits the entire WSDL/SOAP envelope on every ONVIF call at
    # DEBUG/INFO — drown the backend log otherwise.
    "zeep", "zeep.wsdl", "zeep.xsd", "zeep.transports", "onvif",
):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger("app")


# ══════════════════════════════════════════════════════════════════════
# Lifespan — startup / shutdown
# ══════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(application: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────
    logger.info(f"GVD NVR v{__version__} starting (env={settings.ENV})")

    # Wait for the database to accept connections before starting anything
    # (guards against Postgres still in recovery on container startup)
    from app.core.db_retry import wait_for_db
    await wait_for_db(timeout=60.0, op_name="startup_gate")

    # Create database tables
    await init_db()

    # Seed defaults
    async with async_session_maker() as db:
        from app.auth.service import AuthService
        from app.settings.service import SettingsService
        await AuthService.seed_roles(db)
        await SettingsService.seed_defaults(db)

    # Seed default schedule templates (idempotent)
    try:
        from app.cameras.schedule_templates_router import seed_default_templates
        async with async_session_maker() as db:
            await seed_default_templates(db)
    except Exception as _e:
        logger.warning(f"Schedule template seed failed: {_e}")

    # One-shot backfill: re-encrypt any legacy plaintext ONVIF credentials.
    # Idempotent — already-encrypted rows skipped.
    try:
        from app.core.crypto import backfill_encrypt_credentials
        await backfill_encrypt_credentials()
    except Exception as _e:
        logger.warning(f"ONVIF credential backfill failed: {_e}")

    # Ensure storage directories (incl. data/ and data/certs/)
    settings.ensure_directories()

    # License — load installed .lic before any router handles requests so
    # gate methods can return correct answers from the first call.
    try:
        from app.license.service import get_license_service
        await get_license_service().load_persisted()
    except Exception as _e:
        logger.warning(f"License load failed: {_e}")

    # TLS: emit a self-signed cert on first boot so HTTPS is usable out of
    # the box. Operator can replace it via POST /api/settings/tls/upload.
    try:
        from app.settings.tls_service import ensure_present as _ensure_tls
        _ensure_tls()
    except Exception as _e:
        logger.warning(f"TLS bootstrap failed: {_e}")

    # Mount static file directories
    import os
    for name, path in [
        ("recordings", str(settings.STORAGE_PATH)),
        ("thumbnails", str(settings.THUMBNAIL_PATH)),
        ("hls", str(settings.HLS_PATH)),
        ("exports", str(settings.EXPORT_PATH)),
    ]:
        os.makedirs(path, exist_ok=True)
        application.mount(f"/{name}", StaticFiles(directory=path), name=name)

    # Start background services
    from app.monitoring.service import monitoring_service
    from app.services.camera_monitor import camera_monitor
    from app.services.retention_service import retention_service
    from app.services.recovery_service import recovery_service
    from app.notifications.service import notification_service
    from app.services.prebuffer_service import prebuffer_service
    from app.services.snapshot_service import snapshot_service as _snapshot_svc
    from app.core.rate_limiter import auth_limiter

    await monitoring_service.start()
    await prebuffer_service.start()
    await camera_monitor.start()
    await retention_service.start()
    await _snapshot_svc.start_scheduler()
    await notification_service.start()
    auth_limiter.start_cleanup()  # Prevent in-memory leak under sustained traffic

    # S.M.A.R.T disk health poller (no-op if smartctl missing)
    try:
        from app.services.disk_health_service import disk_health_service
        await disk_health_service.start()
    except Exception as _e:
        logger.warning(f"disk_health_service start skipped: {_e}")

    # Thumbnail pre-generation background job (X.5)
    from app.services.thumbnail_service import thumbnail_service
    await thumbnail_service.start()

    # Sync all cameras to go2rtc (register main + sub streams on startup)
    try:
        from app.services.go2rtc_manager import go2rtc_manager
        from app.cameras.models import Camera
        from sqlalchemy import select
        async with async_session_maker() as db:
            result = await db.execute(
                select(Camera).where(Camera.is_enabled.is_(True))
            )
            cameras = result.scalars().all()
            synced = 0
            for cam in cameras:
                if cam.main_stream_url:
                    await go2rtc_manager.add_stream(cam.id, cam.main_stream_url)
                    synced += 1
                if cam.sub_stream_url:
                    await go2rtc_manager.add_stream(f"{cam.id}_sub", cam.sub_stream_url)
        logger.info(f"go2rtc: synced {synced} camera streams on startup")
    except Exception as _e:
        logger.warning(f"go2rtc startup sync failed (go2rtc may not be running yet): {_e}")

    # Recover FFmpeg processes
    if settings.FFMPEG_RECOVERY_ENABLED:
        await recovery_service.recover()

    # OS-level watchdog: detect hung / dead FFmpeg processes between segment cycles
    from app.services.ffmpeg_manager import ffmpeg_manager as _ffmgr
    await _ffmgr.start_watchdog()

    # Start PTZ tour patrol service
    try:
        from app.services.ptz_tour_service import ptz_tour_service
        await ptz_tour_service.start()
    except Exception as _e:
        logger.warning(f"ptz_tour_service start skipped: {_e}")

    # Start ONVIF event pull service
    from app.cameras.onvif_event_service import onvif_event_service as _oes
    await _oes.start_all()

    # Start ONVIF device discovery publisher (NVR as ONVIF device)
    from app.onvif_device.discovery import onvif_discovery_publisher
    await onvif_discovery_publisher.start()

    # Start background task to sweep expired PullPoint subscriptions
    from app.onvif_device.service import sweep_expired_subscriptions
    _sweep_task = asyncio.create_task(sweep_expired_subscriptions(), name="onvif_subscription_sweep")

    # Start ONVIF replay session eviction loop
    from app.onvif_device.replay_manager import replay_manager as _replay_mgr
    await _replay_mgr.start_eviction_loop()

    logger.info("All services started — NVR is ready")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────
    logger.info("Shutting down...")

    # Refuse new requests, wait for in-flight to drain
    from app.core.graceful_shutdown import start_drain, wait_for_drain
    start_drain()
    await wait_for_drain(timeout=30.0)

    from app.services.ffmpeg_manager import ffmpeg_manager
    from app.services.go2rtc_manager import go2rtc_manager
    from app.notifications.service import notification_service

    try:
        from app.services.ptz_tour_service import ptz_tour_service
        await ptz_tour_service.stop()
    except Exception:
        pass
    from app.cameras.onvif_event_service import onvif_event_service as _oes
    await _oes.stop_all()
    from app.onvif_device.discovery import onvif_discovery_publisher
    await onvif_discovery_publisher.stop()
    try:
        _sweep_task.cancel()
        await asyncio.gather(_sweep_task, return_exceptions=True)
    except Exception:
        pass

    await camera_monitor.stop()
    await _snapshot_svc.close()
    await prebuffer_service.stop()
    await retention_service.stop()
    await monitoring_service.stop()
    await notification_service.stop()
    await ffmpeg_manager.stop_watchdog()
    try:
        from app.services.disk_health_service import disk_health_service
        await disk_health_service.stop()
    except Exception:
        pass
    try:
        from app.services.thumbnail_service import thumbnail_service
        await thumbnail_service.stop()
    except Exception:
        pass
    await ffmpeg_manager.cleanup()
    await go2rtc_manager.close()

    # Stop replay session manager
    try:
        from app.onvif_device.replay_manager import replay_manager as _replay_mgr
        await _replay_mgr.stop_eviction_loop()
    except Exception:
        pass

    logger.info("Shutdown complete")


# ══════════════════════════════════════════════════════════════════════
# App creation
# ══════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="GVD NVR",
    description=(
        "GVD NVR REST API. ONVIF Profile S/T compliant. "
        "All endpoints require Bearer JWT or X-Vizor-API-Key header.\n\n"
        "Network Video Recorder with RBAC, ONVIF, PTZ, multi-stream, "
        "storage pools, integrity verification, signed evidence export, "
        "and TOTP 2FA."
    ),
    version="2.0.0",
    lifespan=lifespan,
    # Disable auto-mounted docs — we serve admin-gated branded versions below
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    openapi_tags=[
        {"name": "Authentication", "description": "Login, sessions, 2FA, roles, ACL"},
        {"name": "Cameras", "description": "Cameras, ONVIF, PTZ, motion zones, privacy masks"},
        {"name": "Recordings", "description": "Playback, export, integrity, evidence bundles"},
        {"name": "Events", "description": "Motion / tamper / video-loss + linkage rules"},
        {"name": "Storage", "description": "Pools, tiers, S.M.A.R.T disk health, analytics"},
        {"name": "Monitoring", "description": "CPU/RAM, FFmpeg, bandwidth, disk health"},
        {"name": "Settings", "description": "System settings, TLS, backup/restore"},
        {"name": "System", "description": "License, NTP, DDNS, updates"},
        {"name": "Audit", "description": "Audit log, compliance reports, GDPR export"},
    ],
)


# ── CORS ─────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Admin route IP allow-list (Phase 5.4). No-op when the setting is empty.
from app.core.ip_allowlist import IPAllowlistMiddleware
app.add_middleware(IPAllowlistMiddleware)

# Graceful shutdown: tracks in-flight requests, refuses new ones once
# `start_drain()` is called from the lifespan shutdown hook.
from app.core.graceful_shutdown import InFlightRequestsMiddleware
app.add_middleware(InFlightRequestsMiddleware)


# ── Prometheus metrics (Phase 8) ─────────────────────────────────────
# Exposes /metrics for scraping. Default instrumentator captures HTTP
# request count, latency histogram, in-flight count. Custom NVR-specific
# metrics (ffmpeg processes, active cameras, event ingest rate) are
# defined alongside the producing service.
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/api/health", "/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    logger.info("Prometheus /metrics endpoint enabled")
except ImportError:
    logger.warning(
        "prometheus_fastapi_instrumentator not installed; /metrics disabled"
    )


# ── Global exception handler ────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ══════════════════════════════════════════════════════════════════════
# Register routers
# ══════════════════════════════════════════════════════════════════════

from app.auth.router import router as auth_router
from app.cameras.router import router as cameras_router
from app.recordings.router import router as recordings_router
from app.bookmarks.router import router as bookmarks_router
from app.events.router import router as events_router
from app.storage.router import router as storage_router
from app.monitoring.router import router as monitoring_router
from app.monitoring.camera_health_router import router as camera_health_router
from app.settings.router import router as settings_router
from app.settings.backup_router import router as backup_router
from app.audit.router import router as audit_router
from app.notifications.router import router as notifications_router
from app.core.websocket_router import router as websocket_router
from app.system.router import router as system_router
from app.onvif_device.router import router as onvif_device_router
from app.auth.api_keys_router import router as api_keys_router
from app.events.ingest_router import router as events_ingest_router
from app.events.sse_router import router as events_sse_router
from app.license.router import router as license_router
from app.cameras.schedule_templates_router import router as schedule_templates_router
from app.snapshots.router import router as snapshots_router

app.include_router(auth_router, prefix="/api")
app.include_router(snapshots_router, prefix="/api")
app.include_router(cameras_router, prefix="/api")
app.include_router(recordings_router, prefix="/api")
app.include_router(bookmarks_router, prefix="/api")
app.include_router(events_router, prefix="/api")
app.include_router(storage_router, prefix="/api")
app.include_router(monitoring_router, prefix="/api")
app.include_router(camera_health_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(backup_router, prefix="/api")
app.include_router(audit_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(websocket_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(api_keys_router)
app.include_router(events_ingest_router)
app.include_router(events_sse_router)
app.include_router(license_router)
app.include_router(schedule_templates_router, prefix="/api")

# ONVIF device endpoints are NOT under /api (VMS expects root-level paths)
app.include_router(onvif_device_router)


# ── Admin-gated branded API docs ─────────────────────────────────────
# These replace the default /docs /redoc /openapi.json with authenticated,
# branded equivalents restricted to the admin role.

from app.core.dependencies import get_admin_user as _get_admin_user
from fastapi import Depends as _Depends

@app.get("/api/openapi.json", include_in_schema=False)
async def get_openapi_schema(admin=_Depends(_get_admin_user)):
    """Return the full OpenAPI spec. Admin only."""
    return JSONResponse(app.openapi())


@app.get("/api/docs", response_class=HTMLResponse, include_in_schema=False)
async def get_swagger_ui(admin=_Depends(_get_admin_user)):
    """Branded Swagger UI — admin only."""
    html = """<!DOCTYPE html>
<html>
<head>
  <title>GVD NVR API &middot; Swagger</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" >
  <style>
    body { margin: 0; background: #0f172a; }
    .swagger-ui .topbar { background: #0f172a; border-bottom: 1px solid #1e293b; }
    .swagger-ui .topbar .download-url-wrapper { display: none; }
    .swagger-ui .topbar-wrapper img { content: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%2314b8a6" width="32" height="32"><circle cx="12" cy="12" r="10"/></svg>'); }
    .swagger-ui .topbar-wrapper a::after { content: " GVD NVR"; color: #14b8a6; font-weight: 700; font-size: 1.1rem; margin-left: 8px; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"> </script>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-standalone-preset.js"> </script>
  <script>
    window.onload = function() {
      SwaggerUIBundle({
        url: "/api/openapi.json",
        dom_id: '#swagger-ui',
        presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
        plugins: [SwaggerUIBundle.plugins.DownloadUrl],
        layout: "StandaloneLayout",
        requestInterceptor: (req) => {
          const token = localStorage.getItem('nvr_access_token');
          if (token) req.headers['Authorization'] = 'Bearer ' + token;
          return req;
        },
      });
    };
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/api/redoc", response_class=HTMLResponse, include_in_schema=False)
async def get_redoc_ui(admin=_Depends(_get_admin_user)):
    """Branded ReDoc — admin only."""
    html = """<!DOCTYPE html>
<html>
<head>
  <title>GVD NVR API &middot; ReDoc</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
  <style>body { margin: 0; padding: 0; background: #0f172a; }</style>
</head>
<body>
  <redoc spec-url='/api/openapi.json' theme='{"colors":{"primary":{"main":"#14b8a6"}},"typography":{"fontFamily":"Roboto, sans-serif"}}'></redoc>
  <script src="https://cdn.jsdelivr.net/npm/redoc/bundles/redoc.standalone.js"></script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ── Health check ─────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    from app.services.go2rtc_manager import go2rtc_manager
    from app.services.ffmpeg_manager import ffmpeg_manager
    go2rtc_ok = await go2rtc_manager.is_healthy()
    return {
        "status": "ok",
        "version": __version__,
        "go2rtc": "connected" if go2rtc_ok else "disconnected",
        "active_recordings": ffmpeg_manager.active_count,
    }
