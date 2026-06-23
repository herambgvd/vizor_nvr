"""Async event delivery — off the frame/decode path, with disk-spool fallback.

The fragile worker wrote each event SYNCHRONOUSLY to Postgres inside the per-frame
callback, holding the inflight slot; a slow/blocked insert stalled the frame loop
and its errors were swallowed (counter climbed, no rows). Here, the pipeline just
`submit(event)` — non-blocking — and a dedicated writer drains the queue to a
scenario-supplied `EventSink` on a worker thread. On sink failure the event is
spooled to disk (JSONL) and replayed when the sink recovers, so events are never
silently lost.

Sink contract (each scenario supplies one): `sink(event: dict) -> None`. For PPE
this calls `record_event(**event)` + writes the snapshot; for FRS its own recorder.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

EventSink = Callable[[dict], None]


def _max_spool_bytes() -> int:
    try:
        return int(os.environ.get("VIZOR_SPOOL_MAX_BYTES", str(64 * 1024 * 1024)))
    except ValueError:
        return 64 * 1024 * 1024


class AsyncEventWriter:
    """One per scenario process. A bounded queue + ONE daemon writer thread that
    calls the sink; on failure it spools to disk and replays later. Submit is
    non-blocking (drops + WARNs when the queue is full rather than stalling the
    pipeline)."""

    def __init__(self, name: str, sink: EventSink, *, spool_dir: str | Path,
                 maxsize: int = 2000) -> None:
        self.name = name
        self._sink = sink
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)
        self._stop = threading.Event()
        self._dropped = 0
        self._written = 0
        self._spooled = 0
        self._last_error: str | None = None
        try:
            self._spool = Path(spool_dir) / f"{name}_events.jsonl"
            self._spool.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:  # noqa: BLE001
            logger.warning("[event-writer %s] spool dir unavailable: %s", name, e)
            self._spool = None
        self._thread = threading.Thread(target=self._run, name=f"event-writer-{name}", daemon=True)
        self._replay_thread = threading.Thread(target=self._replay_loop, name=f"event-replay-{name}", daemon=True)
        self._thread.start()
        self._replay_thread.start()

    # ── public ───────────────────────────────────────────────────────────────
    def submit(self, event: dict) -> bool:
        """Non-blocking enqueue. Returns False (and counts a drop) if the queue is
        full — never blocks the caller."""
        try:
            self._q.put_nowait(event)
            return True
        except queue.Full:
            self._dropped += 1
            if self._dropped % 50 == 1:
                logger.warning("[event-writer %s] queue full — dropped %d events", self.name, self._dropped)
            return False

    def stats(self) -> dict:
        return {"written": self._written, "spooled": self._spooled,
                "dropped": self._dropped, "queued": self._q.qsize(),
                "last_error": self._last_error}

    def stop(self) -> None:
        self._stop.set()

    # ── writer thread ────────────────────────────────────────────────────────
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            self._write_one(event)

    def _write_one(self, event: dict) -> None:
        try:
            self._sink(event)
            self._written += 1
        except Exception as e:  # noqa: BLE001 — never lose the event
            self._last_error = str(e)[:200]
            logger.warning("[event-writer %s] sink failed (%s) — spooling", self.name, self._last_error)
            self._spool_event(event)

    def _spool_event(self, event: dict) -> None:
        if self._spool is None:
            return
        try:
            self._rotate_if_big()
            with self._spool.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str) + "\n")
            self._spooled += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("[event-writer %s] spool write failed: %s", self.name, e)

    def _rotate_if_big(self) -> None:
        try:
            if self._spool.exists() and self._spool.stat().st_size > _max_spool_bytes():
                data = self._spool.read_bytes()
                self._spool.write_bytes(data[len(data) // 2:])  # drop oldest half
                logger.warning("[event-writer %s] spool rotated", self.name)
        except OSError:
            pass

    # ── replay thread (drains the spool when the sink recovers) ───────────────
    def _replay_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(10)
            if self._spool is None or not self._spool.exists():
                continue
            try:
                if self._spool.stat().st_size == 0:
                    continue
                lines = self._spool.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            remaining: list[str] = []
            recovered = True
            for ln in lines:
                ln = ln.strip()
                if not ln:
                    continue
                if not recovered:
                    remaining.append(ln)
                    continue
                try:
                    self._sink(json.loads(ln))
                    self._written += 1
                except Exception:  # noqa: BLE001 — sink still down; keep the rest
                    recovered = False
                    remaining.append(ln)
            try:
                if remaining:
                    self._spool.write_text("\n".join(remaining) + "\n", encoding="utf-8")
                else:
                    self._spool.write_text("", encoding="utf-8")
                    logger.info("[event-writer %s] spool drained", self.name)
            except OSError:
                pass
