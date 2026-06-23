"""Async inference gateway — per-model bounded concurrency over the shared Triton.

Replaces the worker's single global `_INFLIGHT` semaphore (which coupled all cameras
and let one wedged Triton call starve the rest) with a PER-MODEL async inflight cap,
a circuit breaker, and an adaptive `should_skip()` so a saturated model drops frames
instead of queuing.

The NVR `TritonClient.infer` is SYNCHRONOUS, so the gateway runs it via
`asyncio.to_thread` — the asyncio loop never blocks on a Triton round-trip. (The
vizor-gpu gateway also coalesces requests into batches; we skip that here because
the TensorRT detector is already ~3.5 ms and per-camera batching adds latency for
little gain. Re-add coalescing later if a heavier model needs it.)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from .circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


_DEFAULT_INFLIGHT_CAP = _env_int("VIZOR_INFER_INFLIGHT_CAP", 4)
_TRITON_TIMEOUT = _env_float("VIZOR_INFER_TIMEOUT_S", 4.0)


class InferenceGateway:
    """One per worker process, shared across all camera tasks. Holds a per-model
    asyncio.Semaphore (inflight cap) + a per-model circuit breaker."""

    def __init__(self, triton, *, inflight_cap: int | None = None) -> None:
        self._triton = triton                      # SDK TritonClient (sync .infer)
        self._cap = inflight_cap or _DEFAULT_INFLIGHT_CAP
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._breakers: dict[str, CircuitBreaker] = {}
        self._inflight: dict[str, int] = {}

    def _sem(self, model: str) -> asyncio.Semaphore:
        s = self._sems.get(model)
        if s is None:
            s = asyncio.Semaphore(self._cap)
            self._sems[model] = s
            self._inflight[model] = 0
        return s

    def _breaker(self, model: str) -> CircuitBreaker:
        b = self._breakers.get(model)
        if b is None:
            b = CircuitBreaker(f"triton_{model}")
            self._breakers[model] = b
        return b

    def should_skip(self, model: str) -> bool:
        """True when this model is saturated (inflight >= cap) or its breaker is
        open — the camera task drops the frame instead of queuing."""
        if self._breaker(model).is_open():
            return True
        return self._inflight.get(model, 0) >= self._cap

    async def infer(self, model: str, inputs: dict, out_names: list[str],
                    *, timeout: float | None = None) -> dict[str, Any] | None:
        """Run one inference: per-model inflight slot + circuit breaker, the SYNC
        Triton call off-loop via to_thread. Returns None (fail-soft) on breaker-open
        or inference failure — the pipeline treats None as "no detections"."""
        breaker = self._breaker(model)
        if breaker.is_open():
            return None
        sem = self._sem(model)
        async with sem:
            self._inflight[model] = self._inflight.get(model, 0) + 1
            try:
                def _call():
                    return self._triton.infer(model, inputs, out_names,
                                              timeout=(timeout or _TRITON_TIMEOUT))
                # circuit-breaker wraps the sync call; to_thread keeps the loop free.
                return await asyncio.to_thread(breaker.call, _call)
            except CircuitOpenError:
                return None
            except Exception as e:  # noqa: BLE001 — fail-soft
                logger.debug("[gateway] infer %s failed: %s", model, e)
                return None
            finally:
                self._inflight[model] -= 1

    def stats(self) -> dict:
        return {m: {"inflight": self._inflight.get(m, 0), "cap": self._cap,
                    "breaker": self._breakers[m].state if m in self._breakers else "closed"}
                for m in self._sems}
