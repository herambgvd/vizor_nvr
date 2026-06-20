"""Base configuration shared by every scenario plugin.

A plugin subclasses or composes BaseConfig and adds its own thresholds. These are
the env vars EVERY scenario needs (NVR wiring, Triton, go2rtc, retention). Keeps
the per-plugin settings.py to just the scenario-specific knobs.
"""
from __future__ import annotations

import os
from pathlib import Path


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


class BaseConfig:
    """Common plugin settings. Read once at import in the plugin's config module:

        from vizor_sdk.config import BaseConfig
        class Config(BaseConfig):
            SLUG = "anpr"
            # ...scenario-specific fields...
        config = Config()
    """

    # Identity
    SLUG: str = os.getenv("SCENARIO_SLUG", "")
    PORT: int = int(os.getenv("PORT", "8090"))

    # NVR wiring
    VIZOR_BASE_URL: str = os.getenv("VIZOR_BASE_URL", "http://backend:8000/api").rstrip("/")
    VIZOR_API_KEY: str = os.getenv("VIZOR_API_KEY", "")
    VIZOR_SERVICE_TOKEN: str = os.getenv("VIZOR_SERVICE_TOKEN", "")

    # Inference
    INFERENCE_BACKEND: str = os.getenv("INFERENCE_BACKEND", "triton")
    TRITON_URL: str = os.getenv("TRITON_URL", "triton:8000")

    # Frame source (go2rtc restream)
    GO2RTC_RTSP_HOST: str = os.getenv("GO2RTC_RTSP_HOST", "go2rtc")
    GO2RTC_RTSP_PORT: int = int(os.getenv("GO2RTC_RTSP_PORT", "8554"))
    LIVE_USE_SUBSTREAM: bool = env_bool("LIVE_USE_SUBSTREAM", False)
    # "cuda" -> NVDEC hardware decode (production, many cameras); "none" -> software.
    LIVE_HWACCEL: str = os.getenv("LIVE_HWACCEL", "none").lower()
    LIVE_FPS: float = float(os.getenv("LIVE_FPS", "5"))
    LIVE_STALL_TIMEOUT: int = int(os.getenv("LIVE_STALL_TIMEOUT", "20"))
    LIVE_POLL_SECONDS: int = int(os.getenv("LIVE_POLL_SECONDS", "15"))

    # Storage / retention
    DATA_PATH: Path = Path(os.getenv("DATA_PATH", "/data"))
    RETENTION_EVENT_DAYS: int = int(os.getenv("RETENTION_EVENT_DAYS", "90"))
    RETENTION_SWEEP_HOURS: float = float(os.getenv("RETENTION_SWEEP_HOURS", "6"))
    RETENTION_BATCH: int = int(os.getenv("RETENTION_BATCH", "2000"))
    DISK_WARN_PERCENT: float = float(os.getenv("DISK_WARN_PERCENT", "90"))

    # Vectors (scenarios that use Qdrant)
    QDRANT_URL: str = os.getenv("QDRANT_URL", "").rstrip("/")

    def rtsp_url(self, stream_id: str) -> str:
        """go2rtc restream URL for a camera/stream id."""
        return f"rtsp://{self.GO2RTC_RTSP_HOST}:{self.GO2RTC_RTSP_PORT}/{stream_id}"
