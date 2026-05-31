# =============================================================================
# LicenseService — load, verify, and gate access to licensed resources.
#
# Lifecycle:
#   1. Backend boots → service.load_persisted() reads data/license.lic
#   2. Ed25519 signature verified against vendor public key
#   3. Fingerprint compared (warn if mismatch, hard-fail in strict mode)
#   4. Expiration checked (7-day grace period after expiry)
#   5. Cached as singleton; mutation endpoints call gate methods
#
# License file format on disk: single base64 string.
#   bytes 0..63   — Ed25519 signature (64 bytes)
#   bytes 64..    — payload JSON (UTF-8)
# =============================================================================

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .fingerprint import get_or_create_fingerprint
from .keys import load_public_key

logger = logging.getLogger(__name__)

LICENSE_FILE = Path(
    os.getenv("LICENSE_FILE")
    or os.path.join(os.getenv("DATA_PATH", "/app/data"), "license.lic")
)
GRACE_DAYS = int(os.getenv("LICENSE_GRACE_DAYS", "7"))


@dataclass
class LicensePayload:
    customer: str
    license_id: str
    issued_at: str
    expires_at: str
    hardware_fingerprint: Optional[str] = None
    camera_limit: int = 0
    features: List[str] = field(default_factory=list)
    tier: str = "free"
    # AI: licensed scenario slugs + the per-AI-camera cap applied to each.
    scenarios: List[str] = field(default_factory=list)
    ai_camera_limit: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "LicensePayload":
        return cls(
            customer=d.get("customer", ""),
            license_id=d.get("license_id", ""),
            issued_at=d.get("issued_at", ""),
            expires_at=d.get("expires_at", ""),
            hardware_fingerprint=d.get("hardware_fingerprint"),
            camera_limit=int(d.get("camera_limit", 0)),
            features=list(d.get("features", []) or []),
            tier=d.get("tier", "free"),
            scenarios=list(d.get("scenarios", []) or []),
            ai_camera_limit=int(d.get("ai_camera_limit", 0)),
        )


@dataclass
class LicenseStatus:
    valid: bool
    in_grace: bool
    fingerprint_match: bool
    days_remaining: int
    reason: Optional[str]
    payload: Optional[LicensePayload]


class LicenseError(Exception):
    pass


