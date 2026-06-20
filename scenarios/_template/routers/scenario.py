"""Scenario HTTP routes — thin: validate, run detect+logic, return.

Add your scenario's endpoints here (e.g. an on-demand analyse, a results list).
Gate them behind the shared NVR service token, and scope reads to the operator's
allowed cameras — both via SDK dependencies.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from vizor_sdk import allowed_camera_ids, service_token_guard

from config.settings import config

require_token = service_token_guard(config.VIZOR_SERVICE_TOKEN)

router = APIRouter(
    prefix=f"/{config.SLUG}",
    tags=[config.SLUG],
    dependencies=[Depends(require_token)],
)


@router.get("/info")
def info(allowed: list[str] | None = Depends(allowed_camera_ids)) -> dict:
    """Example route: returns the scenario's config summary, scoped to the
    operator's allowed cameras (None = unscoped/internal)."""
    return {
        "scenario": config.SLUG,
        "model": config.DETECTOR_MODEL,
        "min_confidence": config.MIN_CONFIDENCE,
        "allowed_cameras": allowed,
    }
