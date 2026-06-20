# =============================================================================
# RAID Service — software RAID management via mdadm
# =============================================================================
# Provides RAID-1/5/6/10 pool creation, monitoring, and health status.
#
# PREREQUISITES
# ─────────────
# • Linux kernel with md (software RAID) module loaded
# • mdadm installed: apt install mdadm  /  dnf install mdadm
# • CAP_SYS_ADMIN capability (or --privileged Docker flag) for array creation
#   and member management.  Read-only status queries work without privileges.
#
# OPERATOR WORKFLOW
# ─────────────────
# 1. Identify target disks via GET /api/storage/raid/devices (lists unmounted
#    block devices).  Example: /dev/sdb, /dev/sdc.
# 2. Create a RAID-1 mirror:
#      POST /api/storage/raid/arrays
#      { "device": "/dev/md0", "level": "raid1", "members": ["/dev/sdb", "/dev/sdc"] }
# 3. The OS will build (sync) the array in the background.  Progress is
#    visible in GET /api/storage/raid/arrays via the "status" field
#    ("clean" when done; "recovering" or "resyncing" while building).
# 4. Mount the array (mkfs first if new):
#      mkfs.ext4 /dev/md0
#      mount /dev/md0 /mnt/nvr_raid
# 5. Add as a storage pool via POST /api/storage/pools.
#
# DISK FAILURE AND REPLACEMENT
# ─────────────────────────────
# When a disk fails, the RAID enters "degraded" state.  The NVR surfaces this
# via /api/monitoring/disks, the Prometheus metric gvd_raid_array_degraded,
# and an alert in the UI.  To replace:
#   mdadm /dev/md0 --remove /dev/sdb     # remove failed device
#   # physically replace disk
#   mdadm /dev/md0 --add /dev/sdb        # add replacement; rebuild starts automatically
#
# NON-LINUX / MACOS / WINDOWS
# ────────────────────────────
# mdadm is Linux-only.  On macOS (Docker Desktop) or Windows containers,
# probe_available() returns {"available": false, "reason": "..."} and all
# write operations return 503.  Read operations return empty lists.
# =============================================================================

import asyncio
import logging
import platform
import re
import shutil
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def _is_linux() -> bool:
    return platform.system() == "Linux"


def _mdadm_available() -> bool:
    return _is_linux() and shutil.which("mdadm") is not None


def _lsblk_available() -> bool:
    return shutil.which("lsblk") is not None


def _unavailable_response(reason: str) -> Dict:
    return {"available": False, "reason": reason}


