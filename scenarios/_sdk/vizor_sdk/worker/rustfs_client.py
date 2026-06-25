"""Single-tenant RustFS (S3-compatible) client (ported from vizor-gpu).

The NVR worker is single-tenant, so object keys are NOT prefixed with a
tenant id — keys are just the suffix passed in (e.g. `{use_case}/snaps/...`).
Every method drops its `tenant_id` parameter.

vizor-gpu used aiobotocore for fully-async I/O; the NVR SDK ships plain `boto3`
(see ``vizor_sdk/objectstore.py``), so this port keeps the async surface but
runs the blocking boto3 calls in a worker thread via ``asyncio.to_thread``.

Carries the optional circuit breaker through: repeated failures short-circuit
via ``breaker.call_async(...)`` so pipelines can degrade to event-only mode.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

try:
    import boto3
    from botocore.config import Config as _BotoConfig
    _HAS_BOTO3 = True
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    _BotoConfig = None  # type: ignore[assignment]
    _HAS_BOTO3 = False

from .circuit_breaker import CircuitBreaker, CircuitOpenError  # noqa: F401

logger = logging.getLogger("vizor.worker.rustfs")


class RustFSClient:
    """Thin async wrapper over boto3 S3 (single-tenant, no key scoping).

    boto3 is synchronous, so each operation is dispatched to a thread via
    ``asyncio.to_thread`` to keep the async call surface from vizor-gpu.

    Example::

        rfs = RustFSClient("http://rustfs:9000", "ak", "sk", "vizor-media")
        key = await rfs.put_object("snaps/2026-04/e1.jpg", data, "image/jpeg")
        url = await rfs.get_presigned_url("snaps/2026-04/e1.jpg")
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
        public_endpoint: str | None = None,
        breaker: CircuitBreaker | None = None,
    ):
        if not _HAS_BOTO3:
            raise RuntimeError("boto3 not installed — object storage unavailable")
        self.endpoint = endpoint
        # Public endpoint is for browser-fetchable presigned URLs. When
        # not supplied we fall back to the internal endpoint — that's
        # almost certainly wrong for browsers but matches legacy
        # behavior. Callers should always pass it explicitly now.
        self.public_endpoint = public_endpoint or endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.region = region
        self._s3 = None
        self._s3_public = None
        self._bucket_ready = False
        self._breaker = breaker

    async def _guard(self, coro_fn, *args, **kwargs):
        """Run an awaitable behind the optional circuit breaker. Keeps
        the put/get/delete code paths free of breaker boilerplate."""
        if self._breaker is None:
            return await coro_fn(*args, **kwargs)
        return await self._breaker.call_async(coro_fn, *args, **kwargs)

    @staticmethod
    def _signing_config():
        """Path-style + s3v4 signing matches every RustFS deploy we ship,
        and works for both compose-DNS endpoints and IP literals. The
        previous default (virtual-host addressing) breaks signature
        verification on IP endpoints."""
        return _BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        )

    def _get_s3(self):
        """Lazy-create a single persistent S3 client (boto3 clients are
        thread-safe for distinct operations)."""
        if self._s3 is None:
            self._s3 = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
                config=self._signing_config(),
            )
        return self._s3

    def _get_s3_public(self):
        """Lazy-create a single persistent public-endpoint S3 client."""
        if self._s3_public is None:
            self._s3_public = boto3.client(
                "s3",
                endpoint_url=self.public_endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
                config=self._signing_config(),
            )
        return self._s3_public

    async def close(self) -> None:
        """Close persistent clients (idempotent)."""
        if self._s3 is not None:
            try:
                self._s3.close()
            except Exception:
                pass
            self._s3 = None
        if self._s3_public is not None:
            try:
                self._s3_public.close()
            except Exception:
                pass
            self._s3_public = None

    @staticmethod
    def _full_key(key_suffix: str) -> str:
        return key_suffix.lstrip("/")

    def _put_object_sync(
        self, key_suffix: str, data: bytes, content_type: str,
    ) -> str:
        key = self._full_key(key_suffix)
        if not self._bucket_ready:
            self._ensure_bucket_sync()
            self._bucket_ready = True
        s3 = self._get_s3()
        s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        logger.debug("[rustfs] PUT %s/%s (%s bytes)", self.bucket, key, len(data))
        return key

    async def _put_object_inner(
        self, key_suffix: str, data: bytes, content_type: str,
    ) -> str:
        return await asyncio.to_thread(
            self._put_object_sync, key_suffix, data, content_type,
        )

    async def put_object(
        self,
        key_suffix: str,
        data: bytes,
        content_type: str,
    ) -> str:
        """Upload `data` under `{key_suffix}`; returns the full key.

        When a circuit breaker is wired, repeated failures short-circuit
        subsequent calls until the cool-down expires — pipelines that
        catch the breaker error can degrade to event-only mode
        (skip snapshot, still emit detection event).
        """
        return await self._guard(
            self._put_object_inner, key_suffix, data, content_type,
        )

    def _presigned_url_sync(self, key_suffix: str, expires: int) -> str:
        key = self._full_key(key_suffix)
        s3 = self._get_s3_public()
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires,
        )

    async def get_presigned_url(
        self,
        key_suffix: str,
        expires: int = 3600,
    ) -> str:
        """Generate a presigned GET URL (default 1h). Signed against
        `RUSTFS_PUBLIC_ENDPOINT` so the URL is browser-fetchable."""
        return await asyncio.to_thread(self._presigned_url_sync, key_suffix, expires)

    def _list_keys_sync(self, prefix: str) -> list[dict]:
        full_prefix = self._full_key(prefix) if prefix else ""
        out: list[dict] = []
        s3 = self._get_s3()
        paginator = s3.get_paginator("list_objects_v2")
        kwargs = {"Bucket": self.bucket}
        if full_prefix:
            kwargs["Prefix"] = full_prefix
        for page in paginator.paginate(**kwargs):
            for o in page.get("Contents", []):
                out.append({
                    "key": o["Key"],
                    "last_modified": o.get("LastModified"),
                    "size": int(o.get("Size") or 0),
                })
        return out

    async def list_keys(
        self,
        prefix: str = "",
    ) -> list[dict]:
        """List objects under `{prefix}` with metadata.

        Returns a list of `{"key": str, "last_modified": datetime,
        "size": int}` records. The `key` is the full object key (matches
        what `put_object`/`delete_prefix` expect). Paginates internally;
        safe on large prefixes.
        """
        return await asyncio.to_thread(self._list_keys_sync, prefix)

    def _delete_prefix_sync(self, prefix: str) -> int:
        full_prefix = self._full_key(prefix) if prefix else ""
        deleted = 0
        s3 = self._get_s3()
        paginator = s3.get_paginator("list_objects_v2")
        kwargs = {"Bucket": self.bucket}
        if full_prefix:
            kwargs["Prefix"] = full_prefix
        for page in paginator.paginate(**kwargs):
            objs = page.get("Contents", [])
            if not objs:
                continue
            s3.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": o["Key"]} for o in objs]},
            )
            deleted += len(objs)
        logger.info("[rustfs] deleted %s objects under %s", deleted, full_prefix)
        return deleted

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every object under `{prefix}`.

        Returns the count deleted. Paginates through listings so it's safe
        on very large prefixes.
        """
        return await self._guard(self._delete_prefix_inner, prefix)

    async def _delete_prefix_inner(self, prefix: str) -> int:
        return await asyncio.to_thread(self._delete_prefix_sync, prefix)

    def _ensure_bucket_sync(self) -> None:
        s3 = self._get_s3()
        try:
            s3.head_bucket(Bucket=self.bucket)
        except Exception:
            try:
                s3.create_bucket(Bucket=self.bucket)
                logger.info("[rustfs] created bucket %s", self.bucket)
            except Exception as e:  # pragma: no cover
                logger.warning("[rustfs] ensure_bucket failed: %s", e)

    async def ensure_bucket(self) -> None:
        """Create the bucket if it does not exist (idempotent)."""
        await asyncio.to_thread(self._ensure_bucket_sync)
