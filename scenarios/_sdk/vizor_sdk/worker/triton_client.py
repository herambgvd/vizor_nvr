"""Triton gRPC client wrapper (ported from vizor-gpu).

This is the module that fixes the production hang. nvr previously called Triton
over HTTP with `tritonclient.http`, whose `_post` has no network timeout — a slow
or stuck Triton blocked the recognition thread forever, every pool thread piled up
behind it, and events froze. Here every call:

  * runs on a dedicated bounded ThreadPoolExecutor (so concurrent inference doesn't
    starve the default to_thread pool used for other I/O),
  * is wrapped in `asyncio.wait_for(..., timeout=deadline)` — a HARD per-call cap.
    A hung Triton raises asyncio.TimeoutError and the pipeline drops the frame
    instead of wedging the camera task,
  * optionally passes through a CircuitBreaker so repeated failures short-circuit.

We use the synchronous gRPC client offloaded to threads (not grpc.aio) because the
aio client binds its channel to the loop at construction, which breaks when the
client is shared across the per-camera task loops.
"""
from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import tritonclient.grpc as tgrpc

logger = logging.getLogger("vizor.worker.triton")

try:
    from prometheus_client import Histogram
    _LATENCY = Histogram(
        "vizor_triton_infer_seconds",
        "Triton inference wall time per call",
        ["model"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
except Exception:  # pragma: no cover
    _LATENCY = None


_DTYPE_MAP = {
    np.dtype("float32"): "FP32",
    np.dtype("float16"): "FP16",
    np.dtype("float64"): "FP64",
    np.dtype("int8"):    "INT8",
    np.dtype("int16"):   "INT16",
    np.dtype("int32"):   "INT32",
    np.dtype("int64"):   "INT64",
    np.dtype("uint8"):   "UINT8",
    np.dtype("bool"):    "BOOL",
}


def _triton_dtype(arr: np.ndarray) -> str:
    try:
        return _DTYPE_MAP[arr.dtype]
    except KeyError as e:
        raise ValueError(f"Unsupported numpy dtype for Triton: {arr.dtype}") from e


def default_grpc_url() -> str:
    """Triton gRPC endpoint from env (TRITON_GRPC_URL), compose default triton:8001."""
    return os.environ.get("TRITON_GRPC_URL", "triton:8001")


class TritonClient:
    """Triton gRPC client with an async, hard-timeout `infer()` surface.

    Internally uses the sync gRPC client; all calls are offloaded to a worker
    thread via run_in_executor, so the client is safe to share across asyncio
    loops and per-camera tasks.
    """

    def __init__(
        self,
        url: str,
        verbose: bool = False,
        *,
        max_workers: int | None = None,
        infer_timeout_secs: float | None = None,
        breaker: Any | None = None,
    ):
        self.url = url.replace("grpc://", "").replace("http://", "").rstrip("/")
        self._client = tgrpc.InferenceServerClient(url=self.url, verbose=verbose)
        self._breaker = breaker
        if max_workers is None:
            try:
                max_workers = int(os.environ.get("TRITON_INFER_WORKERS", "8"))
            except ValueError:
                max_workers = 8
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="triton-infer",
        )
        if infer_timeout_secs is None:
            try:
                infer_timeout_secs = float(os.environ.get("TRITON_INFER_TIMEOUT_SECS", "5.0"))
            except ValueError:
                infer_timeout_secs = 5.0
        self.infer_timeout_secs = infer_timeout_secs

    # ── readiness ──────────────────────────────────────────────────────────
    async def model_ready(self, model_name: str) -> bool:
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(self._executor, self._client.is_model_ready, model_name),
                timeout=self.infer_timeout_secs,
            )
        except Exception as e:
            logger.warning("[triton] is_model_ready(%s) failed: %s", model_name, e)
            return False

    async def server_live(self) -> bool:
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(self._executor, self._client.is_server_live),
                timeout=self.infer_timeout_secs,
            )
        except Exception:
            return False

    # ── inference ──────────────────────────────────────────────────────────
    def _build_infer_inputs(self, inputs: dict[str, np.ndarray]):
        out = []
        for name, arr in inputs.items():
            tensor = tgrpc.InferInput(name, list(arr.shape), _triton_dtype(arr))
            tensor.set_data_from_numpy(np.ascontiguousarray(arr))
            out.append(tensor)
        return out

    def _infer_sync(
        self, model_name: str, inputs: dict[str, np.ndarray], outputs: list[str],
    ) -> dict[str, np.ndarray]:
        infer_inputs = self._build_infer_inputs(inputs)
        infer_outputs = [tgrpc.InferRequestedOutput(o) for o in outputs]
        result = self._client.infer(
            model_name=model_name, inputs=infer_inputs, outputs=infer_outputs,
        )
        return {o: result.as_numpy(o) for o in outputs}

    async def _infer_inner(
        self, model_name: str, inputs: dict[str, np.ndarray],
        outputs: list[str], deadline: float,
    ) -> dict[str, np.ndarray]:
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(self._executor, self._infer_sync, model_name, inputs, outputs)
        try:
            if _LATENCY is not None:
                with _LATENCY.labels(model=model_name).time():
                    return await asyncio.wait_for(fut, timeout=deadline)
            return await asyncio.wait_for(fut, timeout=deadline)
        except asyncio.TimeoutError:
            logger.warning("[triton] infer timeout (model=%s, deadline=%.1fs)",
                           model_name, deadline)
            raise

    async def infer(
        self, model_name: str, inputs: dict[str, np.ndarray], outputs: list[str],
        *, timeout: float | None = None,
    ) -> dict[str, np.ndarray]:
        """Run inference with a HARD timeout. Raises asyncio.TimeoutError if Triton
        doesn't respond within `timeout` (or self.infer_timeout_secs). Pipeline code
        should treat the timeout as a transient failure and skip the frame, NOT
        propagate to the camera task. With a breaker wired, repeated failures open it
        and short-circuit subsequent calls until cool-down."""
        deadline = timeout if timeout is not None else self.infer_timeout_secs
        if self._breaker is not None:
            return await self._breaker.call_async(
                self._infer_inner, model_name, inputs, outputs, deadline)
        return await self._infer_inner(model_name, inputs, outputs, deadline)

    async def close(self) -> None:
        # Best-effort close, bounded so a hung Triton can't stall shutdown.
        try:
            await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(self._executor, self._client.close),
                timeout=5.0,
            )
        except Exception:
            pass
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self._executor.shutdown(wait=True, cancel_futures=True))
        except Exception:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
