# =============================================================================
# Rate Limiter — Redis-preferred with in-memory fallback
# =============================================================================
# In production with multiple workers, REDIS_URL should be set so all
# workers share the same rate-limit counters.  In single-node dev mode
# the in-memory fallback works fine.
# =============================================================================

import time
import asyncio
import logging
from collections import defaultdict
from typing import Callable, Optional
from functools import wraps

from fastapi import Request, HTTPException, status

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Sliding-window rate limiter.

    Redis is used automatically when REDIS_URL is configured;
    otherwise falls back to per-process in-memory tracking.
    """

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 60,
        key_func: Optional[Callable[[Request], str]] = None,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.key_func = key_func or self._default_key
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._redis: Optional[Any] = None
        self._redis_init_attempted: bool = False

    def _default_key(self, request: Request) -> str:
        """Extract client IP for rate limiting key."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        return request.client.host if request.client else "unknown"

    async def _get_redis(self):
        """Lazy-initialize Redis once. Returns None if not configured or unreachable."""
        if self._redis_init_attempted:
            return self._redis
        self._redis_init_attempted = True

        from app.config import settings as _s
        if not _s.REDIS_URL:
            logger.debug("RateLimiter: REDIS_URL not set — using in-memory backend")
            return None

        try:
            import redis.asyncio as redis_asyncio
            self._redis = redis_asyncio.from_url(
                _s.REDIS_URL, decode_responses=True, socket_connect_timeout=2
            )
            await self._redis.ping()
            logger.info(f"RateLimiter: Redis backend active ({_s.REDIS_URL})")
        except Exception as e:
            logger.warning(
                f"RateLimiter: Redis init failed ({e}) — falling back to in-memory. "
                "Set REDIS_URL for shared rate-limiting across workers."
            )
            self._redis = None
        return self._redis

    async def _cleanup_old_entries(self):
        """Periodically remove expired entries to prevent memory leak (in-memory only)."""
        while True:
            await asyncio.sleep(300)  # Cleanup every 5 minutes
            try:
                async with self._lock:
                    now = time.time()
                    cutoff = now - self.window_seconds
                    to_delete = []
                    for key, timestamps in self._requests.items():
                        self._requests[key] = [t for t in timestamps if t > cutoff]
                        if not self._requests[key]:
                            to_delete.append(key)
                    for key in to_delete:
                        del self._requests[key]
            except Exception as e:
                logger.error(f"Rate limiter cleanup error: {e}")

    def start_cleanup(self):
        """Start background cleanup task (in-memory mode only)."""
        if not self._cleanup_task or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_old_entries())

    async def is_rate_limited(self, request: Request) -> tuple[bool, int]:
        """Sliding-window check. Prefers Redis; falls back to in-memory."""
        key = self.key_func(request)
        now = time.time()
        cutoff = now - self.window_seconds

        redis = await self._get_redis()
        if redis is not None:
            rk = f"rl:{self.window_seconds}:{self.max_requests}:{key}"
            try:
                pipe = redis.pipeline()
                pipe.zremrangebyscore(rk, 0, cutoff)
                pipe.zcard(rk)
                pipe.zadd(rk, {f"{now}:{id(request)}": now})
                pipe.expire(rk, self.window_seconds + 5)
                _, count_before, _, _ = await pipe.execute()
                if count_before >= self.max_requests:
                    # Over limit — remove the entry we just added
                    await redis.zremrangebyrank(rk, -1, -1)
                    oldest = await redis.zrange(rk, 0, 0, withscores=True)
                    oldest_ts = oldest[0][1] if oldest else now
                    retry_after = int(oldest_ts + self.window_seconds - now) + 1
                    return True, max(1, retry_after)
                return False, 0
            except Exception as e:
                logger.warning(f"RateLimiter: Redis op failed ({e}) — falling back to memory")
                # Fall through to in-memory path

        async with self._lock:
            self._requests[key] = [t for t in self._requests[key] if t > cutoff]

            if len(self._requests[key]) >= self.max_requests:
                oldest = min(self._requests[key])
                retry_after = int(oldest + self.window_seconds - now) + 1
                return True, max(1, retry_after)

            self._requests[key].append(now)
            return False, 0

    async def limit(self, request: Request):
        """FastAPI dependency for rate limiting."""
        is_limited, retry_after = await self.is_rate_limited(request)
        if is_limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests. Please wait {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )


# =============================================================================
# Pre-configured limiters for different endpoints
# =============================================================================
# Defaults are production-safe. In development (ENV=development) limits
# are bumped 20x so the dashboard, hot-reload, and test scripts don't
# trip the limiter. Override at runtime via env vars when needed.

import os

_DEV = os.getenv("ENV", "production").lower() in ("development", "dev", "local")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# Strict limiter for login/register
auth_limiter = RateLimiter(
    max_requests=_env_int("AUTH_RATE_LIMIT", 100 if _DEV else 5),
    window_seconds=_env_int("AUTH_RATE_WINDOW", 60),
)

# Standard API limiter
api_limiter = RateLimiter(
    max_requests=_env_int("API_RATE_LIMIT", 1000 if _DEV else 60),
    window_seconds=_env_int("API_RATE_WINDOW", 60),
)

# Sensitive ops (password reset, etc.)
strict_limiter = RateLimiter(
    max_requests=_env_int("STRICT_RATE_LIMIT", 30 if _DEV else 3),
    window_seconds=_env_int("STRICT_RATE_WINDOW", 60),
)
