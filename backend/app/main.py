# =============================================================================
# Vizor NVR — Application Factory
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
from fastapi.responses import JSONResponse, HTMLResponse, Response

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
    logger.info(f"Vizor NVR v{__version__} starting (env={settings.ENV})")

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

    # AI scenarios are future add-ons. Keep them opt-in so the current product
    # ships as a focused NVR; enable later with ENABLE_AI_MODULES=true.
    if settings.ENABLE_AI_MODULES:
        try:
            from app.ai.core.seed import seed_scenarios
            from app.ai.core.service import ai_service
            async with async_session_maker() as db:
                await seed_scenarios(db)
                await ai_service.sync_licensing(db)
        except Exception as _e:
            logger.warning(f"AI scenario seed/sync failed: {_e}")

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

    # Scheduled backup / archive service
    try:
        from app.storage.archive_service import archive_service
        await archive_service.start()
    except Exception as _e:
        logger.warning(f"archive_service start skipped: {_e}")

    # N+1 clustering / hot standby
    try:
        from app.cluster.service import cluster_service
        await cluster_service.start()
    except Exception as _e:
        logger.warning(f"cluster_service start skipped: {_e}")

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
                    await go2rtc_manager.add_stream(cam.id, cam.main_stream_url, dewarp_config=cam.dewarp_config)
                    synced += 1
                if cam.sub_stream_url:
                    await go2rtc_manager.add_stream(f"{cam.id}_sub", cam.sub_stream_url, dewarp_config=cam.dewarp_config)
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
    from app.onvif_device.service import sweep_expired_subscriptions, push_delivery_worker
    _sweep_task = asyncio.create_task(sweep_expired_subscriptions(), name="onvif_subscription_sweep")
    _push_task = asyncio.create_task(push_delivery_worker(), name="onvif_push_delivery")

    # Auto-mount NAS storage pools
    try:
        from app.storage.nas_service import nas_service
        async with async_session_maker() as db:
            await nas_service.auto_mount_all_pools(db)
    except Exception as _e:
        logger.warning(f"NAS auto-mount skipped: {_e}")

    # Refresh spot output streams for decoder boxes
    try:
        from app.spot_output.service import spot_output_service
        await spot_output_service.refresh_all()
    except Exception as _e:
        logger.warning(f"Spot output refresh skipped: {_e}")

    # Start POS overlay TCP listener (if any cameras have TCP source configured)
    try:
        from app.services.pos_overlay_service import pos_overlay_service
        await pos_overlay_service.start_tcp_listener()  # host/port from settings
    except Exception as _e:
        logger.warning(f"POS TCP listener skipped: {_e}")

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
        _push_task.cancel()
        await asyncio.gather(_sweep_task, _push_task, return_exceptions=True)
    except Exception:
        pass

    await camera_monitor.stop()
    await _snapshot_svc.close()
    await prebuffer_service.stop()
    await retention_service.stop()
    await monitoring_service.stop()
    try:
        from app.services.pos_overlay_service import pos_overlay_service
        await pos_overlay_service.stop_tcp_listener()
    except Exception:
        pass
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

    # Stop cluster service (releases advisory lock so standby can promote)
    try:
        from app.cluster.service import cluster_service
        await cluster_service.stop()
    except Exception:
        pass

    # Stop archive service
    try:
        from app.storage.archive_service import archive_service
        await archive_service.stop()
    except Exception:
        pass

    logger.info("Shutdown complete")