def _parse_iso(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


class LicenseService:
    def __init__(self) -> None:
        self._payload: Optional[LicensePayload] = None
        self._status: Optional[LicenseStatus] = None
        self._fingerprint: str = ""
        self._lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def load_persisted(self) -> LicenseStatus:
        self._fingerprint = get_or_create_fingerprint()
        if not LICENSE_FILE.exists():
            self._status = LicenseStatus(
                valid=False,
                in_grace=False,
                fingerprint_match=False,
                days_remaining=0,
                reason="no_license_installed",
                payload=None,
            )
            self._payload = None
            return self._status

        try:
            blob = LICENSE_FILE.read_text().strip()
            status = self._verify_blob(blob)
            self._status = status
            self._payload = status.payload
            logger.info(
                "license loaded: valid=%s tier=%s expires=%s cameras=%s",
                status.valid,
                status.payload.tier if status.payload else "?",
                status.payload.expires_at if status.payload else "?",
                status.payload.camera_limit if status.payload else 0,
            )
            return status
        except Exception as e:
            logger.exception("license load failed")
            self._status = LicenseStatus(
                valid=False,
                in_grace=False,
                fingerprint_match=False,
                days_remaining=0,
                reason=f"load_error:{e}",
                payload=None,
            )
            self._payload = None
            return self._status

    async def activate(self, blob: str) -> LicenseStatus:
        """Verify + persist a new license blob. Called from
        POST /api/license/activate."""
        async with self._lock:
            status = self._verify_blob(blob)
            if not status.valid and not status.in_grace:
                raise LicenseError(status.reason or "invalid_license")
            try:
                LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
                LICENSE_FILE.write_text(blob.strip())
            except Exception as e:
                raise LicenseError(f"write_failed:{e}")
            self._status = status
            self._payload = status.payload
            return status

    # ── Verification ──────────────────────────────────────────────────

    def _verify_blob(self, blob: str) -> LicenseStatus:
        try:
            raw = base64.b64decode(blob.strip())
        except Exception:
            return LicenseStatus(False, False, False, 0, "decode_failed", None)
        if len(raw) < 65:
            return LicenseStatus(False, False, False, 0, "too_short", None)
        signature = raw[:64]
        payload_bytes = raw[64:]

        try:
            pub = load_public_key()
            pub.verify(signature, payload_bytes)
        except Exception:
            return LicenseStatus(False, False, False, 0, "bad_signature", None)

        try:
            d = json.loads(payload_bytes.decode("utf-8"))
            payload = LicensePayload.from_dict(d)
        except Exception as e:
            return LicenseStatus(False, False, False, 0, f"parse_failed:{e}", None)

        # Expiration. An empty expires_at means a perpetual license — valid
        # forever (subject to the fingerprint check below).
        now = datetime.now(timezone.utc)
        days_remaining = 0
        in_grace = False
        valid = False
        reason: Optional[str] = None
        if not (payload.expires_at or "").strip():
            valid = True
            days_remaining = -1  # sentinel: perpetual
        elif not (exp := _parse_iso(payload.expires_at)):
            reason = "missing_expires_at"
        else:
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            delta = exp - now
            days_remaining = int(delta.total_seconds() // 86400)
            if delta.total_seconds() >= 0:
                valid = True
            elif delta.total_seconds() >= -GRACE_DAYS * 86400:
                in_grace = True
                reason = "in_grace_period"
            else:
                reason = "expired"

        # Hardware fingerprint binding
        fp_match = True
        if payload.hardware_fingerprint:
            fp_match = payload.hardware_fingerprint == self._fingerprint
            if not fp_match:
                valid = False
                reason = "hardware_mismatch"

        return LicenseStatus(
            valid=valid,
            in_grace=in_grace,
            fingerprint_match=fp_match,
            days_remaining=days_remaining,
            reason=reason,
            payload=payload,
        )

    # ── Accessors used by enforcement ─────────────────────────────────

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def status(self) -> LicenseStatus:
        return self._status or LicenseStatus(
            False, False, False, 0, "not_loaded", None,
        )

    def is_active(self) -> bool:
        s = self.status
        return bool(s.payload) and (s.valid or s.in_grace)

    def camera_limit(self) -> int:
        return self._payload.camera_limit if (self._payload and self.is_active()) else 0

    def features(self) -> List[str]:
        return list(self._payload.features) if (self._payload and self.is_active()) else []

    def scenarios(self) -> List[str]:
        return list(self._payload.scenarios) if (self._payload and self.is_active()) else []

    def ai_camera_limit(self) -> int:
        return self._payload.ai_camera_limit if (self._payload and self.is_active()) else 0

    # ── Snapshot for /api/license ─────────────────────────────────────

    def snapshot(self, camera_count: int) -> dict:
        s = self.status
        p = s.payload
        return {
            "active": self.is_active(),
            "valid": s.valid,
            "in_grace": s.in_grace,
            "fingerprint": self._fingerprint,
            "fingerprint_match": s.fingerprint_match,
            "days_remaining": s.days_remaining,
            "reason": s.reason,
            "customer": p.customer if p else None,
            "tier": p.tier if p else None,
            "license_id": p.license_id if p else None,
            "expires_at": p.expires_at if p else None,
            "camera_limit": p.camera_limit if p else 0,
            "features": list(p.features) if p else [],
            "usage": {
                "cameras": camera_count,
            },
        }


_singleton: Optional[LicenseService] = None


def get_license_service() -> LicenseService:
    global _singleton
    if _singleton is None:
        _singleton = LicenseService()
    return _singleton
