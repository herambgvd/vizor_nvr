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
#       --feature-options '{"frs":["attendance","investigation"]}' \
#       --hardware-fingerprint "<value from /api/license/fingerprint>" \
#       --out acme-2026.lic
#
# Interactive client workflow:
#
#   python scripts/sign_license.py wizard
#
# This creates/reuses:
#   vendor-keys/<client-slug>/private.pem
#   vendor-keys/<client-slug>/public.b64
#   vendor-keys/<client-slug>/licenses/<license-id>.lic
#
# NOTE: every deployed NVR verifies licenses with the public key compiled into
# backend/app/license/keys.py. If you generate a different keypair per client,
# that client's NVR build/config must contain the matching public.b64.
# =============================================================================

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
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


DEFAULT_CLIENTS_ROOT = Path("vendor-keys")
FEATURE_CHOICES = [
    "recording",
    "playback",
    "ppe",
    "anpr",
    "frs",
    "people_counting",
    "suspect_search",
]
SCENARIO_CHOICES = ["ppe", "anpr", "frs", "people_counting", "suspect_search"]
FEATURE_OPTION_CHOICES = {
    "frs": ["attendance", "investigation"],
}
TIER_CHOICES = ["free", "pro", "business", "enterprise"]
MAX_CHANNELS = 64


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "client"


def _save_keypair(out_dir: Path, *, force: bool = False) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    private_path = out_dir / "private.pem"
    public_der_path = out_dir / "public.der"
    public_b64_path = out_dir / "public.b64"
    if not force and any(p.exists() for p in (private_path, public_der_path, public_b64_path)):
        raise SystemExit(
            f"Key files already exist in {out_dir}. Use a new folder or --force to overwrite."
        )

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

    private_path.write_bytes(priv_pem)
    public_der_path.write_bytes(pub_der)
    public_b64_path.write_text(base64.b64encode(pub_der).decode() + "\n")

    print(f"Wrote keypair to {out_dir}/")
    print(f"  - private.pem  (KEEP OFF DEPLOY HOSTS)")
    print(f"  - public.der   (binary public key)")
    print(f"  - public.b64   (base64 — paste into backend/app/license/keys.py)")


