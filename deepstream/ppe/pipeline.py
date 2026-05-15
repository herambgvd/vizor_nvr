"""
DeepStream PPE Compliance pipeline.

Phase 7 scaffold:
  - Bootstraps cameras with `ppe` scenario enabled
  - SIMULATE mode emits synthetic ppe_violation events for testing
  - Real pipeline: PGIE = yolov12m (person) → SGIE = ppe_classifier
    (per-person multi-label classification) → emit violation if any
    required item missing for `violation_grace_frames` consecutive frames.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import signal
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import redis.asyncio as aioredis

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-8s  %(name)-20s  %(message)s",
)
logger = logging.getLogger("ds-ppe")


REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
AI_EVENT_STREAM = os.environ.get("AI_EVENT_STREAM", "ai:events")
CONTROL_CHANNEL = os.environ.get("AI_CONTROL_CHANNEL", "ai:control:reload")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/")
BACKEND_API_KEY = os.environ.get("BACKEND_API_KEY", "")
SIMULATE = os.environ.get("SIMULATE", "0") == "1"
SIM_INTERVAL = float(os.environ.get("SIM_INTERVAL", "12"))

PPE_ITEMS = ["helmet", "vest", "mask", "gloves", "goggles", "boots"]


class Worker:
    def __init__(self) -> None:
        self.redis: Optional[aioredis.Redis] = None
        self.http: Optional[httpx.AsyncClient] = None
        self.cameras: List[Dict[str, Any]] = []
        # camera_id → required_items list (from config)
        self.required_items: Dict[str, List[str]] = {}
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        headers = {}
        if BACKEND_API_KEY:
            headers["X-Vizor-API-Key"] = BACKEND_API_KEY
        self.http = httpx.AsyncClient(
            base_url=BACKEND_URL, headers=headers, timeout=10.0,
        )
        await self.reload_config()

    async def stop(self) -> None:
        self._stop.set()
        if self.http:
            await self.http.aclose()
        if self.redis:
            await self.redis.aclose()

    async def reload_config(self) -> None:
        try:
            r = await self.http.get(
                "/api/ai/cameras/active",
                params={"scenario": "ppe"},
            )
            if r.status_code == 200:
                payload = r.json()
                self.cameras = payload.get("cameras", []) or []
            else:
                logger.warning("backend /active returned %d", r.status_code)
                self.cameras = []
        except Exception as e:
            logger.warning("reload_config failed: %s", e)

        # Per-camera required items — pulled from each camera's config
        self.required_items = {}
        for cam in self.cameras:
            try:
                cr = await self.http.get(
                    f"/api/ai/cameras/{cam['id']}/scenarios",
                )
                if cr.status_code == 200:
                    for entry in cr.json():
                        if entry.get("scenario_slug") == "ppe":
                            cfg = entry.get("config") or {}
                            self.required_items[cam["id"]] = (
                                cfg.get("required_items") or ["helmet", "vest"]
                            )
            except Exception:
                self.required_items[cam["id"]] = ["helmet", "vest"]

        logger.info(
            "reload_config: %d PPE-enabled cameras", len(self.cameras),
        )

    async def emit(self, payload: Dict[str, Any]) -> None:
        try:
            await self.redis.xadd(  # type: ignore
                AI_EVENT_STREAM,
                {"payload": json.dumps(payload, default=str)},
                maxlen=50000,
                approximate=True,
            )
        except Exception:
            logger.exception("xadd failed")

    async def control_loop(self) -> None:
        try:
            pubsub = self.redis.pubsub()  # type: ignore
            await pubsub.subscribe(CONTROL_CHANNEL)
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    logger.info("control reload received")
                    await self.reload_config()
                if self._stop.is_set():
                    break
        except Exception:
            logger.exception("control_loop crashed")

    async def simulate_loop(self) -> None:
        """Synthetic PPE violations — pick random camera + random subset
        of required items as 'missing'."""
        while not self._stop.is_set():
            for cam in self.cameras:
                cid = cam["id"]
                required = self.required_items.get(cid, ["helmet", "vest"])
                if random.random() < 0.6:
                    # Pick 1-2 random items as missing
                    n_missing = random.randint(1, min(2, len(required)))
                    missing = random.sample(required, n_missing)
                    payload = {
                        "type": "ppe_violation",
                        "analyticsModule": "ppe",
                        "sensorId": cid,
                        "missing_items": missing,
                        "required_items": required,
                        "confidence": round(random.uniform(0.55, 0.95), 3),
                        "trackingId": random.randint(1, 9999),
                        "severity": "warning",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    await self.emit(payload)
            await asyncio.sleep(SIM_INTERVAL)

    async def run(self) -> None:
        await self.start()
        tasks = [asyncio.create_task(self.control_loop())]
        if SIMULATE:
            logger.warning("SIMULATE=1 — emitting synthetic PPE violations every %ss", SIM_INTERVAL)
            tasks.append(asyncio.create_task(self.simulate_loop()))
        else:
            logger.info("DeepStream PPE pipeline TODO — placeholder. Set SIMULATE=1 for testing")
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self.stop()


async def main() -> None:
    w = Worker()

    def _shutdown(*_):
        w._stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    try:
        await w.run()
    finally:
        await w.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
