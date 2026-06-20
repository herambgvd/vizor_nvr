"""BaseScenarioApp — the FastAPI scaffold every plugin shares.

Gives a plugin a ready app with: standard /health (+ Triton status), manifest
self-registration on boot, and a place to hang scenario routers. The plugin
supplies its slug, version, manifest path, and (optionally) a health-detail
callback + startup/shutdown hooks.

    from vizor_sdk.app import build_app
    from vizor_sdk.nvr import NvrClient
    app = build_app(
        title="Vizor ANPR", slug="anpr", version="1.0.0",
        manifest_path=config.MANIFEST_PATH,
        nvr=NvrClient(config.VIZOR_BASE_URL, config.VIZOR_API_KEY, "anpr"),
        routers=[plates.router],
        health_detail=lambda: {"triton": engine.status()},
        on_startup=[live.start], on_shutdown=[live.stop],
    )
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional, Sequence

from fastapi import FastAPI

from .nvr import NvrClient

logger = logging.getLogger(__name__)


def build_app(
    *,
    title: str,
    slug: str,
    version: str,
    manifest_path: Optional[str | Path] = None,
    nvr: Optional[NvrClient] = None,
    routers: Sequence = (),
    health_detail: Optional[Callable[[], dict]] = None,
    on_startup: Sequence[Callable] = (),
    on_shutdown: Sequence[Callable] = (),
) -> FastAPI:
    """Construct a standardized scenario FastAPI app."""
    app = FastAPI(title=title, version=version)

    for r in routers:
        app.include_router(r)

    @app.get("/health")
    def health() -> dict:
        out = {"scenario": slug, "version": version, "status": "ok"}
        if health_detail:
            try:
                out.update(health_detail() or {})
            except Exception as exc:  # noqa: BLE001 — health must never 500
                out["health_detail_error"] = str(exc)
        return out

    @app.on_event("startup")
    async def _startup() -> None:  # noqa: ANN202
        # Register manifest with the NVR catalog (best-effort, backs off).
        if nvr and manifest_path:
            try:
                nvr.register_manifest(manifest_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] manifest registration error: %s", slug, exc)
        for hook in on_startup:
            await _run_hook(hook)

    @app.on_event("shutdown")
    async def _shutdown() -> None:  # noqa: ANN202
        for hook in on_shutdown:
            await _run_hook(hook)

    return app


async def _run_hook(hook: Callable) -> None:
    """Run a startup/shutdown hook whether it's sync or async."""
    import inspect

    try:
        res = hook()
        if inspect.isawaitable(res):
            await res
    except Exception as exc:  # noqa: BLE001 — a bad hook must not abort boot/stop
        logger.warning("scenario lifecycle hook %r failed: %s", hook, exc)
