"""FrameSource — single async interface for every RTSP decoder backend.

GStreamer is the production backend (NVDEC-capable, H.264/H.265 via decodebin,
built-in drop-oldest backpressure). PyAV is a pure-software fallback kept only for
boxes without the gst plugins. Ported from vizor-gpu's _base/frame_source.py +
gstreamer_frame_source.py, adapted to the NVR SDK (stdlib logging, no loguru).

Pick a backend with VIZOR_DECODER=gstreamer|pyav (default gstreamer). Optional NVDEC
pin: GST_DECODER_BIN="nvh264dec ! videoconvert" (dGPU) or
"nvv4l2decoder ! nvvideoconvert" (Jetson).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import numpy as np

logger = logging.getLogger(__name__)


def _has_element(name: str) -> bool:
    """True if a GStreamer element factory is available (cudadownload only exists when
    the CUDA plugin is present — absent on a CPU-only build)."""
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        if not Gst.is_initialized():
            Gst.init(None)
        return Gst.ElementFactory.find(name) is not None
    except Exception:  # noqa: BLE001
        return False


class FrameSource(ABC):
    """Abstract async frame producer. Subclasses implement frames(); the rest is
    lifecycle + introspection. Cancellation is cooperative."""

    backend = "abstract"

    @abstractmethod
    def frames(self) -> AsyncIterator[Any]:
        """Yield numpy BGR frames at ~the configured fps. Reconnect on transient
        RTSP errors; only raise on unrecoverable conditions."""
        raise NotImplementedError

    async def close(self) -> None:
        """Release decoder + socket resources. Idempotent."""
        return None

    def stats(self) -> dict[str, Any]:
        """Health snapshot for the watchdog / worker-logs: backend, last_frame_at,
        decode_fps, reconnects."""
        return {}


# ── GStreamer (production default) ───────────────────────────────────────────
try:
    import gi  # type: ignore

    gi.require_version("Gst", "1.0")
    gi.require_version("GstApp", "1.0")
    from gi.repository import GLib, Gst  # type: ignore

    _GST_AVAILABLE = True
    _GST_IMPORT_ERR = ""
except Exception as _exc:  # noqa: BLE001
    _GST_AVAILABLE = False
    _GST_IMPORT_ERR = str(_exc)
    Gst = GLib = None  # type: ignore

_GST_INIT_DONE = False


def _ensure_gst_init() -> None:
    global _GST_INIT_DONE
    if not _GST_INIT_DONE:
        Gst.init(None)
        _GST_INIT_DONE = True


class GStreamerFrameSource(FrameSource):
    """RTSP → BGR numpy via a GStreamer pipeline. A GLib main loop runs on a daemon
    thread and hands frames to the asyncio loop via call_soon_threadsafe; the
    asyncio loop never blocks on Gst. Bounded queue (maxsize=2, drop-oldest) so a
    slow consumer drops frames instead of stalling decode."""

    backend = "gstreamer"

    def __init__(self, rtsp_url: str, *, fps: int = 5, latency_ms: int | None = None, **_: Any) -> None:
        if not _GST_AVAILABLE:
            raise ImportError(
                f"GStreamer python bindings unavailable: {_GST_IMPORT_ERR}. "
                "Install python3-gi + gstreamer1.0 plugins."
            )
        _ensure_gst_init()
        self.rtsp_url = rtsp_url
        self.fps = max(1, int(fps))
        # rtspsrc jitter-buffer latency. 200ms is too tight for high-bitrate 1080p
        # streams behind go2rtc — the buffer underruns and rtspsrc throws "Internal
        # data stream error", killing the pipeline. 500ms absorbs the jitter; tune
        # via GST_RTSP_LATENCY_MS.
        if latency_ms is None:
            latency_ms = int(os.environ.get("GST_RTSP_LATENCY_MS", "500"))
        self.latency_ms = int(latency_ms)
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        self._closed = False
        self._reconnects = 0
        self._restart_pending = False
        self._restart_backoff = 1.0
        self._restart_backoff_max = 30.0
        self._last_frame_at: float = 0.0
        self._stats: dict[str, Any] = {
            "backend": self.backend, "last_frame_at": None,
            "reconnects": 0, "decode_fps": 0.0,
        }
        self._gloop = GLib.MainLoop()
        self._thread = threading.Thread(target=self._run_glib, name=f"gst-{rtsp_url[-12:]}", daemon=True)
        self._pipeline = None
        self._appsink = None
        self._asyncio_loop: asyncio.AbstractEventLoop | None = None
        self._build_pipeline()
        self._thread.start()

    def _build_pipeline(self) -> None:
        appsink = (
            "video/x-raw,format=BGR ! appsink name=sink "
            "max-buffers=2 drop=true sync=false emit-signals=true"
        )
        protocols = os.environ.get("GST_RTSP_PROTOCOLS", "tcp")
        explicit = os.environ.get("GST_DECODER_BIN")
        if explicit:
            pipeline_str = (
                f"rtspsrc location={self.rtsp_url} latency={self.latency_ms} "
                f"tcp-timeout=5000000 protocols={protocols} "
                f"! rtph264depay ! h264parse ! {explicit} ! {appsink}"
            )
        else:
            # decodebin auto-negotiates the codec (H.264 AND H.265) AND the best decoder.
            # With the NVDEC decoders' rank boosted (GST_PLUGIN_FEATURE_RANK) it picks
            # nvh264dec / nvh265dec on the GPU — BOTH output CUDAMemory (NV12), so
            # cudadownload copies it to system memory and videoconvert -> BGR for the
            # appsink. One pipeline, both codecs, on the GPU. (On a no-GPU box decodebin
            # falls back to software decode whose system-memory output passes cudadownload
            # through unchanged.)
            convert = "cudadownload ! videoconvert" if _has_element("cudadownload") else "videoconvert"
            pipeline_str = (
                f"rtspsrc location={self.rtsp_url} latency={self.latency_ms} "
                f"tcp-timeout=5000000 protocols={protocols} "
                f"! decodebin ! {convert} ! {appsink}"
            )
        logger.info("[gst] launch: %s", pipeline_str)
        try:
            self._pipeline = Gst.parse_launch(pipeline_str)
        except GLib.Error as e:  # type: ignore
            raise RuntimeError(f"gst parse_launch failed: {e}") from e
        self._appsink = self._pipeline.get_by_name("sink")
        self._appsink.connect("new-sample", self._on_new_sample)
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

    def _on_new_sample(self, sink) -> int:
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        s = sample.get_caps().get_structure(0)
        width, height = s.get_value("width"), s.get_value("height")
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            arr = np.frombuffer(mapinfo.data, dtype=np.uint8)
            expected = height * width * 3
            if arr.size < expected:
                return Gst.FlowReturn.OK
            frame = arr[:expected].reshape(height, width, 3).copy()
        finally:
            buf.unmap(mapinfo)
        self._last_frame_at = time.time()
        self._stats["last_frame_at"] = self._last_frame_at
        self._restart_backoff = 1.0
        loop = self._asyncio_loop
        if loop is not None and not self._closed:
            try:
                loop.call_soon_threadsafe(self._enqueue, frame)
            except RuntimeError:
                pass
        return Gst.FlowReturn.OK

    def _enqueue(self, frame: np.ndarray) -> None:
        if self._closed:
            return
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            pass

    def _on_bus_message(self, bus, msg) -> None:
        t = msg.type
        if t == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            logger.warning("[gst] pipeline error rtsp=%s err=%s", self.rtsp_url, err.message)
            self._schedule_restart()
        elif t == Gst.MessageType.EOS:
            logger.warning("[gst] eos rtsp=%s", self.rtsp_url)
            self._schedule_restart()

    def _schedule_restart(self) -> None:
        if self._closed or self._restart_pending:
            return
        self._restart_pending = True
        self._reconnects += 1
        self._stats["reconnects"] = self._reconnects
        delay = self._restart_backoff
        logger.info("[gst] restart rtsp=%s in %.0fs (attempt %d)", self.rtsp_url, delay, self._reconnects)
        try:
            self._pipeline.set_state(Gst.State.NULL)
        except Exception:  # noqa: BLE001
            pass
        GLib.timeout_add(int(delay * 1000), self._do_restart)
        self._restart_backoff = min(self._restart_backoff * 2.0, self._restart_backoff_max)

    def _do_restart(self) -> bool:
        self._restart_pending = False
        if self._closed:
            return False
        try:
            self._pipeline.set_state(Gst.State.PLAYING)
        except Exception as e:  # noqa: BLE001
            logger.warning("[gst] restart PLAYING failed rtsp=%s: %s", self.rtsp_url, e)
        return False

    def _run_glib(self) -> None:
        self._pipeline.set_state(Gst.State.PLAYING)
        try:
            self._gloop.run()
        except Exception:  # noqa: BLE001
            logger.exception("[gst] glib loop crashed rtsp=%s", self.rtsp_url)
        finally:
            try:
                self._pipeline.set_state(Gst.State.NULL)
            except Exception:  # noqa: BLE001
                pass

    async def frames(self) -> AsyncIterator[Any]:
        self._asyncio_loop = asyncio.get_running_loop()
        last_emit = 0.0
        interval = 1.0 / self.fps
        while not self._closed:
            try:
                frame = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            now = time.monotonic()
            if now - last_emit < interval:
                continue
            last_emit = now
            yield frame

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._gloop.quit()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._pipeline.set_state(Gst.State.NULL)
        except Exception:  # noqa: BLE001
            pass

    def stats(self) -> dict[str, Any]:
        return dict(self._stats)


# ── PyAV (software fallback only) ────────────────────────────────────────────
class PyAvFrameSource(FrameSource):
    """Pure-software RTSP decode via PyAV — last-resort fallback when GStreamer
    isn't available. Decode runs in a thread (asyncio.to_thread) so the loop never
    blocks; reconnect with backoff."""

    backend = "pyav"

    def __init__(self, rtsp_url: str, *, fps: int = 5, **_: Any) -> None:
        import av  # noqa: F401  (import-time check)
        self.rtsp_url = rtsp_url
        self.fps = max(1, int(fps))
        self._closed = False
        self._reconnects = 0
        self._last_frame_at = 0.0

    async def frames(self) -> AsyncIterator[Any]:
        import av

        interval = 1.0 / self.fps
        backoff = 1.0
        last_emit = 0.0
        while not self._closed:
            try:
                container = await asyncio.to_thread(
                    av.open, self.rtsp_url, options={"rtsp_transport": "tcp", "stimeout": "10000000"}
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("[pyav] open failed rtsp=%s: %s — retry in %.0fs", self.rtsp_url, e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                self._reconnects += 1
                continue
            backoff = 1.0
            try:
                stream = container.streams.video[0]
                gen = container.decode(stream)
                while not self._closed:
                    try:
                        frame = await asyncio.to_thread(next, gen)
                    except StopIteration:
                        break
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[pyav] decode error rtsp=%s: %s", self.rtsp_url, e)
                        break
                    now = time.monotonic()
                    if now - last_emit < interval:
                        continue
                    last_emit = now
                    self._last_frame_at = time.time()
                    yield frame.to_ndarray(format="bgr24")
            finally:
                try:
                    container.close()
                except Exception:  # noqa: BLE001
                    pass
            self._reconnects += 1
            await asyncio.sleep(backoff)

    async def close(self) -> None:
        self._closed = True

    def stats(self) -> dict[str, Any]:
        return {"backend": self.backend, "last_frame_at": self._last_frame_at or None,
                "reconnects": self._reconnects, "decode_fps": 0.0}


# ── factory ──────────────────────────────────────────────────────────────────
def build_frame_source(rtsp_url: str, *, fps: int = 5, backend: str | None = None, **kwargs: Any) -> FrameSource:
    """Pick the FrameSource: explicit backend, else VIZOR_DECODER env, else
    gstreamer. Falls back gstreamer -> pyav with a WARNING so a box that silently
    drops to software CPU decode is visible in logs."""
    requested = (backend or os.environ.get("VIZOR_DECODER", "gstreamer")).strip().lower()
    if requested == "gstreamer":
        try:
            src = GStreamerFrameSource(rtsp_url, fps=fps, **kwargs)
            logger.info("decoder: gstreamer engaged for %s", rtsp_url)
            return src
        except Exception as e:  # noqa: BLE001
            logger.warning("decoder fallback: gstreamer unavailable (%s) -> pyav (software CPU "
                           "decode — check gst plugins / NVDEC)", e)
            requested = "pyav"
    src = PyAvFrameSource(rtsp_url, fps=fps, **kwargs)
    logger.info("decoder: pyav (software) engaged for %s", rtsp_url)
    return src
