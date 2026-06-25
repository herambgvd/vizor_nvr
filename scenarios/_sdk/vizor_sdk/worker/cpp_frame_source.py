"""C++ NVDEC FrameSource — wraps the native vizor_decode.AsyncDecoder (ported from
vizor-gpu).

Picks NVDEC h264_cuvid via FFmpeg's libavcodec C API. Decode runs on a dedicated
background thread inside the C++ module; Python just pulls the freshest BGR frame
from a 2-slot ringbuffer. This is the canonical worker decoder — it sidesteps the
GStreamer pipeline that crashed in the worker process, and runs the entropy decode
on NVDEC silicon (CPU ~5-10%/camera vs ~2 cores for software decode).

Requires the compiled `vizor_decode` .so on PYTHONPATH (built from cpp/vizor_decode
in the image). If the native module is missing the factory falls back to ffmpeg
(PyAV software) then pyav.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator

from ..aio.frame_source import FrameSource

logger = logging.getLogger("vizor.worker.cpp_frame_source")


def _try_import_native() -> Any:
    try:
        import vizor_decode as _vd  # type: ignore[import-not-found]
        return _vd
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cpp_frame_source] vizor_decode native module unavailable: %s", exc)
        return None


_vd = _try_import_native()


class CppFrameSource(FrameSource):
    """RTSP via the native vizor_decode AsyncDecoder (NVDEC)."""

    backend = "cpp"

    def __init__(
        self,
        rtsp_url: str,
        *,
        fps: int = 5,
        transport: str = "tcp",
        hwaccel: bool = True,
        gpu_index: int = 0,
        max_backoff: float = 30.0,
        frame_timeout_ms: int = 1000,
        **_: Any,
    ) -> None:
        if _vd is None:
            raise RuntimeError(
                "vizor_decode native module not available; build it via "
                "cpp/vizor_decode/ and ship the .so into PYTHONPATH")
        self.rtsp_url = rtsp_url
        self.fps = max(1, int(fps))
        self.transport = transport
        self.hwaccel = hwaccel
        self.gpu_index = gpu_index
        self.max_backoff = max_backoff
        self.frame_timeout_ms = frame_timeout_ms
        self._closed = False
        self._stats: dict[str, Any] = {
            "backend": self.backend, "last_frame_at": None,
            "reconnects": 0, "hwaccel": "cuda" if hwaccel else "",
        }

    async def frames(self) -> AsyncIterator[Any]:
        frame_interval = 1.0 / self.fps
        backoff = 1.0
        last_yielded = 0.0

        while not self._closed:
            dec = None
            try:
                dec = await asyncio.to_thread(
                    _vd.AsyncDecoder, self.rtsp_url, self.hwaccel,
                    self.transport, self.gpu_index)
                await asyncio.to_thread(dec.start)
                logger.info("[cpp] opened %s hwaccel=%s", self.rtsp_url, self.hwaccel)
                backoff = 1.0
                empty_streak = 0

                while not self._closed:
                    arr = await asyncio.to_thread(dec.next_frame, self.frame_timeout_ms)
                    if arr is None:
                        empty_streak += 1
                        if not dec.is_running:
                            raise RuntimeError("decode thread exited: " + (dec.last_error or "EOF"))
                        if empty_streak >= 3:
                            raise RuntimeError("frame_timeout x3 — reconnecting")
                        continue
                    empty_streak = 0
                    now = time.monotonic()
                    if now - last_yielded < frame_interval:
                        continue
                    last_yielded = now
                    self._stats["last_frame_at"] = time.time()
                    yield arr
                    await asyncio.sleep(0)

            except asyncio.CancelledError:
                logger.info("[cpp] cancelled: %s", self.rtsp_url)
                raise
            except Exception as exc:  # noqa: BLE001
                self._stats["reconnects"] += 1
                logger.warning("[cpp] %s : %s — reconnect in %.1fs", self.rtsp_url, exc, backoff)
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise
                backoff = min(backoff * 2, self.max_backoff)
            finally:
                if dec is not None:
                    try:
                        await asyncio.to_thread(dec.stop)
                    except Exception:  # noqa: BLE001
                        pass

    async def close(self) -> None:
        self._closed = True

    def stats(self) -> dict[str, Any]:
        return dict(self._stats)
