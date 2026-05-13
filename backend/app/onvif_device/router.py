# =============================================================================
# ONVIF Device Router — SOAP endpoints for each ONVIF service
# =============================================================================

from fastapi import APIRouter, Request, Response

from app.onvif_device.service import onvif_device_service

router = APIRouter(tags=["ONVIF Device"])

# Paths must match the XAddr advertised in GetCapabilities / GetServices
SERVICE_PATHS = [
    "/onvif/device_service",
    "/onvif/media_service",
    "/onvif/media2_service",
    "/onvif/recording_service",
    "/onvif/search_service",
    "/onvif/replay_service",
    "/onvif/event_service",
]


def _make_handler(path: str):
    async def handler(request: Request):
        return await onvif_device_service.handle(path, request)
    return handler


for _path in SERVICE_PATHS:
    router.post(_path)(_make_handler(_path))
