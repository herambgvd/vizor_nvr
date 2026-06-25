"""Unified event-deduper.

Scenarios produce events that should NOT spam the operator UI when the
same person/object is repeatedly detected within a short window. Each
existing pipeline rolled its own dedup with subtly different
semantics (PPE: spatial grid, FRS: cosine-distance, people-mgmt:
per-line-per-track). This module gives us a single primitive every
scenario can share for the **temporal** half — the "did we just emit
key K within window W" check that all of them have to do.

It is intentionally tiny: only the time-based suppression. Scenarios
still build their own dedup KEYS (spatial grid, embedding hash, …)
because those are scenario-specific and worth their existing care.

In-process by default. A future iteration may add a Redis-backed
variant when multi-worker dedup matters (today each scenario runs
single-leader so per-process is fine).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("vizor.worker.dedup")


class TimeDeduper:
    """Boolean cache: ``should_emit(key, now)`` returns False when the
    same key was emitted within ``window_seconds``.

    Thread-safe and asyncio-safe (one internal mutex). LRU-pruned
    every ``_PRUNE_EVERY`` calls so memory stays bounded under
    high-cardinality keyspaces.
    """

    __slots__ = ("window_seconds", "_last", "_lock", "_max_keys", "_calls")

    def __init__(self, window_seconds: float = 5.0, *, max_keys: int = 10_000) -> None:
        self.window_seconds = float(window_seconds)
        self._last: dict[Any, float] = {}
        self._lock = threading.Lock()
        self._max_keys = int(max_keys)
        self._calls = 0

    def should_emit(self, key: Any, now: Optional[float] = None) -> bool:
        """Return True if ``key`` may be emitted now; stamp the
        timestamp as a side effect.

        Caller passes ``now`` (typically the frame timestamp) so the
        deduper agrees with whatever time source the pipeline uses
        for events. Falls back to wall clock if omitted.
        """
        ts = float(now) if now is not None else time.time()
        with self._lock:
            self._calls += 1
            prev = self._last.get(key)
            if prev is not None and (ts - prev) < self.window_seconds:
                return False
            self._last[key] = ts
            if len(self._last) > self._max_keys:
                self._prune_locked(ts)
            return True

    def reset(self) -> None:
        with self._lock:
            self._last.clear()
            self._calls = 0

    def _prune_locked(self, now: float) -> None:
        cutoff = now - (self.window_seconds * 4.0)
        for k, ts in list(self._last.items()):
            if ts < cutoff:
                self._last.pop(k, None)
        # If still over the cap, drop oldest until we're under.
        if len(self._last) > self._max_keys:
            ordered = sorted(self._last.items(), key=lambda kv: kv[1])
            for k, _ in ordered[: len(self._last) - self._max_keys]:
                self._last.pop(k, None)
