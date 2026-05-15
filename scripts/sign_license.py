#!/usr/bin/env python3
# =============================================================================
# Vendor-side license signer.
#
# Generates an Ed25519 keypair (once), then signs license payloads.
# Output is a base64 string that the customer uploads via Settings → License.
#
# Usage:
#
#   # 1. One-time keypair generation. Public key goes in backend/keys.py;
#   #    private key stays OFF every deploy host.
#   python scripts/sign_license.py keygen --out ./vendor-keys
#
#   # 2. Sign a license — every flag maps to a payload field.
#   python scripts/sign_license.py sign \
#       --private-key ./vendor-keys/private.pem \
#       --customer "Acme Industries" \
#       --license-id "ACME-2026-001" \
#       --expires "2027-05-15" \
#       --tier business \
#       --camera-limit 32 --ai-camera-limit 8 \
#       --scenarios frs,people_counting,ppe \
#       --features recording,playback,attendance,investigation \
#       --hardware-fingerprint "<value from /api/license/fingerprint>" \
#       --out acme-2026.lic
# =============================================================================

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import List

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization
except ImportError:  # pragma: no cover
    print("ERROR: install `cryptography` (pip install cryptography)", file=sys.stderr)
    sys.exit(2)


def _save_keypair(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_der = pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    (out_dir / "private.pem").write_bytes(priv_pem)
    (out_dir / "public.der").write_bytes(pub_der)
    (out_dir / "public.b64").write_text(base64.b64encode(pub_der).decode() + "\n")

    print(f"Wrote keypair to {out_dir}/")
    print(f"  - private.pem  (KEEP OFF DEPLOY HOSTS)")
    print(f"  - public.der   (binary public key)")
    print(f"  - public.b64   (base64 — paste into backend/app/license/keys.py)")


def _csv(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _sign(args: argparse.Namespace) -> None:
    priv_path = Path(args.private_key)
    priv = serialization.load_pem_private_key(
        priv_path.read_bytes(), password=None,
    )
    if not isinstance(priv, Ed25519PrivateKey):
        raise SystemExit("private key is not Ed25519")

    now = dt.datetime.now(dt.timezone.utc)
    expires = dt.datetime.fromisoformat(args.expires + "T23:59:59+00:00")

    payload = {
        "customer": args.customer,
        "license_id": args.license_id,
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "hardware_fingerprint": args.hardware_fingerprint or None,
        "camera_limit": args.camera_limit,
        "ai_camera_limit": args.ai_camera_limit,
        "scenarios": _csv(args.scenarios),
        "features": _csv(args.features),
        "tier": args.tier,
    }

    # Canonical serialization — sort keys + UTF-8 + no whitespace tricks.
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = priv.sign(payload_bytes)

    blob = base64.b64encode(signature + payload_bytes).decode()
    out_path = Path(args.out)
    out_path.write_text(blob)
    print(f"Signed license written: {out_path}")
    print(f"  customer:       {payload['customer']}")
    print(f"  license_id:     {payload['license_id']}")
    print(f"  expires:        {payload['expires_at']}")
    print(f"  tier:           {payload['tier']}")
    print(f"  cameras:        {payload['camera_limit']}  ai: {payload['ai_camera_limit']}")
    print(f"  scenarios:      {payload['scenarios']}")
    print(f"  fingerprint:    {payload['hardware_fingerprint'] or '(unbound)'}")


def main() -> int:
    ap = argparse.ArgumentParser(prog="sign_license")
    sub = ap.add_subparsers(dest="cmd", required=True)

    kg = sub.add_parser("keygen", help="generate vendor keypair")
    kg.add_argument("--out", required=True)

    sg = sub.add_parser("sign", help="sign a license payload")
    sg.add_argument("--private-key", required=True)
    sg.add_argument("--customer", required=True)
    sg.add_argument("--license-id", required=True)
    sg.add_argument("--expires", required=True, help="YYYY-MM-DD")
    sg.add_argument("--tier", default="business",
                    choices=["free", "pro", "business", "enterprise"])
    sg.add_argument("--camera-limit", type=int, required=True)
    sg.add_argument("--ai-camera-limit", type=int, required=True)
    sg.add_argument("--scenarios", default="")
    sg.add_argument("--features", default="")
    sg.add_argument("--hardware-fingerprint", default=None)
    sg.add_argument("--out", required=True)

    args = ap.parse_args()
    if args.cmd == "keygen":
        _save_keypair(Path(args.out))
    elif args.cmd == "sign":
        _sign(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
