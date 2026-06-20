# =============================================================================
# TLS Service — self-signed cert generation, custom upload, status reporting
# =============================================================================
#
# Nginx terminates TLS; the backend's job here is to *manage* the cert+key
# files on a shared volume. The container layout assumes:
#   - backend writes to settings.CERT_PATH/cert.pem & key.pem
#   - nginx reads /etc/nginx/ssl/cert.pem & key.pem (mounted from the same vol)
#
# Operations exposed via /api/settings/tls/* endpoints:
#   - generate_self_signed: emit a fresh self-signed cert (1 year validity)
#   - install_custom: accept operator-supplied cert + key, validate, persist
#   - status: parse the current cert and return CN, issuer, expiry, fingerprint
# =============================================================================

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.config import settings

logger = logging.getLogger(__name__)


CERT_FILENAME = "cert.pem"
KEY_FILENAME = "key.pem"


@dataclass
class TLSStatus:
    present: bool
    self_signed: bool
    common_name: Optional[str]
    issuer: Optional[str]
    not_before: Optional[datetime]
    not_after: Optional[datetime]
    days_until_expiry: Optional[int]
    fingerprint_sha256: Optional[str]
    cert_path: str
    key_path: str

    def to_dict(self) -> dict:
        return {
            "present": self.present,
            "self_signed": self.self_signed,
            "common_name": self.common_name,
            "issuer": self.issuer,
            "not_before": self.not_before.isoformat() if self.not_before else None,
            "not_after": self.not_after.isoformat() if self.not_after else None,
            "days_until_expiry": self.days_until_expiry,
            "fingerprint_sha256": self.fingerprint_sha256,
            "cert_path": self.cert_path,
            "key_path": self.key_path,
        }


def cert_path() -> Path:
    return Path(settings.CERT_PATH) / CERT_FILENAME


def key_path() -> Path:
    return Path(settings.CERT_PATH) / KEY_FILENAME


def _write_secure(path: Path, data: bytes) -> None:
    """Write data with 0600 permissions atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def _mirror_to_nginx(cert_bytes: bytes, key_bytes: bytes) -> None:
    """If NGINX_CERT_PATH is configured, copy the cert/key there too so the
    nginx container reload picks them up. Best-effort — failures logged only."""
    nginx_dir = settings.NGINX_CERT_PATH
    if not nginx_dir:
        return
    try:
        ndir = Path(nginx_dir)
        ndir.mkdir(parents=True, exist_ok=True)
        _write_secure(ndir / CERT_FILENAME, cert_bytes)
        _write_secure(ndir / KEY_FILENAME, key_bytes)
    except Exception as e:
        logger.warning(f"TLS: failed to mirror cert to nginx path {nginx_dir}: {e}")


def generate_self_signed(
    common_name: str = "gvd-nvr.local",
    days_valid: int = 365,
) -> TLSStatus:
    """Generate a 2048-bit RSA self-signed cert + key at CERT_PATH.

    Overwrites any existing files. Returns the new status.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Vizor NVR (self-signed)"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days_valid))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common_name)]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    key_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    _write_secure(cert_path(), cert_bytes)
    _write_secure(key_path(), key_bytes)
    _mirror_to_nginx(cert_bytes, key_bytes)
    logger.info(f"TLS: generated self-signed cert CN={common_name} valid {days_valid}d")
    return status()


def install_custom(cert_pem: bytes, key_pem: bytes) -> TLSStatus:
    """Validate operator-supplied PEM cert + key, persist if both parse and
    the key matches the cert's public key. Raises ValueError on validation
    failure so the router returns HTTP 400."""
    try:
        cert = x509.load_pem_x509_certificate(cert_pem)
    except Exception as e:
        logger.warning(f"TLS install: certificate parse failed: {e}")
        raise ValueError("The certificate file is not valid. Please upload a valid PEM certificate.")
    try:
        priv = serialization.load_pem_private_key(key_pem, password=None)
    except Exception as e:
        logger.warning(f"TLS install: private key parse failed: {e}")
        raise ValueError("The private key file is not valid. Please upload a valid PEM private key.")

    # Key/cert match check — public key bytes must be identical
    cert_pub = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if cert_pub != key_pub:
        raise ValueError("Private key does not match certificate public key")

    _write_secure(cert_path(), cert_pem)
    _write_secure(key_path(), key_pem)
    _mirror_to_nginx(cert_pem, key_pem)
    logger.info("TLS: installed custom cert")
    return status()


def _read_cert() -> Optional[x509.Certificate]:
    cp = cert_path()
    if not cp.exists():
        return None
    try:
        return x509.load_pem_x509_certificate(cp.read_bytes())
    except Exception as e:
        logger.warning(f"TLS: cannot parse cert at {cp}: {e}")
        return None


def status() -> TLSStatus:
    cp, kp = cert_path(), key_path()
    cert = _read_cert()
    if cert is None or not kp.exists():
        return TLSStatus(
            present=False, self_signed=False,
            common_name=None, issuer=None,
            not_before=None, not_after=None, days_until_expiry=None,
            fingerprint_sha256=None,
            cert_path=str(cp), key_path=str(kp),
        )

    def _cn(name: x509.Name) -> Optional[str]:
        try:
            return name.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        except (IndexError, AttributeError):
            return None

    subj_cn = _cn(cert.subject)
    issuer_cn = _cn(cert.issuer)
    not_before = cert.not_valid_before_utc
    not_after = cert.not_valid_after_utc
    days_left = max(0, int((not_after - datetime.now(timezone.utc)).total_seconds() // 86400))
    fp = cert.fingerprint(hashes.SHA256()).hex(":")

    return TLSStatus(
        present=True,
        self_signed=(subj_cn == issuer_cn),
        common_name=subj_cn,
        issuer=issuer_cn,
        not_before=not_before,
        not_after=not_after,
        days_until_expiry=days_left,
        fingerprint_sha256=fp,
        cert_path=str(cp),
        key_path=str(kp),
    )


def ensure_present() -> TLSStatus:
    """Lifespan hook: generate a self-signed cert if none exists yet. Safe
    to call on every boot — no-op when a cert is already present."""
    st = status()
    if st.present:
        return st
    logger.info("TLS: no certificate found, generating self-signed")
    return generate_self_signed()
