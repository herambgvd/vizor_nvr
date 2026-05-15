# =============================================================================
# Hardware fingerprint — stable across reboots, changes if hardware swapped.
#
# Combines:
#   - First non-loopback MAC address (sorted)
#   - /etc/machine-id (Linux installer-generated UUID)
#   - Root filesystem UUID
#
# Result is SHA-256 hex (64 chars). Persisted to data/.machine_id on first
# run so subsequent boots return the same value even if hardware enumeration
# order shifts.
# =============================================================================

import hashlib
import os
import subprocess
from pathlib import Path

MACHINE_ID_FILE = Path(
    os.getenv("MACHINE_ID_FILE")
    or os.path.join(os.getenv("DATA_PATH", "/app/data"), ".machine_id")
)


def _first_mac() -> str:
    try:
        import psutil  # type: ignore

        addrs = psutil.net_if_addrs()
        macs = []
        for iface, info in addrs.items():
            if iface.startswith(("lo", "docker", "veth", "br-")):
                continue
            for a in info:
                if a.family.name == "AF_PACKET" and a.address and a.address != "00:00:00:00:00:00":
                    macs.append(a.address.lower())
        macs.sort()
        return macs[0] if macs else ""
    except Exception:
        return ""


def _linux_machine_id() -> str:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            return Path(path).read_text().strip()
        except Exception:
            continue
    return ""


def _root_fs_uuid() -> str:
    try:
        out = subprocess.check_output(
            ["findmnt", "-no", "UUID", "/"], stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip()
        return out
    except Exception:
        return ""


def compute_fingerprint() -> str:
    parts = [_first_mac(), _linux_machine_id(), _root_fs_uuid()]
    raw = "|".join(p for p in parts if p)
    if not raw:
        # Last-resort fallback — make sure we still emit *something*
        raw = os.uname().nodename + str(os.getuid())
    return hashlib.sha256(raw.encode()).hexdigest()


def get_or_create_fingerprint() -> str:
    """Returns the persisted machine fingerprint, computing + caching on
    first call. Survives container restarts because data/ is a volume."""
    try:
        if MACHINE_ID_FILE.exists():
            cached = MACHINE_ID_FILE.read_text().strip()
            if len(cached) == 64:
                return cached
    except Exception:
        pass

    fp = compute_fingerprint()
    try:
        MACHINE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        MACHINE_ID_FILE.write_text(fp)
    except Exception:
        pass
    return fp
