# =============================================================================
# Signed Evidence Export (Phase 4.6)
# =============================================================================
#
# Produces a tamper-evident bundle for legal/chain-of-custody use:
#   evidence_<recording_id>.zip
#     ├── <basename>.mp4               (original or remuxed-with-metadata)
#     ├── chain_of_custody.json        (camera/operator/timestamps/hash)
#     ├── chain_of_custody.txt         (human-readable variant)
#     └── signature.sig                (RSA-PSS-SHA256 over chain_of_custody.json)
#
# Signing key: data/certs/evidence_signing_key.pem — auto-generated on first
# export. Public key is exposed at GET /api/recordings/evidence/public-key so
# downstream verifiers can confirm authenticity.
# =============================================================================

import json
import logging
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.config import settings

logger = logging.getLogger(__name__)


def _key_path() -> Path:
    return Path(settings.CERT_PATH) / "evidence_signing_key.pem"


def _pub_path() -> Path:
    return Path(settings.CERT_PATH) / "evidence_signing_pub.pem"


def _ensure_signing_key() -> rsa.RSAPrivateKey:
    """Load the evidence signing key, generating + persisting one if missing.
    Key is 3072-bit RSA — comfortably above NIST 2030 baseline."""
    kp = _key_path()
    if kp.exists():
        priv = serialization.load_pem_private_key(kp.read_bytes(), password=None)
        return priv  # type: ignore[return-value]
    kp.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    kp.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    os.chmod(kp, 0o600)
    _pub_path().write_bytes(key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    logger.info(f"Evidence signing key generated at {kp}")
    return key


def public_key_pem() -> str:
    """Return PEM-encoded public key so verifiers can be handed a stable artifact."""
    _ensure_signing_key()  # idempotent
    return _pub_path().read_text()


def _sign(key: rsa.RSAPrivateKey, data: bytes) -> bytes:
    return key.sign(
        data,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )


def build_evidence_zip(
    recording: dict,
    operator: dict,
    output_dir: str,
    attach_snapshots: list = None,
) -> str:
    """Bundle a recording into a signed evidence zip. Returns the path to the
    zip file. *recording* must include: id, camera_id, camera_name, file_path,
    start_time, end_time, duration, checksum (or None if unverified yet)."""
    key = _ensure_signing_key()
    rec_id = recording["id"]
    src_path = recording["file_path"]
    if not os.path.exists(src_path):
        raise FileNotFoundError(src_path)

    # Recompute checksum at export time so the bundle's integrity attestation
    # is independent of whatever is stored in the DB.
    from app.recordings.service import RecordingService
    live_hash = RecordingService.compute_sha256(src_path)

    custody = {
        "schema": "gvd-nvr/evidence/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recording": {
            "id": rec_id,
            "camera_id": recording.get("camera_id"),
            "camera_name": recording.get("camera_name"),
            "file_path": src_path,
            "filename": os.path.basename(src_path),
            "start_time": str(recording.get("start_time")),
            "end_time": str(recording.get("end_time")),
            "duration_seconds": recording.get("duration"),
            "file_size_bytes": os.path.getsize(src_path),
            "sha256": live_hash,
            "checksum_at_record_time": recording.get("checksum"),
            "checksum_match": (recording.get("checksum") == live_hash) if recording.get("checksum") else None,
        },
        "operator": {
            "user_id": operator.get("id"),
            "username": operator.get("username"),
            "role": operator.get("role"),
        },
        "system": {
            "host_machine_fingerprint_hint": None,  # filled in below
            "nvr_version": _nvr_version(),
        },
    }
    # Add machine fingerprint hint (truncated) so two NVRs that both signed the
    # same file are distinguishable without leaking the full ID.
    try:
        from app.core.crypto import _machine_fingerprint
        custody["system"]["host_machine_fingerprint_hint"] = _machine_fingerprint()[:12]
    except Exception:
        pass

    # Resolve and hash attached snapshots
    snapshot_entries = []
    resolved_snapshot_paths = []
    if attach_snapshots:
        from app.services.snapshot_service import _snapshot_base_path
        for snap_url in attach_snapshots:
            # snap_url format: /cameras/{cam_id}/snapshots/files/{date}/{filename}
            local_path = None
            if snap_url.startswith("/cameras/"):
                parts = snap_url.lstrip("/").split("/")
                # parts: ["cameras", cam_id, "snapshots", "files", date, filename]
                if len(parts) == 6 and parts[2] == "snapshots" and parts[3] == "files":
                    cam_id, date_str, filename = parts[1], parts[4], parts[5]
                    base = _snapshot_base_path()
                    local_path = base / cam_id / date_str / filename
            if local_path and local_path.exists():
                import hashlib
                sha = hashlib.sha256(local_path.read_bytes()).hexdigest()
                snapshot_entries.append({
                    "kind": "snapshot",
                    "filename": local_path.name,
                    "original_url": snap_url,
                    "sha256": sha,
                    "size_bytes": local_path.stat().st_size,
                    "added_at": datetime.now(timezone.utc).isoformat(),
                })
                resolved_snapshot_paths.append(local_path)
            else:
                logger.warning(f"build_evidence_zip: snapshot not found locally: {snap_url}")
    custody["attached_snapshots"] = snapshot_entries

    custody_json = json.dumps(custody, indent=2, default=str).encode()
    signature = _sign(key, custody_json)

    os.makedirs(output_dir, exist_ok=True)
    out_zip = os.path.join(output_dir, f"evidence_{rec_id}.zip")
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(src_path, arcname=os.path.basename(src_path))
        zf.writestr("chain_of_custody.json", custody_json)
        zf.writestr("chain_of_custody.txt", _custody_to_text(custody))
        zf.writestr("signature.sig", signature)
        zf.writestr("public_key.pem", public_key_pem())
        for snap_path in resolved_snapshot_paths:
            zf.write(str(snap_path), arcname=f"snapshots/{snap_path.name}")
    return out_zip


def _nvr_version() -> str:
    try:
        from app import __version__
        return __version__
    except Exception:
        return "unknown"


def _custody_to_text(c: dict) -> str:
    r = c["recording"]
    op = c["operator"]
    return (
        "GVD NVR — Evidence Chain of Custody\n"
        f"Generated: {c['generated_at']}\n\n"
        f"Recording ID:    {r['id']}\n"
        f"Camera:          {r.get('camera_name')} ({r.get('camera_id')})\n"
        f"File:            {r['filename']}\n"
        f"Time range:      {r['start_time']} → {r['end_time']}\n"
        f"Duration:        {r.get('duration_seconds')} s\n"
        f"Size:            {r['file_size_bytes']} bytes\n"
        f"SHA-256:         {r['sha256']}\n"
        f"Match at export: {r['checksum_match']}\n\n"
        f"Operator:        {op.get('username')} ({op.get('role')})\n"
        f"NVR version:     {c['system']['nvr_version']}\n"
        f"Host hint:       {c['system']['host_machine_fingerprint_hint']}\n"
    )
