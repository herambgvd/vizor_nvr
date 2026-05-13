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
    """Collect local IP addresses suitable for WebRTC candidates."""
    candidates = ["127.0.0.1:8555"]
    try:
        # Get the primary outbound IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip != "127.0.0.1":
            candidates.insert(0, f"{primary_ip}:8555")
    except Exception:
        pass

    # Add all non-loopback interface addresses
    try:
        import psutil
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if ip != "127.0.0.1" and ip not in [c.replace(":8555", "") for c in candidates]:
                        candidates.append(f"{ip}:8555")
    except ImportError:
        pass

    return candidates


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
