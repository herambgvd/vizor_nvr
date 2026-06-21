"""Suspect Search feature settings — operator-facing (service-token gated).

GET/PUT the public-dashboard + third-party ingest toggles, mint/rotate the
ingest API key, and return the sample ingest payload for the Settings UI. Backed
by the SDK-compatible (psycopg2) settings store. This is the ONLY /settings
surface SS exposes — there is no pre-existing detection-config /settings router.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from db.public_store import SAMPLE_INGEST_PAYLOAD, store
from deps.auth import require_service_token

router = APIRouter(prefix="/settings", tags=["settings"],
                   dependencies=[Depends(require_service_token)])


def _block() -> dict:
    st = store.get()
    return {
        "public_dashboard_enabled": st["public_dashboard_enabled"],
        "ingest_api_enabled": st["ingest_api_enabled"],
        "public_show_names": st["public_show_names"],
        # Key returned so the operator can copy it into the third-party system.
        "ingest_api_key": st["ingest_api_key"],
        "sample_ingest_payload": SAMPLE_INGEST_PAYLOAD,
    }


@router.get("")
def read_settings() -> dict:
    return _block()


@router.put("")
def write_settings(body: dict = Body(...)) -> dict:
    patch = {k: bool(body[k]) for k in
             ("public_dashboard_enabled", "ingest_api_enabled", "public_show_names")
             if k in body}
    if patch:
        store.update(**patch)
    return _block()


@router.post("/ingest-key/rotate")
def rotate_key() -> dict:
    return {"ingest_api_key": store.rotate_key()}
