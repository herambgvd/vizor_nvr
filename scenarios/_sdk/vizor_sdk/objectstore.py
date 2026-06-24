"""Shared object-store client for AI scenario plugins — RustFS / S3-compatible.

A thin synchronous boto3 wrapper used by the plugins (FRS ID documents now; PPE/
ANPR/SuspectSearch media later). Reads its config from the environment so every
plugin shares one bucket without a DB round-trip:

  RUSTFS_ENDPOINT    (default http://rustfs:9000)
  RUSTFS_ACCESS_KEY  (default rustfsadmin)
  RUSTFS_SECRET_KEY  (default rustfsadmin)
  RUSTFS_BUCKET      (default vizor-ai)

Usage:
    from vizor_sdk.objectstore import default_store
    store = default_store()
    key = store.put("frs/ids/<person>/<uuid>.pdf", data, "application/pdf")
    url = store.presigned_url(key)            # browser-fetchable, time-limited
    data = store.get(key)
    store.delete(key)

Fail-soft: if boto3 isn't installed or the store is unreachable, methods raise a
clear RuntimeError (callers decide whether that's fatal). The client is lazy and
ensures the bucket exists on first use.
"""
from __future__ import annotations

import os
import threading
from typing import Optional

try:
    import boto3
    from botocore.client import Config as _BotoConfig
    from botocore.exceptions import ClientError
    _HAS_BOTO3 = True
except ImportError:  # pragma: no cover
    _HAS_BOTO3 = False


class ObjectStore:
    def __init__(self, *, endpoint: str, access_key: str, secret_key: str,
                 bucket: str, region: str = "us-east-1"):
        self.endpoint = endpoint.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.region = region
        self._client = None
        self._bucket_ready = False
        self._lock = threading.Lock()

    # ── connection ──────────────────────────────────────────────────────────
    def _conn(self):
        if self._client is not None:
            return self._client
        if not _HAS_BOTO3:
            raise RuntimeError("boto3 not installed — object storage unavailable")
        with self._lock:
            if self._client is None:
                self._client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name=self.region,
                    config=_BotoConfig(signature_version="s3v4",
                                       s3={"addressing_style": "path"}),
                )
        return self._client

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        c = self._conn()
        try:
            c.head_bucket(Bucket=self.bucket)
        except ClientError:
            try:
                c.create_bucket(Bucket=self.bucket)
            except ClientError as exc:  # already exists / race — fine
                if exc.response.get("Error", {}).get("Code") not in (
                    "BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    raise
        self._bucket_ready = True

    # ── operations ──────────────────────────────────────────────────────────
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Store bytes under `key`; returns the key."""
        self._ensure_bucket()
        self._conn().put_object(Bucket=self.bucket, Key=key, Body=data,
                                ContentType=content_type)
        return key

    def get(self, key: str) -> bytes:
        self._ensure_bucket()
        obj = self._conn().get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self._conn().head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete(self, key: str) -> None:
        try:
            self._conn().delete_object(Bucket=self.bucket, Key=key)
        except ClientError:
            pass

    def presigned_url(self, key: str, ttl: int = 3600) -> str:
        """Time-limited GET URL the browser can fetch directly."""
        self._ensure_bucket()
        return self._conn().generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=ttl)


_DEFAULT: Optional[ObjectStore] = None
_DEFAULT_LOCK = threading.Lock()


def default_store() -> ObjectStore:
    """Process-wide ObjectStore built from the RUSTFS_* environment."""
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = ObjectStore(
                    endpoint=os.getenv("RUSTFS_ENDPOINT", "http://rustfs:9000"),
                    access_key=os.getenv("RUSTFS_ACCESS_KEY", "rustfsadmin"),
                    secret_key=os.getenv("RUSTFS_SECRET_KEY", "rustfsadmin"),
                    bucket=os.getenv("RUSTFS_BUCKET", "vizor-ai"),
                )
    return _DEFAULT