# ══════════════════════════════════════════════════════════════════════
# App creation
# ══════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Vizor NVR",
    description=(
        "Vizor NVR REST API. ONVIF Profile S/T compliant. "
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


# ── License gate ─────────────────────────────────────────────────────
# Added before CORS so its 403 "license_required" responses are wrapped by
# the CORS middleware (Starlette applies the first-added middleware as the
# innermost layer). Blocks all data APIs until a valid license is installed.
from app.core.license_gate import LicenseGateMiddleware
app.add_middleware(LicenseGateMiddleware)

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
# Exposes /metrics for scraping. Domain metrics are defined alongside the
# producing service. Avoid prometheus-fastapi-instrumentator middleware here:
# with nested FastAPI routers it can see an internal _IncludedRouter object and
# fail normal API requests while resolving route names.
try:
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    logger.info("Prometheus /metrics endpoint enabled")
except ImportError:
    logger.warning(
        "prometheus_client not installed; /metrics disabled"
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
from app.spot_output.router import router as spot_output_router

app.include_router(auth_router, prefix="/api")
app.include_router(snapshots_router, prefix="/api")
app.include_router(cameras_router, prefix="/api")
from app.cameras.pos_router import router as pos_router
app.include_router(pos_router, prefix="/api")
app.include_router(recordings_router, prefix="/api")
app.include_router(bookmarks_router, prefix="/api")
app.include_router(events_router, prefix="/api")
app.include_router(storage_router, prefix="/api")
from app.cluster.router import router as cluster_router
app.include_router(cluster_router, prefix="/api")
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
if settings.ENABLE_AI_MODULES:
    from app.ai.core.router import router as ai_router
    from app.ai.core.camera_config_router import router as ai_camera_config_router
    from app.ai.frs.query_router import router as ai_frs_query_router
    from app.ai.frs.router import router as ai_frs_router
    from app.ai.frs.recognize_router import router as ai_frs_recognize_router
    from app.ai.frs.investigate_router import router as ai_frs_investigate_router
    from app.ai.frs.transit_router import router as ai_frs_transit_router
    from app.ai.ppe.router import router as ai_ppe_router

    app.include_router(ai_router)
    app.include_router(ai_camera_config_router)
    app.include_router(ai_frs_query_router)
    app.include_router(ai_frs_router)
    app.include_router(ai_frs_recognize_router)
    app.include_router(ai_frs_investigate_router)
    app.include_router(ai_frs_transit_router)
    app.include_router(ai_ppe_router)
app.include_router(schedule_templates_router, prefix="/api")
app.include_router(spot_output_router, prefix="/api")

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
async def get_swagger_ui():
    """Branded Swagger UI shell. The HTML itself carries no API data — the
    schema is fetched from the admin-gated /api/openapi.json with a bearer
    token (see requestInterceptor below), so docs stay restricted to admins
    while the page can still load via direct browser navigation."""
    html = """<!DOCTYPE html>
<html>
<head>
  <title>Vizor NVR API &middot; Swagger</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" >
  <style>
    /* ── Vizor NVR — forced dark theme (no light mode, no toggle) ───────── */
    :root { color-scheme: dark; }
    body { margin: 0; background: #0f172a; }
    .swagger-ui, .swagger-ui .info, .swagger-ui .scheme-container { background: #0f172a; }
    /* topbar / branding */
    .swagger-ui .topbar { background: #0b1220; border-bottom: 1px solid #1e293b; }
    .swagger-ui .topbar .download-url-wrapper { display: none; }
    .swagger-ui .topbar-wrapper img { content: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%2314b8a6" width="32" height="32"><circle cx="12" cy="12" r="10"/></svg>'); }
    .swagger-ui .topbar-wrapper a::after { content: " Vizor NVR"; color: #14b8a6; font-weight: 700; font-size: 1.1rem; margin-left: 8px; }
    /* global text colour */
    .swagger-ui, .swagger-ui .info .title, .swagger-ui .info li, .swagger-ui .info p,
    .swagger-ui .info table, .swagger-ui label, .swagger-ui .opblock-tag,
    .swagger-ui .opblock .opblock-summary-operation-id,
    .swagger-ui .opblock .opblock-summary-path,
    .swagger-ui .opblock .opblock-summary-path__deprecated,
    .swagger-ui .opblock .opblock-summary-description,
    .swagger-ui .opblock-description-wrapper p, .swagger-ui .opblock-external-docs-wrapper p,
    .swagger-ui .opblock-title_normal p, .swagger-ui table thead tr td,
    .swagger-ui table thead tr th, .swagger-ui .parameter__name, .swagger-ui .parameter__type,
    .swagger-ui .response-col_status, .swagger-ui .response-col_description,
    .swagger-ui .responses-inner h4, .swagger-ui .responses-inner h5,
    .swagger-ui .tab li, .swagger-ui .markdown p, .swagger-ui .markdown li,
    .swagger-ui .model, .swagger-ui .model-title, .swagger-ui section.models h4,
    .swagger-ui .parameter__in, .swagger-ui .prop-type { color: #e2e8f0; }
    .swagger-ui .opblock-tag small, .swagger-ui .info .base-url,
    .swagger-ui .parameter__type, .swagger-ui .renderedMarkdown code { color: #94a3b8; }
    .swagger-ui svg, .swagger-ui .opblock-tag svg, .swagger-ui .expand-operation svg,
    .swagger-ui .model-toggle:after { fill: #94a3b8; filter: invert(0.85); }
    /* section / tag headers */
    .swagger-ui .opblock-tag { border-bottom: 1px solid #1e293b; }
    /* operation blocks */
    .swagger-ui .opblock { background: #111c30; border: 1px solid #1e293b; box-shadow: none; }
    .swagger-ui .opblock .opblock-section-header { background: #16233b; border-bottom: 1px solid #1e293b; }
    .swagger-ui .opblock .opblock-section-header h4, .swagger-ui .opblock .opblock-section-header label { color: #e2e8f0; }
    .swagger-ui .opblock.opblock-get { border-color: #1d4ed8; background: rgba(37,99,235,.08); }
    .swagger-ui .opblock.opblock-post { border-color: #15803d; background: rgba(34,197,94,.08); }
    .swagger-ui .opblock.opblock-put { border-color: #b45309; background: rgba(217,119,6,.08); }
    .swagger-ui .opblock.opblock-delete { border-color: #b91c1c; background: rgba(239,68,68,.08); }
    /* tables / models / inputs */
    .swagger-ui table thead tr td, .swagger-ui table thead tr th { border-bottom: 1px solid #1e293b; }
    .swagger-ui .model-box, .swagger-ui section.models, .swagger-ui section.models.is-open h4 { background: #111c30; border-color: #1e293b; }
    .swagger-ui section.models { border: 1px solid #1e293b; }
    .swagger-ui input[type=text], .swagger-ui input[type=password], .swagger-ui input[type=email],
    .swagger-ui textarea, .swagger-ui select {
      background: #0b1220; color: #e2e8f0; border: 1px solid #334155;
    }
    .swagger-ui .microlight { background: #0b1220; color: #e2e8f0; }
    .swagger-ui .highlight-code { background: #0b1220; }
    /* responses / dialogs */
    .swagger-ui .responses-inner { background: transparent; }
    .swagger-ui .dialog-ux .modal-ux { background: #111c30; border: 1px solid #1e293b; }
    .swagger-ui .dialog-ux .modal-ux-header h3, .swagger-ui .dialog-ux .modal-ux-content h4,
    .swagger-ui .dialog-ux .modal-ux-content p { color: #e2e8f0; }
    /* authorize button keeps brand accent */
    .swagger-ui .btn.authorize { color: #14b8a6; border-color: #14b8a6; }
    .swagger-ui .btn.authorize svg { fill: #14b8a6; filter: none; }
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
          const token = localStorage.getItem('nvr_token');
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
async def get_redoc_ui():
    """Branded ReDoc shell. Schema comes from the admin-gated
    /api/openapi.json, so the docs themselves remain admin-restricted."""
    html = """<!DOCTYPE html>
<html>
<head>
  <title>Vizor NVR API &middot; ReDoc</title>
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
    from app.cluster.service import cluster_service
    go2rtc_ok = await go2rtc_manager.is_healthy()
    return {
        "status": "ok",
        "version": __version__,
        "go2rtc": "connected" if go2rtc_ok else "disconnected",
        "active_recordings": ffmpeg_manager.active_count,
        "cluster_role": cluster_service.role,
        "cluster_node": cluster_service.node_id,
    }
