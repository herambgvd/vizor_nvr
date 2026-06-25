"""PPE Redis worker — drives the proven PPE pipeline under the vizor-gpu worker
framework (BaseWorker), emitting events onto `ai:events` instead of writing inline.

PpePipeline already buffers its events and `process(frame)` returns them as a list of
dicts (no seam refactor needed, unlike FRS). This worker wraps each dict into an
Event and yields it; the PPE events bridge does record_event on the app side. The
detector uses the gRPC Triton client (hard per-call timeout) so a stalled Triton
can't wedge the camera task. Snapshot saves stay inline in the pipeline.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from vizor_sdk.worker import BaseWorker, Command, Event

from .async_pipeline import PpePipeline

logger = logging.getLogger("ppe.redis_worker")

USE_CASE = "ppe"


class PpeWorker(BaseWorker):
    use_case = USE_CASE

    def __init__(self, redis_url: str, **kw: Any) -> None:
        super().__init__(redis_url, **kw)
        self._pipelines: dict[str, PpePipeline] = {}
        # Dedicated recognition pool, separate from the default to_thread pool the
        # cpp decoder uses — otherwise heavy sync detection starves next_frame() and
        # the camera loop stalls after one frame.
        from concurrent.futures import ThreadPoolExecutor
        import os as _os
        n = max(2, min(8, (_os.cpu_count() or 4)))
        self._reco_pool = ThreadPoolExecutor(max_workers=n, thread_name_prefix="ppe-reco")

    async def on_warmup(self) -> None:
        # The PPE detector connects lazily; nudge Triton readiness for the model so
        # the heartbeat only reports healthy once it's loadable. Uses the detector's
        # own gRPC client (set via VIZOR_TRITON_GRPC + TRITON_GRPC_URL).
        try:
            import asyncio
            import config
            from inference.triton_engine import detector
            model = config.PPE_MODEL_NAME
            for _ in range(60):  # up to ~180s
                if await asyncio.to_thread(detector.ready):
                    logger.info("[ppe] warmup: model %s ready", model)
                    return
                await asyncio.sleep(3.0)
            logger.warning("[ppe] warmup: model not ready after wait")
        except Exception as e:  # noqa: BLE001
            logger.warning("[ppe] warmup failed (non-fatal): %s", e)

    def _pipeline_for(self, cmd: Command) -> PpePipeline:
        pl = self._pipelines.get(cmd.device_id)
        if pl is None:
            cam = {
                "camera_id": cmd.device_id,
                "config_id": cmd.config.get("config_id"),
                "config": cmd.config,
            }
            pl = PpePipeline(cam)
            self._pipelines[cmd.device_id] = pl
        return pl

    async def process_frame(self, cmd: Command, frame: Any) -> AsyncIterator[Event]:
        import asyncio
        pl = self._pipeline_for(cmd)
        loop = asyncio.get_running_loop()
        events = await loop.run_in_executor(self._reco_pool, pl.process, frame)
        for e in events or []:
            yield Event(
                use_case=USE_CASE,
                sub_feature=("detection" if e.get("event_type") == "ppe_compliant" else "violation"),
                device_id=e.get("camera_id") or cmd.device_id,
                event_type=e.get("event_type", "ppe_missing"),
                timestamp=datetime.now(timezone.utc),
                data={
                    "worker_track_id": e.get("worker_track_id"),
                    "ppe_item": e.get("ppe_item"),
                    "missing_items": e.get("missing_items"),
                    "present_items": e.get("present_items"),
                    "confidence": e.get("confidence"),
                    "snapshot_path": e.get("snapshot_path"),
                    "bbox": e.get("bbox"),
                },
            )

    async def on_config_update(self, cmd: Command) -> None:
        await super().on_config_update(cmd)
        self._pipelines.pop(cmd.device_id, None)

    async def on_camera_stopped(self, device_id: str) -> None:
        self._pipelines.pop(device_id, None)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Force the PPE detector onto gRPC inside the worker process.
    os.environ.setdefault("VIZOR_TRITON_GRPC", "1")
    redis_url = os.environ.get("AI_REDIS_URL", "redis://ai-redis:6379/0")
    import asyncio
    asyncio.run(PpeWorker(redis_url).run())


if __name__ == "__main__":
    main()
