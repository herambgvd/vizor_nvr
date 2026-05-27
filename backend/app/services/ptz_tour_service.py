# =============================================================================
# PTZ Tour Service — per-camera preset patrol cycle
# =============================================================================
# Polls cameras with ptz_tour_enabled=True, walks through the ordered
# list of presets in ptz_tour_config.presets, calling GotoPreset for each
# then sleeping dwell_seconds.  Runs as a long-lived asyncio task; per-
# camera errors are warnings, not fatal.
# =============================================================================

import asyncio
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PTZTourService:
    """Background service that drives per-camera PTZ preset tours."""

    _POLL_INTERVAL = 5  # seconds between DB sweeps for enabled cameras

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        # Maps camera_id → asyncio.Task running that camera's tour loop
        self._tours: Dict[str, asyncio.Task] = {}
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._supervisor_loop(), name="ptz_tour_supervisor")
        logger.info("PTZ tour service started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Stop all per-camera loops
        for cid, t in list(self._tours.items()):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tours.clear()
        logger.info("PTZ tour service stopped")

    # ------------------------------------------------------------------
    # Internal supervisor
    # ------------------------------------------------------------------

    async def _supervisor_loop(self):
        """
        Every _POLL_INTERVAL seconds: query DB for cameras whose
        ptz_tour_enabled flag changed, start/stop individual tour tasks.
        """
        while self._running:
            try:
                await self._sync_tours()
            except Exception as exc:
                logger.warning("PTZ tour supervisor error: %s", exc)
            await asyncio.sleep(self._POLL_INTERVAL)

    async def _sync_tours(self):
        from app.database import async_session_maker
        from app.cameras.models import Camera
        from sqlalchemy import select

        async with async_session_maker() as db:
            result = await db.execute(
                select(Camera).where(Camera.is_enabled.is_(True))
            )
            cameras = result.scalars().all()

        enabled_ids = set()
        for cam in cameras:
            # ptz_tour_enabled may not exist on older schema rows; default False
            enabled = getattr(cam, "ptz_tour_enabled", False) or False
            config = getattr(cam, "ptz_tour_config", None) or {}
            presets = config.get("presets", []) if isinstance(config, dict) else []

            if enabled and presets and cam.ptz_capable and cam.onvif_host:
                enabled_ids.add(cam.id)
                if cam.id not in self._tours or self._tours[cam.id].done():
                    self._tours[cam.id] = asyncio.create_task(
                        self._run_tour(cam.id),
                        name=f"ptz_tour_{cam.id}",
                    )

        # Stop tours for cameras no longer enabled
        for cid in list(self._tours.keys()):
            if cid not in enabled_ids:
                task = self._tours.pop(cid)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                logger.info("[%s] PTZ tour stopped (disabled/no presets)", cid)

    async def _run_tour(self, camera_id: str):
        """
        Continuously cycle through presets for one camera.
        Survives per-step errors; exits cleanly on cancellation.
        """
        from app.database import async_session_maker
        from app.cameras.models import Camera
        from app.cameras.onvif_service import onvif_service
        from app.core.crypto import decrypt_value
        from sqlalchemy import select

        logger.info("[%s] PTZ tour task started", camera_id)
        try:
            while True:
                # Reload camera from DB each loop to pick up config changes
                async with async_session_maker() as db:
                    result = await db.execute(
                        select(Camera).where(Camera.id == camera_id)
                    )
                    cam = result.scalar_one_or_none()

                if cam is None:
                    logger.info("[%s] Camera gone; stopping tour", camera_id)
                    return

                enabled = getattr(cam, "ptz_tour_enabled", False) or False
                config = getattr(cam, "ptz_tour_config", None) or {}
                if not enabled or not isinstance(config, dict):
                    logger.info("[%s] Tour disabled; stopping", camera_id)
                    return

                presets = config.get("presets", [])
                loop_tour = config.get("loop", True)
                if not presets:
                    await asyncio.sleep(10)
                    continue

                host = cam.onvif_host
                port = cam.onvif_port or 80
                username = decrypt_value(cam.onvif_username) if cam.onvif_username else ""
                password = decrypt_value(cam.onvif_password) if cam.onvif_password else ""
                profile_token = cam.onvif_profile_token  # may be None

                for preset in presets:
                    token = preset.get("token")
                    dwell = int(preset.get("dwell_seconds", 10))
                    if not token:
                        continue
                    try:
                        ok = await onvif_service.goto_preset(
                            host, port, username, password,
                            token, profile_token=profile_token,
                        )
                        if not ok:
                            logger.warning("[%s] GotoPreset %s returned False", camera_id, token)
                    except Exception as exc:
                        logger.warning("[%s] GotoPreset %s error: %s", camera_id, token, exc)
                    await asyncio.sleep(dwell)

                if not loop_tour:
                    logger.info("[%s] PTZ tour finished (loop=false)", camera_id)
                    return

        except asyncio.CancelledError:
            logger.info("[%s] PTZ tour task cancelled", camera_id)
            raise
        except Exception as exc:
            logger.warning("[%s] PTZ tour task error: %s", camera_id, exc)


# Module singleton
ptz_tour_service = PTZTourService()
