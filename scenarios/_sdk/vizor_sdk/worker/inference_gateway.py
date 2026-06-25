"""InferenceGateway — single entry point for all Triton calls (ported from
vizor-gpu).

Wraps `TritonClient.infer()` with three edge-critical capabilities:

  1. Client-side request coalescing — opportunistically batch concurrent calls to
     the same model into one Triton request, amortising network + dispatch cost.
  2. Per-model concurrency cap — bounded inflight per model so N cameras don't queue
     more than the GPU can sensibly run.
  3. Adaptive frame-skip signal — `should_skip(model)` returns True when the gateway
     is over-subscribed OR the event loop is lagging, so pipelines drop a frame
     before wasting CPU on preprocessing for a result that'll arrive late.

Opt-in: pipelines that don't pass a gateway keep calling TritonClient.infer() direct.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("vizor.worker.inference_gateway")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


COALESCE_WINDOW_S = _env_float("VIZOR_INFER_COALESCE_WINDOW_S", 0.005)
COALESCE_MAX_BATCH = _env_int("VIZOR_INFER_COALESCE_MAX_BATCH", 8)
DEFAULT_INFLIGHT_CAP = _env_int("VIZOR_INFER_INFLIGHT_CAP", 4)
LOOP_LAG_SKIP_S = _env_float("VIZOR_INFER_LOOP_LAG_SKIP_S", 0.075)


@dataclass
class _PendingRequest:
    inputs: dict[str, np.ndarray]
    outputs: list[str]
    future: asyncio.Future
    enqueued_at: float


class InferenceGateway:
    """Per-worker singleton fronting a `TritonClient`. Construct ONCE per process."""

    def __init__(
        self,
        triton: Any,
        *,
        metrics: Optional[Any] = None,
        coalesce_window_s: float | None = None,
        coalesce_max_batch: int | None = None,
        inflight_cap: int | None = None,
    ) -> None:
        self.triton = triton
        self.metrics = metrics
        self.coalesce_window_s = COALESCE_WINDOW_S if coalesce_window_s is None else coalesce_window_s
        self.coalesce_max_batch = COALESCE_MAX_BATCH if coalesce_max_batch is None else coalesce_max_batch
        self.inflight_cap = DEFAULT_INFLIGHT_CAP if inflight_cap is None else inflight_cap

        self._queues: dict[str, deque[_PendingRequest]] = {}
        self._dispatchers: dict[str, asyncio.Task] = {}
        self._inflight: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._recent_latency: dict[str, deque[float]] = {}
        self._last_loop_lag: float = 0.0

    def _state(self, model_name: str) -> tuple[deque, asyncio.Lock]:
        q = self._queues.get(model_name)
        if q is None:
            q = deque()
            self._queues[model_name] = q
            self._inflight[model_name] = 0
            self._recent_latency[model_name] = deque(maxlen=32)
            self._locks[model_name] = asyncio.Lock()
        return q, self._locks[model_name]

    def update_loop_lag(self, lag_s: float) -> None:
        self._last_loop_lag = float(max(0.0, lag_s))

    def should_skip(self, model_name: str | None = None) -> bool:
        """True when the gateway suggests dropping a frame: loop lag over threshold,
        or this model's inflight is at/above cap."""
        if self._last_loop_lag > LOOP_LAG_SKIP_S:
            return True
        if model_name is None:
            return False
        return self._inflight.get(model_name, 0) >= self.inflight_cap

    async def infer(
        self, model_name: str, inputs: dict[str, np.ndarray], outputs: list[str],
        *, timeout: float | None = None, coalesce: bool = True,
    ) -> dict[str, np.ndarray]:
        if not coalesce:
            return await self._direct_infer(model_name, inputs, outputs, timeout)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        req = _PendingRequest(inputs=inputs, outputs=outputs, future=fut, enqueued_at=loop.time())
        q, _ = self._state(model_name)
        q.append(req)
        self._report_queue_depth(model_name)
        await self._ensure_dispatcher(model_name)
        return await fut

    async def _ensure_dispatcher(self, model_name: str) -> None:
        existing = self._dispatchers.get(model_name)
        if existing is not None and not existing.done():
            return
        loop = asyncio.get_running_loop()
        self._dispatchers[model_name] = loop.create_task(
            self._dispatch_loop(model_name), name=f"infer-gateway-{model_name}")

    async def _dispatch_loop(self, model_name: str) -> None:
        q, lock = self._state(model_name)
        try:
            while True:
                if not q:
                    return
                await asyncio.sleep(self.coalesce_window_s)
                async with lock:
                    if not q:
                        return
                    batch = []
                    while q and len(batch) < self.coalesce_max_batch:
                        batch.append(q.popleft())
                self._report_queue_depth(model_name)
                await self._fire_batch(model_name, batch)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("[infer-gateway] dispatcher crashed model=%s", model_name)
            while q:
                req = q.popleft()
                if not req.future.done():
                    req.future.set_exception(e)

    async def _fire_batch(self, model_name: str, batch: list[_PendingRequest]) -> None:
        if not batch:
            return
        self._inflight[model_name] = self._inflight.get(model_name, 0) + len(batch)
        self._report_inflight(model_name)
        t0 = time.perf_counter()
        try:
            if len(batch) == 1:
                req = batch[0]
                try:
                    res = await self.triton.infer(model_name, req.inputs, req.outputs)
                    if not req.future.done():
                        req.future.set_result(res)
                except Exception as e:
                    if not req.future.done():
                        req.future.set_exception(e)
                return
            try:
                stacked = self._stack_inputs(batch)
                outputs = batch[0].outputs
                res = await self.triton.infer(model_name, stacked, outputs)
                split = self._split_outputs(res, len(batch))
                for req, row in zip(batch, split):
                    if not req.future.done():
                        req.future.set_result(row)
            except Exception as e:
                logger.warning("[infer-gateway] batch fire failed model=%s bs=%d: %s",
                               model_name, len(batch), e)
                for req in batch:
                    try:
                        res = await self.triton.infer(model_name, req.inputs, req.outputs)
                        if not req.future.done():
                            req.future.set_result(res)
                    except Exception as e2:
                        if not req.future.done():
                            req.future.set_exception(e2)
        finally:
            self._inflight[model_name] = max(0, self._inflight.get(model_name, 0) - len(batch))
            self._report_inflight(model_name)
            latency = time.perf_counter() - t0
            self._recent_latency[model_name].append(latency)
            self._report_batch(model_name, len(batch), latency)

    @staticmethod
    def _stack_inputs(batch: list[_PendingRequest]) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        keys = list(batch[0].inputs.keys())
        for k in keys:
            arrays = [req.inputs[k] for req in batch]
            stacked = np.concatenate(arrays, axis=0) if arrays[0].ndim >= 1 else np.stack(arrays)
            out[k] = np.ascontiguousarray(stacked)
        return out

    @staticmethod
    def _split_outputs(result: dict[str, np.ndarray], batch_size: int) -> list[dict[str, np.ndarray]]:
        rows: list[dict[str, np.ndarray]] = [dict() for _ in range(batch_size)]
        for name, arr in result.items():
            if arr is None or batch_size == 1:
                for i in range(batch_size):
                    rows[i][name] = arr
                continue
            if arr.shape[0] == batch_size:
                for i in range(batch_size):
                    rows[i][name] = arr[i:i + 1]
            else:
                for i in range(batch_size):
                    rows[i][name] = arr
        return rows

    async def _direct_infer(
        self, model_name: str, inputs: dict[str, np.ndarray],
        outputs: list[str], timeout: float | None,
    ) -> dict[str, np.ndarray]:
        self._inflight[model_name] = self._inflight.get(model_name, 0) + 1
        self._report_inflight(model_name)
        t0 = time.perf_counter()
        try:
            if timeout is None:
                return await self.triton.infer(model_name, inputs, outputs)
            return await self.triton.infer(model_name, inputs, outputs, timeout=timeout)
        finally:
            self._inflight[model_name] = max(0, self._inflight.get(model_name, 0) - 1)
            self._report_inflight(model_name)
            self._report_batch(model_name, 1, time.perf_counter() - t0)

    def _report_queue_depth(self, model_name: str) -> None:
        m = self.metrics
        if m is None:
            return
        try:
            q = self._queues.get(model_name)
            m.queue_depth.labels(use_case=getattr(m, "use_case", "_"),
                                 queue=f"infer:{model_name}").set(len(q) if q is not None else 0)
        except Exception:
            pass

    def _report_inflight(self, model_name: str) -> None:
        m = self.metrics
        if m is None:
            return
        try:
            m.tasks_inflight.labels(use_case=getattr(m, "use_case", "_"),
                                    pool=f"infer:{model_name}").set(self._inflight.get(model_name, 0))
        except Exception:
            pass

    def _report_batch(self, model_name: str, batch_size: int, latency_s: float) -> None:
        m = self.metrics
        if m is None:
            return
        try:
            m.frame_stage_latency.labels(use_case=getattr(m, "use_case", "_"),
                                         camera_id=f"_batch_size_{batch_size}",
                                         stage=f"infer:{model_name}").observe(latency_s)
        except Exception:
            pass

    async def aclose(self) -> None:
        for task in list(self._dispatchers.values()):
            if not task.done():
                task.cancel()
        for task in list(self._dispatchers.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._dispatchers.clear()
        for q in self._queues.values():
            while q:
                req = q.popleft()
                if not req.future.done():
                    req.future.set_exception(RuntimeError("inference gateway closed"))
