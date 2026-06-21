"""PPE feature settings — operator-facing (service-token gated via the NVR proxy).

Read/update the default required-PPE set, the optional positive-compliant-event
toggle, and the temporal thresholds (grace / min-present / cooldown). ALSO
exposes (merged into the same GET/PUT) the public-dashboard + third-party ingest
toggles, the ingest API key, and a rotate endpoint — backed by the SDK
SettingsStore so there is one /settings surface for the operator UI."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from db.public_store import SAMPLE_INGEST_PAYLOAD, store as public_store
from db.settings_store import get_settings, update_settings
from deps import require_service_token

router = APIRouter(prefix="/settings", tags=["settings"],
                   dependencies=[Depends(require_service_token)])

_PPE_OPTIONS = ["helmet", "vest"]


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
    st = get_settings()
    return {**st, "ppe_options": _PPE_OPTIONS, **_public_block()}


@router.put("")
def write_settings(body: dict = Body(...)) -> dict:
    patch = {}
    if "required_ppe" in body and isinstance(body["required_ppe"], list):
        patch["required_ppe"] = [str(x) for x in body["required_ppe"]]
    for k in ("emit_compliant",):
        if k in body:
            patch[k] = bool(body[k])
    for k in ("missing_grace", "min_present", "cooldown"):
        if k in body and body[k] is not None:
            try:
                patch[k] = float(body[k])
            except (TypeError, ValueError):
                pass
    st = update_settings(**patch)

    # Public / ingest toggles go to the SDK store (separate columns, same row).
    public_patch = {k: bool(body[k]) for k in
                    ("public_dashboard_enabled", "ingest_api_enabled",
                     "public_show_names") if k in body}
    if public_patch:
        public_store.update(**public_patch)

    return {**st, "ppe_options": _PPE_OPTIONS, **_public_block()}


@router.post("/ingest-key/rotate")
def rotate_key() -> dict:
    return {"ingest_api_key": public_store.rotate_key()}
