# =============================================================================
# TOTP (Time-based One-Time Password) — Phase 5.3
# =============================================================================
#
# Standard RFC 6238 implementation compatible with Google Authenticator,
# 1Password, Authy, etc. Secret stored AES-encrypted (via app.core.crypto)
# on the User row. Verification window is ±1 step (30 s) to absorb client
# clock drift.
# =============================================================================

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
import urllib.parse


def generate_secret(num_bytes: int = 20) -> str:
    """RFC 4226 recommends 160-bit secrets. Returns Base32 (no padding)."""
    return base64.b32encode(os.urandom(num_bytes)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = 6) -> str:
    secret = base64.b32decode(secret_b32 + "=" * ((8 - len(secret_b32) % 8) % 8))
    msg = struct.pack(">Q", counter)
    mac = hmac.new(secret, msg, hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (
        ((mac[offset] & 0x7F) << 24)
        | ((mac[offset + 1] & 0xFF) << 16)
        | ((mac[offset + 2] & 0xFF) << 8)
        | (mac[offset + 3] & 0xFF)
    )
    return str(code % (10 ** digits)).zfill(digits)


def current_code(secret_b32: str, step: int = 30, digits: int = 6) -> str:
    return _hotp(secret_b32, int(time.time() // step), digits)


def verify(secret_b32: str, token: str, step: int = 30, digits: int = 6,
           window: int = 1) -> bool:
    """Return True if *token* matches the current 30-s window ± 1 step.
    Constant-time compare to avoid leaking which window matched."""
    if not token or not token.isdigit() or len(token) != digits:
        return False
    counter = int(time.time() // step)
    for offset in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + offset, digits), token):
            return True
    return False


def provisioning_uri(username: str, secret_b32: str, issuer: str = "GVD NVR") -> str:
    """otpauth://totp URI that 2FA apps render as a QR code."""
    label = urllib.parse.quote(f"{issuer}:{username}")
    params = urllib.parse.urlencode({
        "secret": secret_b32,
        "issuer": issuer,
        "digits": 6,
        "period": 30,
        "algorithm": "SHA1",
    })
    return f"otpauth://totp/{label}?{params}"


def generate_recovery_codes(count: int = 10) -> list:
    """Recovery codes are single-use; ~80 bits of entropy each."""
    return [secrets.token_hex(5) for _ in range(count)]
