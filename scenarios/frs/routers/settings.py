"""FRS feature settings — operator-facing (service-token gated via the NVR proxy).

Read/update the public-dashboard + ingest-API toggles, mint/rotate the ingest
API key, and return the sample ingest payload for the Settings UI.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from deps import require_service_token
from db.settings_store import get_settings, rotate_ingest_key, update_settings

router = APIRouter(prefix="/settings", tags=["settings"],
                   dependencies=[Depends(require_service_token)])


SAMPLE_INGEST_PAYLOAD = {
    "camera_id": "gate-1",
    "camera_name": "Main Gate",
    "person_external_id": "EMP1042",
    "person_name": "Ravi Kumar",
    "event_type": "face_recognized",
    "confidence": 0.91,
    "timestamp": "2026-06-20T14:30:00Z",
    "bbox": {"x": 100, "y": 80, "w": 120, "h": 140},
    "source": "hikvision-nvr",
    "attributes": {"site": "HQ"},
}


@router.get("")
def read_settings() -> dict:
    st = get_settings()
    return {
        "public_dashboard_enabled": st["public_dashboard_enabled"],
        "ingest_api_enabled": st["ingest_api_enabled"],
        "public_show_names": st["public_show_names"],
        # Key returned so the operator can copy it into the third-party system.
        "ingest_api_key": st["ingest_api_key"],
        "sample_ingest_payload": SAMPLE_INGEST_PAYLOAD,
    }


@router.put("")
def write_settings(body: dict = Body(...)) -> dict:
    patch = {k: body[k] for k in
             ("public_dashboard_enabled", "ingest_api_enabled", "public_show_names")
             if k in body}
    st = update_settings(**patch)
    return {**st, "sample_ingest_payload": SAMPLE_INGEST_PAYLOAD}


@router.post("/ingest-key/rotate")
def rotate_key() -> dict:
    return {"ingest_api_key": rotate_ingest_key()}
