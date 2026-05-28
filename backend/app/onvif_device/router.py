# =============================================================================
# ONVIF Device Router — SOAP endpoints for each ONVIF service
# =============================================================================

from fastapi import APIRouter, Request, Response
from typing import Optional

from app.onvif_device.service import onvif_device_service

router = APIRouter(tags=["ONVIF Device"])

# Paths must match the XAddr advertised in GetCapabilities / GetServices
SERVICE_PATHS = [
    "/onvif/device_service",
    "/onvif/media_service",
    "/onvif/media2_service",
    "/onvif/ptz_service",
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


@router.post("/onvif/test/inject_event", include_in_schema=False)
async def inject_test_event(
    camera_id: str = "test",
    topic: str = "tns1:VideoSource/MotionAlarm",
):
    """Internal test endpoint: inject a synthetic event into all active PullPoint queues."""
    from datetime import datetime, timezone
    from app.onvif_device.service import subscription_queues
    evt = {
        "topic": topic,
        "camera_id": camera_id,
        "source": f"camera:{camera_id}",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "value": "true",
        "metadata": {"injected": "true"},
    }
    count = 0
    for q in list(subscription_queues.values()):
        try:
            q.put_nowait(evt)
            count += 1
        except Exception:
            pass
    return {"queues_notified": count, "active_subscriptions": len(subscription_queues)}
