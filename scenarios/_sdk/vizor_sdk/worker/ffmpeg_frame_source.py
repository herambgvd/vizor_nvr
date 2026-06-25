"""ffmpeg FrameSource adapter (ported from vizor-gpu) — PyAV software decode.

The fallback decoder for the worker when the native cpp NVDEC module isn't present.
NOTE: PyAV 17 can't swap a stream's codec_context, so this runs PyAV's SOFTWARE
decoder (true NVDEC needs the cpp module). It's the CPU-safe fallback that avoids the
GStreamer crash. Requires the `av` package in the image.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, AsyncIterator

from ..aio.frame_source import FrameSource

logger = logging.getLogger("vizor.worker.ffmpeg_frame_source")


class FFmpegFrameSource(FrameSource):
    """RTSP via PyAV (software decode)."""

    backend = "ffmpeg"

    def __init__(
        self,
        rtsp_url: str,
        *,
        fps: int = 5,
        transport: str = "tcp",
        max_backoff: float = 30.0,
        hwaccel: str | None = None,
        **_: Any,
    ) -> None:
        self.rtsp_url = rtsp_url
        self.fps = max(1, int(fps))
        self.transport = transport
        self.max_backoff = max_backoff
        self.hwaccel = (
            os.environ.get("VIZOR_FFMPEG_HWACCEL", "cuda") if hwaccel is None else hwaccel)
        self._closed = False
        self._stats: dict[str, Any] = {
            "backend": self.backend, "last_frame_at": None,
            "reconnects": 0, "hwaccel": None,
        }

    async def frames(self) -> AsyncIterator[Any]:
        import av  # type: ignore

        frame_interval = 1.0 / max(1, self.fps)
        backoff = 1.0

        while not self._closed:
            container = None
            _active_iterator = None
            current_hw = self.hwaccel or None
            try:
                logger.info("[ffmpeg] opening %s hwaccel=%s", self.rtsp_url, current_hw or "off")
                options = {
                    "rtsp_transport": self.transport,
                    "stimeout": "5000000",
                    "max_delay": "100000",
                    "fflags": "nobuffer+discardcorrupt",
                    "flags": "low_delay",
                    "probesize": "32",
                    "analyzeduration": "0",
                    "reorder_queue_size": "0",
                }
                container = await asyncio.to_thread(
                    av.open, self.rtsp_url, options=options, timeout=10.0)
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                self._stats["hwaccel"] = "sw"
                backoff = 1.0
                last_yielded = 0.0

                def _iter_frames():
                    for pkt in container.demux(stream):
                        for frame in pkt.decode():
                            arr = frame.to_ndarray(format="bgr24")
                            yield arr
                            del arr

                iterator = await asyncio.to_thread(lambda: iter(_iter_frames()))
                _active_iterator = iterator
                _SENTINEL = object()

                def _next_or_sentinel(it):
                    try:
                        return next(it)
                    except StopIteration:
                        return _SENTINEL

                while not self._closed:
                    ndarray = await asyncio.to_thread(_next_or_sentinel, iterator)
                    if ndarray is _SENTINEL:
                        break
                    now = time.monotonic()
                    if now - last_yielded < frame_interval:
                        continue
                    last_yielded = now
                    self._stats["last_frame_at"] = time.time()
                    yield ndarray
                    await asyncio.sleep(0)

                logger.warning("[ffmpeg] stream ended, reconnecting: %s", self.rtsp_url)
            except asyncio.CancelledError:
                logger.info("[ffmpeg] cancelled: %s", self.rtsp_url)
                raise
            except Exception as e:  # noqa: BLE001
                self._stats["reconnects"] += 1
                logger.warning("[ffmpeg] error on %s: %s — reconnect in %.1fs",
                               self.rtsp_url, e, backoff)
                if current_hw and "hwaccel" in str(e).lower():
                    self.hwaccel = ""
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise
                backoff = min(backoff * 2, self.max_backoff)
            finally:
                if _active_iterator is not None:
                    try:
                        _active_iterator.close()
                    except Exception:
                        pass
                if container is not None:
                    try:
                        await asyncio.to_thread(container.close)
                    except Exception:
                        pass

    async def close(self) -> None:
        self._closed = True

    def stats(self) -> dict[str, Any]:
        return dict(self._stats)
