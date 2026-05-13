# =============================================================================
# Recording download tokens — short-lived, HMAC-signed, single-use
# =============================================================================
#
# A request to GET /{id}/download-token mints a token that grants exactly one
# download of one recording for 15 minutes. The actual download endpoint
# accepts either:
#   - a regular JWT access token (legacy / privileged flows), OR
#   - one of these signed tokens (preferred, shareable, single-use).
#
# This addresses TODO 5.9 / X.2: prevents hot-linking, link sharing, and
# replay across browsers. The signature binds (recording_id, user_id, expiry)
# so a leaked token cannot pivot to other recordings.
# =============================================================================

import hmac
import hashlib
import secrets
import time
from typing import Optional

from app.config import settings

TTL_SECONDS = 15 * 60
_used_tokens: set = set()
# Periodic cleanup happens lazily on each verify() — bounded by TTL window so
# this set never grows beyond the issuance rate × TTL.
_last_purge = 0.0


def _sign(payload: str) -> str:
    return hmac.new(
        settings.JWT_SECRET_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def issue(recording_id: str, user_id: str) -> dict:
    """Mint a one-shot download token for (recording_id, user_id)."""
    expiry = int(time.time()) + TTL_SECONDS
    nonce = secrets.token_hex(8)
    payload = f"{recording_id}:{user_id}:{expiry}:{nonce}"
    sig = _sign(payload)
    return {
        "token": f"{payload}:{sig}",
        "expires_at": expiry,
        "ttl_seconds": TTL_SECONDS,
    }


def verify(token: str, recording_id: str) -> Optional[str]:
    """Return the bound user_id if the token is valid for recording_id, else
    None. Side-effect: marks the token as used so a second call fails."""
    if not token or token.count(":") != 4:
        return None
    rid, uid, expiry_s, nonce, sig = token.split(":")
    if rid != recording_id:
        return None
    try:
        expiry = int(expiry_s)
    except ValueError:
        return None
    now = int(time.time())
    if now > expiry:
        return None
    expected = _sign(f"{rid}:{uid}:{expiry_s}:{nonce}")
    if not hmac.compare_digest(sig, expected):
        return None
    # Single-use enforcement
    if token in _used_tokens:
        return None
    _used_tokens.add(token)
    _maybe_purge(now)
    return uid


def _maybe_purge(now: int) -> None:
    """Drop tokens past their TTL. Cheap O(n) scan, only runs every TTL/2."""
    global _last_purge
    if now - _last_purge < TTL_SECONDS // 2:
        return
    _last_purge = now
    # Parse expiry from each entry — entries past TTL can never be reused
    # so they're safe to drop.
    stale = set()
    for t in _used_tokens:
        try:
            _, _, expiry_s, _, _ = t.split(":")
            if int(expiry_s) < now:
                stale.add(t)
        except ValueError:
            stale.add(t)
    _used_tokens.difference_update(stale)