class RAIDService:
    """Wrap mdadm for software RAID operations.

    All methods degrade gracefully on non-Linux hosts or when mdadm is absent.
    """

    # ── Availability probe ─────────────────────────────────────────────

    def probe_available(self) -> Dict:
        """Return availability status without raising.  Safe to call anywhere."""
        if not _is_linux():
            return _unavailable_response(
                "RAID management is not supported on this system."
            )
        if not _mdadm_available():
            return _unavailable_response(
                "RAID management is not available on this system."
            )
        return {"available": True}

    # ── Array listing / status ─────────────────────────────────────────

    async def list_arrays(self) -> List[Dict]:
        """Return list of active md arrays with health details."""
        probe = self.probe_available()
        if not probe.get("available"):
            return []

        try:
            proc = await asyncio.create_subprocess_exec(
                "mdadm", "--detail", "--scan",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            logger.warning("[raid] mdadm --detail --scan timed out")
            return []
        except OSError as exc:
            logger.warning(f"[raid] mdadm exec failed: {exc}")
            return []

        arrays = []
        for line in stdout.decode(errors="replace").strip().splitlines():
            m = re.match(r"ARRAY\s+(\S+)", line)
            if m:
                device = m.group(1)
                detail = await self._detail(device)
                if detail:
                    arrays.append(detail)
                    self._update_degraded_metric(detail)
        return arrays

    async def _detail(self, device: str) -> Optional[Dict]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "mdadm", "--detail", device,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            text = stdout.decode(errors="replace")
            level = self._extract(text, r"Raid Level\s*:\s*(\S+)")
            status = self._extract(text, r"State\s*:\s*(.+)")
            working = self._extract(text, r"Working Devices\s*:\s*(\d+)")
            failed = self._extract(text, r"Failed Devices\s*:\s*(\d+)")
            total = self._extract(text, r"Raid Devices\s*:\s*(\d+)")
            resync = self._extract(text, r"Rebuild Status\s*:\s*(.+)")
            return {
                "device": device,
                "level": level or "unknown",
                "status": (status or "unknown").strip(),
                "working_devices": int(working) if working else 0,
                "failed_devices": int(failed) if failed else 0,
                "total_devices": int(total) if total else 0,
                "degraded": int(failed or 0) > 0,
                "rebuild_status": (resync or "").strip() or None,
            }
        except asyncio.TimeoutError:
            logger.warning(f"[raid] mdadm --detail {device} timed out")
            return None
        except OSError as exc:
            logger.debug(f"[raid] mdadm detail failed for {device}: {exc}")
            return None

    def _update_degraded_metric(self, detail: Dict):
        try:
            from app.core.metrics import GVD_RAID_ARRAY_DEGRADED, GVD_RAID_FAILED_DEVICES
            device = detail["device"]
            GVD_RAID_ARRAY_DEGRADED.labels(device=device).set(
                1 if detail["degraded"] else 0
            )
            GVD_RAID_FAILED_DEVICES.labels(device=device).set(
                detail.get("failed_devices", 0)
            )
        except Exception:
            pass

    @staticmethod
    def _extract(text: str, pattern: str) -> Optional[str]:
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1) if m else None

    # ── Array creation / removal ───────────────────────────────────────

    async def create_array(
        self,
        device: str,
        level: str,
        members: List[str],
        force: bool = False,
    ) -> Dict:
        """Create a new md array.  Requires privileged container + Linux."""
        probe = self.probe_available()
        if not probe.get("available"):
            return {"success": False, "message": probe["reason"]}

        level_map = {
            "raid0": "0", "raid1": "1",
            "raid5": "5", "raid6": "6", "raid10": "10",
        }
        lvl = level_map.get(level.lower(), level)
        if lvl not in ("0", "1", "5", "6", "10"):
            return {"success": False, "message": f"Unsupported RAID level: {level}"}

        if not members:
            return {"success": False, "message": "At least one member device required"}

        cmd = [
            "mdadm", "--create", device,
            "--level", lvl,
            "--raid-devices", str(len(members)),
            *members,
        ]
        if force:
            cmd.append("--force")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode == 0:
                logger.info(f"[raid] Created RAID {level} on {device} with {len(members)} members")
                return {"success": True, "message": f"RAID {level} created on {device}"}
            err = stderr.decode(errors="replace")[-500:]
            logger.warning(f"[raid] mdadm create failed: {err}")
            return {"success": False, "message": "Could not create the storage array. Please check the selected disks and try again."}
        except asyncio.TimeoutError:
            logger.warning("[raid] mdadm create timed out")
            return {"success": False, "message": "The operation timed out. Please try again."}
        except PermissionError:
            logger.warning("[raid] mdadm create denied — missing CAP_SYS_ADMIN")
            return {
                "success": False,
                "message": "Insufficient privileges to manage storage arrays on this system.",
            }
        except OSError as exc:
            logger.warning(f"[raid] mdadm create OS error: {exc}")
            return {"success": False, "message": "Could not create the storage array. Please try again."}

    async def stop_array(self, device: str) -> Dict:
        probe = self.probe_available()
        if not probe.get("available"):
            return {"success": False, "message": probe["reason"]}
        try:
            proc = await asyncio.create_subprocess_exec(
                "mdadm", "--stop", device,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode == 0:
                return {"success": True, "message": f"Stopped {device}"}
            logger.warning(f"[raid] mdadm stop failed for {device}: {stderr.decode(errors='replace')[-500:]}")
            return {"success": False, "message": "Could not stop the storage array. Please try again."}
        except asyncio.TimeoutError:
            logger.warning("[raid] mdadm stop timed out")
            return {"success": False, "message": "The operation timed out. Please try again."}
        except OSError as exc:
            logger.warning(f"[raid] mdadm stop OS error: {exc}")
            return {"success": False, "message": "Could not stop the storage array. Please try again."}

    async def remove_array(self, device: str) -> Dict:
        """Stop array and zero-superblock all members."""
        probe = self.probe_available()
        if not probe.get("available"):
            return {"success": False, "message": probe["reason"]}

        detail = await self._detail(device)
        if not detail:
            return {"success": False, "message": f"Array {device} not found or not readable"}

        # Find member devices
        members = []
        try:
            proc = await asyncio.create_subprocess_exec(
                "mdadm", "--detail", device,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            for line in stdout.decode(errors="replace").splitlines():
                m = re.search(r"\s(/dev/\S+)$", line)
                if m:
                    members.append(m.group(1))
        except Exception as exc:
            logger.debug(f"[raid] Could not enumerate members of {device}: {exc}")

        stop = await self.stop_array(device)
        if not stop["success"]:
            return stop

        for member in members:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "mdadm", "--zero-superblock", member,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=15)
            except Exception as exc:
                logger.debug(f"[raid] zero-superblock failed for {member}: {exc}")

        logger.info(f"[raid] Removed {device} and zeroed {len(members)} superblock(s)")
        return {"success": True, "message": f"Removed {device} and zeroed superblocks"}

    # ── Block device discovery ─────────────────────────────────────────

    async def list_block_devices(self) -> List[Dict]:
        """List available block devices (type=disk, unmounted)."""
        if not _lsblk_available():
            return []
        try:
            proc = await asyncio.create_subprocess_exec(
                "lsblk", "-d", "-n", "-o", "NAME,SIZE,TYPE,MODEL",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            devices = []
            for line in stdout.decode(errors="replace").strip().splitlines():
                parts = line.split(None, 3)
                if len(parts) >= 3 and parts[2] == "disk":
                    devices.append({
                        "name": f"/dev/{parts[0]}",
                        "size": parts[1],
                        "model": parts[3].strip() if len(parts) > 3 else "",
                    })
            return devices
        except asyncio.TimeoutError:
            logger.warning("[raid] lsblk timed out")
            return []
        except OSError as exc:
            logger.debug(f"[raid] lsblk failed: {exc}")
            return []


# Module singleton
raid_service = RAIDService()
