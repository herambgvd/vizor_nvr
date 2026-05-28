#!/usr/bin/env python3
"""
Generate go2rtc.yaml from go2rtc.yaml.template using environment variables.

Usage:
    python scripts/generate-go2rtc-config.py

Environment variables:
    GO2RTC_API_ORIGIN    — CORS origin for go2rtc API (default: http://localhost)
    GO2RTC_CANDIDATES    — comma-separated list of host:port candidates
                           (default: auto-detected from network interfaces)
    NVR_PUBLIC_HOST      — public hostname/IP of the NVR (used for candidates)

The script writes to go2rtc.yaml in the project root.
"""

import os
import sys
import socket
from pathlib import Path


def get_default_candidates() -> list[str]:
    """Return minimal localhost candidate list.

    We no longer auto-detect interface IPs because:
    1. On cloud/VPN hosts this leaks private VPC IPs and internal topology.
    2. On multi-homed servers it produces invalid candidates that break WebRTC.
    3. The operator-provided NVR_PUBLIC_HOST (set via install.sh) is the
       authoritative public candidate and is injected separately.
    """
    return ["127.0.0.1:8555"]


def generate_config() -> str:
    origin = os.getenv("GO2RTC_API_ORIGIN", "http://localhost")
    nvr_host = os.getenv("NVR_PUBLIC_HOST", "").strip()
    candidates_env = os.getenv("GO2RTC_CANDIDATES", "").strip()

    if candidates_env:
        candidates = [c.strip() for c in candidates_env.split(",") if c.strip()]
    else:
        candidates = get_default_candidates()
        if nvr_host:
            host_entry = f"{nvr_host}:8555"
            if host_entry not in candidates:
                candidates.insert(0, host_entry)

    candidates_yaml = "\n".join(f"    - {c}" for c in candidates)

    template_path = Path(__file__).parent.parent / "go2rtc.yaml.template"
    output_path = Path(__file__).parent.parent / "go2rtc.yaml"

    if not template_path.exists():
        print(f"[ERROR] Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    template = template_path.read_text()
    config = template.replace("${GO2RTC_API_ORIGIN}", origin)
    config = config.replace("${GO2RTC_CANDIDATES}", candidates_yaml)

    output_path.write_text(config)
    print(f"[OK] Generated {output_path}")
    print(f"     Origin: {origin}")
    print(f"     Candidates: {', '.join(candidates)}")


if __name__ == "__main__":
    generate_config()
