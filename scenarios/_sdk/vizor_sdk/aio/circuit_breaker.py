"""Circuit breaker for outbound dependencies (Triton, DB). Ported from vizor-gpu.

Three states: closed (calls pass, failures counted) → open (short-circuit for a
cooldown, saves the caller from queuing on a dead dependency) → half_open (one
probe; success closes, failure reopens). Lets a pipeline degrade gracefully — a
dead Triton short-circuits in microseconds instead of every camera burning a
timeout per frame.

Defaults: 5 failures / 10s window → open 30s. Env-tunable per name:
VIZOR_CB_<NAME>_FAILURES / _WINDOW_S / _COOLDOWN_S.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import Any, Awaitable, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    def __init__(self, name: str, reopen_in: float) -> None:
        super().__init__(f"circuit '{name}' open (reopen in {reopen_in:.1f}s)")
        self.name = name
        self.reopen_in = reopen_in


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


class CircuitBreaker:
    """One breaker per named dependency. Construct ONCE per dependency and share.
    Wrap calls via call() (sync) or call_async() (awaitable)."""

    def __init__(self, name: str, *, failure_threshold: int | None = None,
                 rolling_window_s: float | None = None, open_cooldown_s: float | None = None) -> None:
        self.name = name
        u = name.upper()
        self.failure_threshold = _env_int(f"VIZOR_CB_{u}_FAILURES", failure_threshold or 5)
        self.rolling_window_s = _env_float(f"VIZOR_CB_{u}_WINDOW_S", rolling_window_s or 10.0)
        self.open_cooldown_s = _env_float(f"VIZOR_CB_{u}_COOLDOWN_S", open_cooldown_s or 30.0)
        self._failures: deque[float] = deque()
        self._opened_at: Optional[float] = None
        self._half_open_lock = asyncio.Lock()
        self._state: str = "closed"

    @property
    def state(self) -> str:
        return self._state

    def is_open(self) -> bool:
        self._maybe_transition_to_half_open()
        return self._state == "open"

    # ── sync (NVR detector / DB are blocking) ────────────────────────────────
    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a SYNC fn behind the breaker. Raises CircuitOpenError when open."""
        self._maybe_transition_to_half_open()
        if self._state == "open":
            raise CircuitOpenError(self.name, self._reopen_in())
        try:
            result = fn(*args, **kwargs)
        except CircuitOpenError:
            raise
        except Exception:
            self._record_failure()
            raise
        else:
            self._record_success()
            return result

    # ── async ────────────────────────────────────────────────────────────────
    async def call_async(self, fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        self._maybe_transition_to_half_open()
        if self._state == "open":
            raise CircuitOpenError(self.name, self._reopen_in())
        if self._state == "half_open":
            async with self._half_open_lock:
                self._maybe_transition_to_half_open()
                if self._state == "open":
                    raise CircuitOpenError(self.name, self._reopen_in())
                return await self._invoke(fn, args, kwargs)
        return await self._invoke(fn, args, kwargs)

    async def _invoke(self, fn, args, kwargs):
        try:
            result = await fn(*args, **kwargs)
        except CircuitOpenError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            self._record_failure()
            raise
        else:
            self._record_success()
            return result

    def _record_failure(self) -> None:
        now = time.monotonic()
        self._failures.append(now)
        self._prune(now)
        if len(self._failures) >= self.failure_threshold and self._state != "open":
            self._open(now)

    def _record_success(self) -> None:
        if self._state == "half_open":
            self._close()

    def _open(self, now: float) -> None:
        self._opened_at = now
        self._state = "open"
        logger.warning("[cb %s] OPEN — %d failures in %.1fs", self.name, len(self._failures), self.rolling_window_s)

    def _close(self) -> None:
        self._opened_at = None
        self._failures.clear()
        self._state = "closed"
        logger.info("[cb %s] CLOSED — probe succeeded", self.name)

    def _maybe_transition_to_half_open(self) -> None:
        if self._state != "open" or self._opened_at is None:
            return
        if (time.monotonic() - self._opened_at) >= self.open_cooldown_s:
            self._state = "half_open"
            logger.info("[cb %s] HALF_OPEN — probing next call", self.name)

    def _prune(self, now: float) -> None:
        cutoff = now - self.rolling_window_s
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()

    def _reopen_in(self) -> float:
        if self._opened_at is None:
            return 0.0
        return max(0.0, self.open_cooldown_s - (time.monotonic() - self._opened_at))
