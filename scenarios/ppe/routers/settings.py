"""PPE feature settings — operator-facing (service-token gated via the NVR proxy).

Read/update the default required-PPE set, the optional positive-compliant-event
toggle, and the temporal thresholds (grace / min-present / cooldown)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from db.settings_store import get_settings, update_settings
from deps import require_service_token

router = APIRouter(prefix="/settings", tags=["settings"],
                   dependencies=[Depends(require_service_token)])

_PPE_OPTIONS = ["helmet", "vest"]


@router.get("")
def read_settings() -> dict:
    st = get_settings()
    return {**st, "ppe_options": _PPE_OPTIONS}


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
    return {**st, "ppe_options": _PPE_OPTIONS}
