"""
DeepStream FRS pipeline.

Phase 6 scaffold:
  - Bootstraps cameras with `frs` scenario enabled from backend
  - SIMULATE mode emits synthetic face_recognized events on a timer
  - Real GStreamer wiring same shape as people_counting/pipeline.py,
    only with PGIE = scrfd + SGIE = arcface + Qdrant lookup.

Real pipeline ships when Triton models + DeepStream image run on the
deploy host (Phase 7 verification on RTX 5060).
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
logger = logging.getLogger("ds-frs")


REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
AI_EVENT_STREAM = os.environ.get("AI_EVENT_STREAM", "ai:events")
CONTROL_CHANNEL = os.environ.get("AI_CONTROL_CHANNEL", "ai:control:reload")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/")
BACKEND_API_KEY = os.environ.get("BACKEND_API_KEY", "")
SIMULATE = os.environ.get("SIMULATE", "0") == "1"
SIM_INTERVAL = float(os.environ.get("SIM_INTERVAL", "15"))


class Worker:
    def __init__(self) -> None:
        self.redis: Optional[aioredis.Redis] = None
        self.http: Optional[httpx.AsyncClient] = None
        self.cameras: List[Dict[str, Any]] = []
        self.persons: List[Dict[str, Any]] = []
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
                params={"scenario": "frs"},
            )
            if r.status_code == 200:
                payload = r.json()
                self.cameras = payload.get("cameras", []) or []
            else:
                logger.warning("backend /active returned %d", r.status_code)
                self.cameras = []
        except Exception as e:
            logger.warning("reload_config failed: %s", e)

        # Pull person list for SIMULATE
        try:
            r = await self.http.get("/api/ai/frs/persons")
            if r.status_code == 200:
                self.persons = r.json() or []
        except Exception:
            pass

        logger.info(
            "reload_config: %d FRS-enabled cameras, %d enrolled persons",
            len(self.cameras), len(self.persons),
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
        """Synthetic face_recognized events for dev — picks random
        camera + enrolled person + confidence."""
        while not self._stop.is_set():
            if self.cameras and self.persons:
                cam = random.choice(self.cameras)
                person = random.choice(self.persons)
                conf = round(random.uniform(0.55, 0.95), 3)
                payload = {
                    "type": "face_recognized",
                    "analyticsModule": "frs",
                    "sensorId": cam["id"],
                    "personId": person.get("id"),
                    "confidence": conf,
                    "trackingId": random.randint(1, 9999),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                # Occasionally emit a face_alert if person belongs to a watchlist
                if random.random() < 0.15:
                    payload["type"] = "face_alert"
                    payload["severity"] = "warning"
                await self.emit(payload)
            await asyncio.sleep(SIM_INTERVAL)

    async def run(self) -> None:
        await self.start()
        tasks = [asyncio.create_task(self.control_loop())]
        if SIMULATE:
            logger.warning("SIMULATE=1 — emitting synthetic FRS events every %ss", SIM_INTERVAL)
            tasks.append(asyncio.create_task(self.simulate_loop()))
        else:
            logger.info("DeepStream FRS pipeline TODO — placeholder. Set SIMULATE=1 for testing")
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
