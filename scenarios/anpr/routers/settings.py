"""ANPR feature settings — operator-facing (service-token gated via the NVR proxy).

Read/update the region/plate-regex, raw-read + low-light toggles, det/ocr
thresholds, min-reads, and the speed-estimation enable flag (speed itself is
calibrated per camera in the camera config — see scenario.json)."""
from __future__ import annotations

import re

from fastapi import APIRouter, Body, Depends, HTTPException

from db.public_store import SAMPLE_INGEST_PAYLOAD, store as public_store
from db.settings_store import get_settings, update_settings
from deps import require_service_token

router = APIRouter(prefix="/settings", tags=["settings"],
                   dependencies=[Depends(require_service_token)])


def _public_block() -> dict:
    st = public_store.get()
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
    return {**get_settings(), **_public_block()}


@router.put("")
def write_settings(body: dict = Body(...)) -> dict:
    patch = {}
    if "region" in body and body["region"]:
        patch["region"] = str(body["region"])[:16]
    if "plate_regex" in body and body["plate_regex"]:
        pattern = str(body["plate_regex"])
        try:
            re.compile(pattern)
        except re.error as exc:
            raise HTTPException(400, f"invalid plate_regex: {exc}")
        patch["plate_regex"] = pattern
    for k in ("allow_raw_reads", "lowlight_enhance", "speed_enabled"):
        if k in body:
            patch[k] = bool(body[k])
    for k in ("det_conf", "ocr_conf"):
        if k in body and body[k] is not None:
            try:
                patch[k] = float(body[k])
            except (TypeError, ValueError):
                pass
    for k in ("min_plate_w", "min_reads"):
        if k in body and body[k] is not None:
            try:
                patch[k] = int(body[k])
            except (TypeError, ValueError):
                pass
    st = update_settings(**patch)

    # Public / ingest toggles go to the SDK store (separate columns, same row).
    public_patch = {k: bool(body[k]) for k in
                    ("public_dashboard_enabled", "ingest_api_enabled",
                     "public_show_names") if k in body}
    if public_patch:
        public_store.update(**public_patch)

    return {**st, **_public_block()}


@router.post("/ingest-key/rotate")
def rotate_key() -> dict:
    return {"ingest_api_key": public_store.rotate_key()}
