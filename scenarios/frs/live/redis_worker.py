"""FRS Redis worker — drives the proven recognition pipeline under the vizor-gpu
worker framework (BaseWorker), emitting events onto the `ai:events` Redis stream
instead of writing Postgres inline.

Why: the legacy live path could wedge when Triton stalled (HTTP infer, no timeout).
This worker runs the SAME recognition pipeline (SCRFD → ByteTrack → vote → ArcFace
→ quality/liveness gates → snapshot + qdrant index) per camera, but:

  * frames arrive via the framework's per-camera asyncio task + watchdog,
  * each event is EMITTED to ai:events (the events bridge does record_event +
    attendance + transit on the app side, off the worker),
  * snapshot-save + qdrant snapshot-index still run inline in the worker (it has
    the frame + clients); only the Postgres write + transit-drive are deferred to
    the bridge via the emitted Event.

Recognition behaviour is byte-for-byte the legacy pipeline — only the event
transport changes.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import config
from vizor_sdk.worker import BaseWorker, Command, Event

from .async_pipeline import FrsPipeline

logger = logging.getLogger("frs.redis_worker")

USE_CASE = "frs"


class _EmitPipeline(FrsPipeline):
    """FrsPipeline whose event sinks buffer Events instead of writing Postgres.
    `process(frame)` runs the full recognition pipeline; the buffered events are
    drained by the worker and emitted to ai:events."""

    def __init__(self, cam: dict) -> None:
        super().__init__(cam)
        self._pending: list[Event] = []

    # Override the seam: buffer an Event carrying everything the bridge's
    # record_event call needs. Return a synthetic id (used by _index_snapshot —
    # the snapshot index is keyed by it; the bridge re-keys to the real event id
    # via attributes.client_event_id).
    def _sink_event(self, camera_id, person_id, person_name, confidence, snapshot_path,
                    event_type, ts, bbox=None, attributes=None, direction=None) -> str:
        ev = Event(
            use_case=USE_CASE,
            sub_feature=("detection" if event_type == "face_detected" else "recognition"),
            device_id=camera_id or "",
            event_type=event_type,
            timestamp=ts if isinstance(ts, datetime) else datetime.now(timezone.utc),
            data={
                "person_id": person_id,
                "person_name": person_name,
                "confidence": confidence,
                "snapshot_path": snapshot_path,
                "bbox": bbox,
                "attributes": attributes or {},
                "direction": direction,
            },
        )
        self._pending.append(ev)
        return str(ev.id)

    def _sink_transit(self, person_id, camera_id, ts, person_name=None, snapshot_key=None) -> None:
        # Transit is driven on the app side by the bridge when it sees a recognised
        # event; carry the hint so the bridge knows to drive transit for this person.
        ev = Event(
            use_case=USE_CASE,
            sub_feature="transit",
            device_id=camera_id or "",
            event_type="transit_drive",
            timestamp=ts if isinstance(ts, datetime) else datetime.now(timezone.utc),
            data={
                "person_id": person_id,
                "person_name": person_name,
                "snapshot_key": snapshot_key,
            },
        )
        self._pending.append(ev)

    def drain(self) -> list[Event]:
        out = self._pending
        self._pending = []
        return out


class FrsWorker(BaseWorker):
    """Per-camera FRS recognition under the worker framework."""

    use_case = USE_CASE

    def __init__(self, redis_url: str, **kw: Any) -> None:
        super().__init__(redis_url, **kw)
        # gRPC Triton client (hard-timeout) shared across cameras, wired with a
        # circuit breaker so repeated Triton failures short-circuit.
        from vizor_sdk.worker import TritonClient, default_grpc_url, CircuitBreaker
        self._triton = TritonClient(default_grpc_url(), breaker=CircuitBreaker("triton"))
        self._pipelines: dict[str, _EmitPipeline] = {}
        # DEDICATED recognition executor — separate from the default asyncio
        # to_thread pool that the cpp decoder's next_frame() borrows. Running the
        # heavy sync recognition on the shared pool starved the decoder's threads, so
        # next_frame() never got a slot and the camera loop stalled after 1 frame
        # (vizor-gpu sidesteps this with a fully-async pipeline; we isolate the pool).
        from concurrent.futures import ThreadPoolExecutor
        n = max(2, min(8, (os.cpu_count() or 4)))
        self._reco_pool = ThreadPoolExecutor(max_workers=n, thread_name_prefix="frs-reco")

    async def on_warmup(self) -> None:
        # Wait for the models the pipeline needs so the first real frame doesn't pay
        # cold-start, and the heartbeat reports healthy only once Triton is up.
        models = ["scrfd_10g", "arcface_r50"]
        if os.getenv("FRS_LIVENESS_ENABLED", "0") not in ("0", "false", "no"):
            models.append("antispoofing")
        ready = await self.wait_for_models(self._triton, models, timeout_s=180.0)
        logger.info("[frs] warmup models ready: %s", sorted(ready))

    def _pipeline_for(self, cmd: Command) -> _EmitPipeline:
        pl = self._pipelines.get(cmd.device_id)
        if pl is None:
            cam = {
                "camera_id": cmd.device_id,
                "camera_name": cmd.config.get("camera_name", cmd.device_id),
                "config": cmd.config,
            }
            pl = _EmitPipeline(cam)
            self._pipelines[cmd.device_id] = pl
        return pl

    async def process_frame(self, cmd: Command, frame: Any) -> AsyncIterator[Event]:
        pl = self._pipeline_for(cmd)
        # Run recognition on the DEDICATED pool (not the default to_thread pool the
        # cpp decoder uses) so decode + control plane never starve.
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._reco_pool, pl.process, frame)
        for ev in pl.drain():
            yield ev

    async def on_config_update(self, cmd: Command) -> None:
        await super().on_config_update(cmd)
        # Rebuild the pipeline so new ROI/thresholds/fps take effect.
        self._pipelines.pop(cmd.device_id, None)

    async def on_camera_stopped(self, device_id: str) -> None:
        self._pipelines.pop(device_id, None)

    async def on_shutdown(self) -> None:
        try:
            await self._triton.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._reco_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    redis_url = os.environ.get("AI_REDIS_URL", "redis://ai-redis:6379/0")
    import asyncio
    asyncio.run(FrsWorker(redis_url).run())


if __name__ == "__main__":
    main()