def _csv(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _build_payload(args: argparse.Namespace) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    # Blank --expires => perpetual license (expires_at left empty; the
    # platform treats an empty expires_at as never-expiring).
    if args.expires:
        expires_at = dt.datetime.fromisoformat(args.expires + "T23:59:59+00:00").isoformat()
    else:
        expires_at = ""

    # Channel cap is currently limited to 64 maximum. Clamp loudly so a
    # typo can never mint a license that the platform would refuse.
    cam_limit = args.camera_limit
    if cam_limit > MAX_CHANNELS:
        print(f"WARNING: --camera-limit {cam_limit} exceeds max {MAX_CHANNELS}; clamping.", file=sys.stderr)
        cam_limit = MAX_CHANNELS
    if cam_limit < 1:
        raise SystemExit("--camera-limit must be at least 1")

    feature_options = getattr(args, "feature_options", {}) or {}
    if isinstance(feature_options, str):
        feature_options = json.loads(feature_options) if feature_options.strip() else {}

    return {
        "customer": args.customer,
        "license_id": args.license_id,
        "issued_at": now.isoformat(),
        "expires_at": expires_at,
        "hardware_fingerprint": args.hardware_fingerprint or None,
        "camera_limit": cam_limit,
        "ai_camera_limit": args.ai_camera_limit,
        "scenarios": _csv(args.scenarios),
        "features": _csv(args.features),
        "feature_options": feature_options,
        "tier": args.tier,
    }


def _write_signed_license(private_key: Path, payload: dict, out_path: Path) -> None:
    priv_path = Path(private_key)
    priv = serialization.load_pem_private_key(
        priv_path.read_bytes(), password=None,
    )
    if not isinstance(priv, Ed25519PrivateKey):
        raise SystemExit("private key is not Ed25519")

    # Canonical serialization — sort keys + UTF-8 + no whitespace tricks.
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = priv.sign(payload_bytes)

    blob = base64.b64encode(signature + payload_bytes).decode()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(blob)

    # Sidecar helps vendor ops audit exactly what was issued without decoding
    # the signed blob. It is not uploaded to the customer system.
    out_path.with_suffix(".payload.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    print(f"Signed license written: {out_path}")
    print(f"  customer:       {payload['customer']}")
    print(f"  license_id:     {payload['license_id']}")
    print(f"  expires:        {payload['expires_at'] or '(perpetual)'}")
    print(f"  tier:           {payload['tier']}")
    print(f"  cameras:        {payload['camera_limit']}  ai: {payload['ai_camera_limit']}")
    print(f"  features:       {payload['features']}")
    print(f"  options:        {payload.get('feature_options') or {}}")
    print(f"  scenarios:      {payload['scenarios']}")
    print(f"  fingerprint:    {payload['hardware_fingerprint'] or '(unbound)'}")


def _sign(args: argparse.Namespace) -> None:
    payload = _build_payload(args)
    _write_signed_license(Path(args.private_key), payload, Path(args.out))


def _prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    return value or default


def _prompt_int(text: str, default: int, *, min_value: int = 0, max_value: int | None = None) -> int:
    while True:
        raw = _prompt(text, str(default))
        try:
            value = int(raw)
        except ValueError:
            print("Please enter a number.")
            continue
        if value < min_value:
            print(f"Value must be at least {min_value}.")
            continue
        if max_value is not None and value > max_value:
            print(f"Value must be at most {max_value}.")
            continue
        return value


def _prompt_choice(text: str, choices: List[str], default: str) -> str:
    normalized = {c.lower(): c for c in choices}
    while True:
        raw = _prompt(f"{text} ({'/'.join(choices)})", default).lower()
        if raw in normalized:
            return normalized[raw]
        print(f"Choose one of: {', '.join(choices)}")


def _prompt_multi(text: str, choices: List[str], defaults: List[str]) -> List[str]:
    print(f"\n{text}")
    for i, choice in enumerate(choices, start=1):
        mark = "default" if choice in defaults else ""
        print(f"  {i}. {choice} {mark}".rstrip())
    raw = _prompt("Enter numbers or comma-separated names; blank keeps default", ",".join(defaults))
    selected: List[str] = []
    for token in _csv(raw):
        if token.isdigit():
            idx = int(token)
            if 1 <= idx <= len(choices):
                selected.append(choices[idx - 1])
                continue
        normalized = token.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in choices:
            selected.append(normalized)
        else:
            print(f"Skipping unknown value: {token}")
    return list(dict.fromkeys(selected))


def _next_license_id(client_slug: str, root: Path) -> str:
    today = dt.datetime.now().strftime("%Y%m%d")
    licenses_dir = root / client_slug / "licenses"
    existing = sorted(licenses_dir.glob(f"{client_slug.upper()}-{today}-*.lic"))
    return f"{client_slug.upper()}-{today}-{len(existing) + 1:03d}"


def _wizard(args: argparse.Namespace) -> None:
    root = Path(args.root)
    print("\nVizor NVR License Wizard")
    print("------------------------")
    print(f"Client root: {root}")

    customer = _prompt("Client/customer display name", "GVD")
    client_slug = _prompt("Client folder slug", _slugify(customer))
    client_dir = root / client_slug
    keys_dir = client_dir
    private_key = keys_dir / "private.pem"

    if private_key.exists():
        print(f"Using existing client key: {private_key}")
    else:
        create = _prompt("No key found. Generate a new keypair for this client? (yes/no)", "yes").lower()
        if create not in {"y", "yes"}:
            private_key = Path(_prompt("Path to existing private.pem"))
            if not private_key.exists():
                raise SystemExit(f"Private key not found: {private_key}")
        else:
            _save_keypair(keys_dir)

    public_b64 = keys_dir / "public.b64"
    if public_b64.exists():
        print(f"Public key for this client: {public_b64}")
        print("Reminder: the deployed NVR must use this matching public key.")

    license_id = _prompt("License ID", _next_license_id(client_slug, root))
    expires = _prompt("Expiry date YYYY-MM-DD; blank = perpetual", "2027-12-31")
    tier = _prompt_choice("Tier", TIER_CHOICES, "business")
    camera_limit = _prompt_int("Camera limit", 8, min_value=1, max_value=MAX_CHANNELS)
    ai_camera_limit = _prompt_int("AI camera limit", min(camera_limit, 8), min_value=0, max_value=MAX_CHANNELS)
    hardware_fingerprint = _prompt("Machine fingerprint; blank = unbound", "")
    features = _prompt_multi(
        "Licensed product features",
        FEATURE_CHOICES,
        ["recording", "playback"],
    )
    scenarios = _prompt_multi(
        "Licensed AI scenarios",
        SCENARIO_CHOICES,
        [s for s in ["ppe", "anpr", "frs"] if s in features],
    )
    feature_options = {}
    if "frs" in features or "frs" in scenarios:
        feature_options["frs"] = _prompt_multi(
            "FRS sub-features",
            FEATURE_OPTION_CHOICES["frs"],
            FEATURE_OPTION_CHOICES["frs"],
        )

    payload_args = argparse.Namespace(
        customer=customer,
        license_id=license_id,
        expires=expires,
        tier=tier,
        camera_limit=camera_limit,
        ai_camera_limit=ai_camera_limit,
        scenarios=",".join(scenarios),
        features=",".join(features),
        feature_options=feature_options,
        hardware_fingerprint=hardware_fingerprint or None,
    )
    payload = _build_payload(payload_args)
    out = client_dir / "licenses" / f"{license_id}.lic"

    print("\nLicense summary")
    print(json.dumps(payload, indent=2, sort_keys=True))
    confirm = _prompt("Generate this license? (yes/no)", "yes").lower()
    if confirm not in {"y", "yes"}:
        raise SystemExit("Cancelled.")

    _write_signed_license(private_key, payload, out)
    print("\nUpload this file in Vizor NVR: Settings → License → Upload License")


def main() -> int:
    ap = argparse.ArgumentParser(prog="sign_license")
    sub = ap.add_subparsers(dest="cmd")

    kg = sub.add_parser("keygen", help="generate vendor keypair")
    kg.add_argument("--out", required=True)
    kg.add_argument("--force", action="store_true",
                    help="overwrite existing private/public key files")

    sg = sub.add_parser("sign", help="sign a license payload")
    sg.add_argument("--private-key", required=True)
    sg.add_argument("--customer", required=True)
    sg.add_argument("--license-id", required=True)
    sg.add_argument("--expires", default="",
                    help="YYYY-MM-DD; omit for a perpetual license")
    sg.add_argument("--tier", default="business",
                    choices=["free", "pro", "business", "enterprise"])
    sg.add_argument("--camera-limit", type=int, required=True,
                    help="max camera channels (1-64)")
    sg.add_argument("--ai-camera-limit", type=int, default=0)
    sg.add_argument("--scenarios", default="")
    sg.add_argument("--features", default="")
    sg.add_argument("--feature-options", default="",
                    help='JSON map for scenario sub-features, e.g. {"frs":["attendance","investigation"]}')
    sg.add_argument("--hardware-fingerprint", default=None)
    sg.add_argument("--out", required=True)

    wz = sub.add_parser("wizard", help="interactive client license workflow")
    wz.add_argument("--root", default=str(DEFAULT_CLIENTS_ROOT),
                    help="root folder for client key/license workspaces")

    args = ap.parse_args()
    if args.cmd is None:
        args = argparse.Namespace(cmd="wizard", root=str(DEFAULT_CLIENTS_ROOT))

    if args.cmd == "keygen":
        _save_keypair(Path(args.out), force=args.force)
    elif args.cmd == "sign":
        _sign(args)
    elif args.cmd == "wizard":
        _wizard(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
