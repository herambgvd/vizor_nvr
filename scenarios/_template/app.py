"""Scenario entrypoint — wire the SDK scaffold together. Usually unchanged.

The SDK's build_app gives you /health + manifest self-registration + lifecycle.
You only pass your slug/version, the manifest path, an NvrClient, your routers,
and a health-detail callback reporting model readiness.
"""
from __future__ import annotations

from vizor_sdk import NvrClient, build_app

import detect
from config.settings import config
from routers import scenario as scenario_router

nvr = NvrClient(config.VIZOR_BASE_URL, config.VIZOR_API_KEY, config.SLUG)

app = build_app(
    title=f"Vizor {config.SLUG.upper()}",
    slug=config.SLUG,
    version="1.0.0",
    manifest_path=config.MANIFEST_PATH,
    nvr=nvr,
    routers=[scenario_router.router],
    health_detail=lambda: {"inference": detect.status()},
    # For a live scenario, add the per-camera worker manager here:
    # on_startup=[live.start], on_shutdown=[live.stop],
)
