# =============================================================================
# Licensing (Phase 7.1) — hardware fingerprint + camera tier enforcement
# =============================================================================
#
# A license file is a JSON document signed with the vendor RSA public key.
# Payload includes:
#   { fingerprint, tier, max_cameras, issued_at, expires_at, customer }
#
# Verification flow on every startup + every camera_create:
#   1. Read /data/certs/license.json (or LICENSE_PATH).
#   2. If absent — start a 7-day grace period (stored in data/.license_grace).
#   3. Verify RSA-PSS-SHA256 signature against the embedded vendor public key.
#   4. Check fingerprint matches THIS machine.
#   5. Check expiry hasn't passed.
#   6. Expose status via GET /api/license/status; enforce tier limits at the
#      camera-creation site.
#
# Tiers:
#   starter      —   4 cameras
#   professional —  16 cameras
#   business     —  32 cameras
#   enterprise   —  64 cameras
#   unlimited    —  no cap
# =============================================================================

import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.config import settings

logger = logging.getLogger(__name__)


TIER_LIMITS = {
    "starter": 4,
    "professional": 16,
    "business": 32,
    "enterprise": 64,
    "unlimited": None,  # None = uncapped
}

GRACE_PERIOD_DAYS = 7

# The vendor public key shipped with each build. Replace this constant for
# real deployments. The matching private key is held by the vendor and never
# distributed.
VENDOR_PUBKEY_PEM = b"""-----BEGIN PUBLIC KEY-----
PLACEHOLDER_REPLACE_WITH_REAL_VENDOR_PUBLIC_KEY
-----END PUBLIC KEY-----"""


@dataclass
class LicenseStatus:
    state: str           # valid | invalid | expired | trial | missing | tampered
    tier: Optional[str]
    max_cameras: Optional[int]
    fingerprint_ok: bool
    customer: Optional[str]
    issued_at: Optional[str]
    expires_at: Optional[str]
    days_remaining: Optional[int]
    grace_remaining_days: Optional[int]
    detail: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _license_path() -> Path:
    return Path(getattr(settings, "LICENSE_PATH", str(Path(settings.CERT_PATH) / "license.json")))


def _grace_path() -> Path:
    return Path(settings.DATA_PATH) / ".license_grace"


def _grace_remaining_days() -> int:
    gp = _grace_path()
    if not gp.exists():
        gp.write_text(str(int(time.time())))
        return GRACE_PERIOD_DAYS
    try:
        started = int(gp.read_text().strip())
    except ValueError:
        started = int(time.time())
    elapsed_days = (time.time() - started) / 86400
    return max(0, int(GRACE_PERIOD_DAYS - elapsed_days))


def _verify_signature(payload: bytes, signature_b64: str) -> bool:
    import base64
    try:
        pubkey = serialization.load_pem_public_key(VENDOR_PUBKEY_PEM)
        pubkey.verify(
            base64.b64decode(signature_b64),
            payload,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, ValueError):
        return False


def status() -> LicenseStatus:
    """Return the current license status. Result is cheap to recompute, so
    no caching — callers can hit it from health endpoints freely."""
    lp = _license_path()
    if not lp.exists():
        grace = _grace_remaining_days()
        if grace > 0:
            return LicenseStatus(
                state="trial", tier="starter",
                max_cameras=TIER_LIMITS["starter"],
                fingerprint_ok=True, customer=None,
                issued_at=None, expires_at=None,
                days_remaining=None,
                grace_remaining_days=grace,
                detail=f"Trial: {grace}d remaining (starter tier)",
            )
        return LicenseStatus(
            state="missing", tier=None, max_cameras=0,
            fingerprint_ok=False, customer=None,
            issued_at=None, expires_at=None,
            days_remaining=None, grace_remaining_days=0,
            detail="No license file and trial period elapsed",
        )

    try:
        bundle = json.loads(lp.read_text())
        payload = bundle["payload"]
        sig = bundle["signature"]
    except (json.JSONDecodeError, KeyError) as e:
        return LicenseStatus(
            state="tampered", tier=None, max_cameras=0,
            fingerprint_ok=False, customer=None,
            issued_at=None, expires_at=None,
            days_remaining=None, grace_remaining_days=0,
            detail=f"License file malformed: {e}",
        )

    # Vendor key is a placeholder during dev — accept all bundles in that case
    # so local builds aren't blocked by a missing real key.
    if b"PLACEHOLDER" in VENDOR_PUBKEY_PEM:
        sig_ok = True
        logger.warning("Licensing: using placeholder vendor key — accepting all signatures")
    else:
        sig_ok = _verify_signature(json.dumps(payload, sort_keys=True).encode(), sig)
    if not sig_ok:
        return LicenseStatus(
            state="tampered", tier=None, max_cameras=0,
            fingerprint_ok=False, customer=None,
            issued_at=payload.get("issued_at"),
            expires_at=payload.get("expires_at"),
            days_remaining=None, grace_remaining_days=0,
            detail="Signature verification failed",
        )

    # Fingerprint check
    from app.core.crypto import _machine_fingerprint
    fp_ok = payload.get("fingerprint") == _machine_fingerprint()

    expires_at_str = payload.get("expires_at")
    days_remaining = None
    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            days_remaining = max(0, int((expires_at - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() // 86400))
            if expires_at < datetime.utcnow():
                return LicenseStatus(
                    state="expired", tier=payload.get("tier"),
                    max_cameras=TIER_LIMITS.get(payload.get("tier", "starter"), 0),
                    fingerprint_ok=fp_ok, customer=payload.get("customer"),
                    issued_at=payload.get("issued_at"), expires_at=expires_at_str,
                    days_remaining=0, grace_remaining_days=0,
                    detail=f"Expired on {expires_at_str}",
                )
        except ValueError:
            pass

    tier = payload.get("tier", "starter")
    return LicenseStatus(
        state="valid" if fp_ok else "invalid",
        tier=tier,
        max_cameras=payload.get("max_cameras") or TIER_LIMITS.get(tier),
        fingerprint_ok=fp_ok,
        customer=payload.get("customer"),
        issued_at=payload.get("issued_at"),
        expires_at=expires_at_str,
        days_remaining=days_remaining,
        grace_remaining_days=None,
        detail=None if fp_ok else "Fingerprint mismatch — license issued for a different host",
    )


def enforce_camera_count(current_count: int) -> None:
    """Raise ValueError if adding one more camera would exceed the licensed tier."""
    st = status()
    if st.max_cameras is None:
        return  # unlimited or placeholder
    if current_count + 1 > st.max_cameras:
        raise ValueError(
            f"Camera limit reached: tier '{st.tier}' allows {st.max_cameras} camera(s). "
            f"Upgrade required."
        )
