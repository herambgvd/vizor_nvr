"""Platform config cache — stub for the nvr single-tenant port.

In vizor-gpu this cached a superadmin-edited `platform_config:current` JSON blob in
Redis with pub/sub invalidation, so workers read tunables without hammering Redis.
nvr already delivers per-camera config through the HTTP control plane (the Command's
`config` dict), so a global platform-config blob isn't needed yet.

This stub keeps the import surface BaseWorker / clients expect (start/stop/get) but
just returns an empty dict. Wire it to Redis later if a global tunable store lands.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("vizor.worker.platform_config")


class PlatformConfigCache:
    def __init__(self, redis_url: str | None = None, key: str = "platform_config:current",
                 channel: str = "platform_config:updated", ttl_s: float = 30.0) -> None:
        self.redis_url = redis_url
        self.key = key
        self.channel = channel
        self.ttl_s = ttl_s
        self._cache: dict[str, Any] = {}

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def get(self) -> dict[str, Any]:
        return dict(self._cache)
