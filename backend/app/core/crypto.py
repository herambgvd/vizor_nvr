# =============================================================================
# Crypto Utilities — Fernet encryption for sensitive data at rest
# =============================================================================
#
# Used for encrypting ONVIF credentials (username + password), cloud storage
# secrets, and any other sensitive value stored in the database.
#
# Key derivation: SHA-256(JWT_SECRET_KEY || machine_fingerprint).
#   - JWT_SECRET_KEY is the operator-provided secret.
#   - machine_fingerprint binds the ciphertext to *this* host so that a stolen
#     database dump cannot be decrypted with a leaked .env on a different
#     machine. Sources: /etc/machine-id, /var/lib/dbus/machine-id, or a
#     persistent fallback written to data/.machine_id on first run.
#
# Backwards compatibility: a legacy key derived from JWT_SECRET_KEY alone is
# kept as a secondary MultiFernet key so historical ciphertexts written before
# the machine-fingerprint upgrade still decrypt. New writes always use the
# fingerprinted primary key.
# =============================================================================

import base64
import hashlib
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import settings

logger = logging.getLogger(__name__)


# ── Machine fingerprint ──────────────────────────────────────────────────────

_machine_fingerprint_cache: Optional[str] = None


def _read_first(*paths: str) -> Optional[str]:
    for p in paths:
        try:
            v = Path(p).read_text().strip()
            if v:
                return v
        except (OSError, PermissionError):
            continue
    return None


def _machine_fingerprint() -> str:
    """Stable per-host identifier used as part of the encryption key.

    Resolution order:
      1. /etc/machine-id (systemd / most Linux distros)
      2. /var/lib/dbus/machine-id (older Linux)
      3. data/.machine_id (operator-writable fallback; created on first run
         using uuid.getnode() — MAC-derived — and a random component)
    """
    global _machine_fingerprint_cache
    if _machine_fingerprint_cache is not None:
        return _machine_fingerprint_cache

    fp = _read_first("/etc/machine-id", "/var/lib/dbus/machine-id")
    if not fp:
        # Persist a stable ID under DATA_PATH so the key survives reboots
        # even on systems without machine-id.
        data_dir = getattr(settings, "DATA_PATH", None) or Path("./data")
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        fallback = Path(data_dir) / ".machine_id"
        if fallback.exists():
            fp = fallback.read_text().strip()
        else:
            # uuid.getnode() = MAC; combined with a random UUID so two hosts
            # behind NAT with the same MAC (rare but possible) still differ.
            fp = f"{uuid.getnode():012x}-{uuid.uuid4().hex}"
            fallback.write_text(fp)
            try:
                os.chmod(fallback, 0o600)
            except OSError:
                pass

    _machine_fingerprint_cache = fp
    return fp


# ── Key derivation ───────────────────────────────────────────────────────────

def _derive_fernet_key(material: str) -> bytes:
    """SHA-256 → urlsafe-base64 = 32-byte Fernet key."""
    return base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())


_cipher: Optional[MultiFernet] = None


def _build_cipher() -> MultiFernet:
    """Primary key includes machine fingerprint; legacy key (secret-only) is
    kept as a fallback so pre-upgrade ciphertexts continue to decrypt."""
    primary = _derive_fernet_key(settings.JWT_SECRET_KEY + ":" + _machine_fingerprint())
    legacy = _derive_fernet_key(settings.JWT_SECRET_KEY)
    return MultiFernet([Fernet(primary), Fernet(legacy)])


def get_cipher() -> MultiFernet:
    global _cipher
    if _cipher is None:
        _cipher = _build_cipher()
    return _cipher


def reset_cipher_cache() -> None:
    """Reset memoized cipher (used in tests + after fingerprint regeneration)."""
    global _cipher, _machine_fingerprint_cache
    _cipher = None
    _machine_fingerprint_cache = None


# ── Public API ───────────────────────────────────────────────────────────────

ENC_PREFIX = "enc:"


def encrypt_value(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a string. Idempotent: already-encrypted values pass through.
    Empty / None values pass through unchanged."""
    if not plaintext:
        return plaintext
    if plaintext.startswith(ENC_PREFIX):
        return plaintext
    try:
        token = get_cipher().encrypt(plaintext.encode())
        return f"{ENC_PREFIX}{token.decode()}"
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise ValueError("Failed to encrypt value")


def decrypt_value(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt a string previously produced by encrypt_value. If the value is
    not encrypted (no 'enc:' prefix) it is returned unchanged — this covers
    legacy plaintext rows until backfill_encrypt_credentials() rotates them.

    Tries primary key first; falls back to the legacy (secret-only) key via
    MultiFernet so ciphertexts written before the machine-fingerprint upgrade
    keep working without a forced re-encryption."""
    if not ciphertext:
        return ciphertext
    if not ciphertext.startswith(ENC_PREFIX):
        return ciphertext
    try:
        return get_cipher().decrypt(ciphertext[len(ENC_PREFIX):].encode()).decode()
    except InvalidToken:
        logger.error("Decryption failed: token cannot be verified with current keys")
        raise ValueError("Failed to decrypt value - invalid token")
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        raise ValueError("Failed to decrypt value")


def is_encrypted(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(ENC_PREFIX)


# ── One-shot backfill (startup hook) ─────────────────────────────────────────

async def backfill_encrypt_credentials() -> int:
    """Re-encrypt any plaintext ONVIF credentials in the cameras table.

    Run once on startup. Idempotent: already-encrypted rows are skipped.
    Returns the number of rows updated (for logging)."""
    from sqlalchemy import select, update
    from app.database import async_session_maker
    from app.cameras.models import Camera

    updated = 0
    async with async_session_maker() as db:
        result = await db.execute(select(Camera))
        for cam in result.scalars().all():
            changed = False
            if cam.onvif_password and not is_encrypted(cam.onvif_password):
                cam.onvif_password = encrypt_value(cam.onvif_password)
                changed = True
            if cam.onvif_username and not is_encrypted(cam.onvif_username):
                cam.onvif_username = encrypt_value(cam.onvif_username)
                changed = True
            if changed:
                updated += 1
        if updated:
            await db.commit()
    if updated:
        logger.info(f"backfill_encrypt_credentials: re-encrypted {updated} camera row(s)")
    return updated
