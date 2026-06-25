"""Local-disk JSONL event spool for Redis-down degradation.

When `emit()` cannot reach Redis (network blip, Redis OOM, container
restart), the NVR worker would otherwise lose the detection event. This
spool appends the serialized event to a JSONL file on local disk.
On reconnect, `replay()` drains the file back into the stream and
truncates on success.

Bounded by `VIZOR_SPOOL_MAX_BYTES` (default 256 MB) — older entries
rotate out before they fill the edge box.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("vizor.worker.event_spool")


def _spool_dir() -> Path:
    base = os.environ.get("VIZOR_SPOOL_DIR", "/var/lib/vizor/spool")
    return Path(base)


def _max_bytes() -> int:
    try:
        return int(os.environ.get("VIZOR_SPOOL_MAX_BYTES", str(256 * 1024 * 1024)))
    except ValueError:
        return 256 * 1024 * 1024


class EventSpool:
    """Per-worker spool. Construct once; share across emit() callers.

    File-per-worker so two workers in the same compose project don't
    interleave writes. Replay is serialised by an asyncio.Lock so a
    second connect-recovery doesn't double-emit a partial batch.
    """

    def __init__(self, use_case: str) -> None:
        self.use_case = use_case
        self.dir = _spool_dir()
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self.path: Path | None = self.dir / f"{use_case}.jsonl"
        except OSError as e:
            logger.warning("[spool] cannot create %s: %s", self.dir, e)
            self.path = None
        self._lock = asyncio.Lock()

    def disabled(self) -> bool:
        return self.path is None

    async def append(self, line: str) -> None:
        """Append one JSON line. Caller already serialised the event.
        Synchronous file I/O run in a thread so the asyncio loop
        doesn't block on slow disks."""
        if self.path is None:
            return
        try:
            await asyncio.to_thread(self._append_sync, line)
        except Exception as e:
            logger.warning("[spool] append failed: %s", e)

    def _append_sync(self, line: str) -> None:
        assert self.path is not None
        # Rotate if file > cap. Drop oldest half (cheap truncate).
        try:
            size = self.path.stat().st_size if self.path.exists() else 0
        except OSError:
            size = 0
        if size > _max_bytes():
            try:
                # Read second half + rewrite. Loses oldest events but
                # keeps recent ones for replay.
                data = self.path.read_bytes()
                self.path.write_bytes(data[len(data) // 2:])
                logger.warning(
                    "[spool] rotated %s (%s -> %s bytes)",
                    self.path, size, len(data) // 2,
                )
            except OSError as e:
                logger.warning("[spool] rotate failed: %s", e)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)
            if not line.endswith("\n"):
                f.write("\n")

    async def replay(self, emit_fn) -> int:
        """Drain spool into `emit_fn(line)` (async). Returns count
        replayed. Caller usually wires this to BaseWorker's emit-to-
        Redis path. On any per-line error we keep the line in place
        so a half-recovered Redis doesn't lose events; full success
        truncates the spool file.
        """
        if self.path is None:
            return 0
        async with self._lock:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return 0
            try:
                lines = await asyncio.to_thread(self._read_lines)
            except OSError as e:
                logger.warning("[spool] read failed: %s", e)
                return 0
            replayed = 0
            errored = False
            for ln in lines:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    await emit_fn(ln)
                    replayed += 1
                except Exception as e:
                    logger.warning("[spool] replay failed at line %s: %s", replayed, e)
                    errored = True
                    break
            if not errored:
                try:
                    await asyncio.to_thread(self._truncate)
                except OSError as e:
                    logger.warning("[spool] truncate failed: %s", e)
            else:
                # Rewrite remaining lines so replayed ones don't
                # double-emit on next attempt.
                remaining = lines[replayed:]
                try:
                    await asyncio.to_thread(self._rewrite, remaining)
                except OSError as e:
                    logger.warning("[spool] rewrite failed: %s", e)
            if replayed:
                logger.info("[spool] replayed %s events from %s", replayed, self.path)
            return replayed

    def _read_lines(self) -> list[str]:
        assert self.path is not None
        with self.path.open("r", encoding="utf-8") as f:
            return f.readlines()

    def _truncate(self) -> None:
        assert self.path is not None
        with self.path.open("w", encoding="utf-8") as f:
            f.truncate(0)

    def _rewrite(self, lines: list[str]) -> None:
        assert self.path is not None
        with self.path.open("w", encoding="utf-8") as f:
            for ln in lines:
                if not ln.endswith("\n"):
                    ln += "\n"
                f.write(ln)

    def stats(self) -> dict[str, Any]:
        if self.path is None or not self.path.exists():
            return {"queued_bytes": 0, "path": None}
        try:
            return {
                "queued_bytes": self.path.stat().st_size,
                "path": str(self.path),
                "last_modified": self.path.stat().st_mtime,
            }
        except OSError:
            return {"queued_bytes": 0, "path": str(self.path)}
