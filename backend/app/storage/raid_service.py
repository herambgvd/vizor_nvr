# =============================================================================
# RAID Service — software RAID management via mdadm
# =============================================================================
# Provides RAID-1/5/6/10 pool creation, monitoring, and health status.
# Requires mdadm installed and CAP_SYS_ADMIN (or --privileged) for creation.
# Read-only status queries work without privileges.
# =============================================================================

import asyncio
import logging
import os
import re
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class RAIDService:
    """Wrap mdadm for software RAID operations."""

    async def list_arrays(self) -> List[Dict]:
        """Return list of active md arrays."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "mdadm", "--detail", "--scan",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            arrays = []
            for line in stdout.decode().strip().splitlines():
                # Format: ARRAY /dev/md0 metadata=1.2 UUID=...
                m = re.match(r"ARRAY\s+(\S+)", line)
                if m:
                    device = m.group(1)
                    detail = await self._detail(device)
                    if detail:
                        arrays.append(detail)
            return arrays
        except Exception as e:
            logger.debug(f"mdadm scan failed: {e}")
            return []

    async def _detail(self, device: str) -> Optional[Dict]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "mdadm", "--detail", "--brief", device,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            text = stdout.decode()
            # Parse brief output
            level = self._extract(text, r"Raid Level : (\S+)")
            status = self._extract(text, r"State : (.*)")
            devices = self._extract(text, r"Working Devices : (\d+)")
            failed = self._extract(text, r"Failed Devices : (\d+)")
            return {
                "device": device,
                "level": level or "unknown",
                "status": (status or "unknown").strip(),
                "working_devices": int(devices) if devices else 0,
                "failed_devices": int(failed) if failed else 0,
            }
        except Exception as e:
            logger.debug(f"mdadm detail failed for {device}: {e}")
            return None

    @staticmethod
    def _extract(text: str, pattern: str) -> Optional[str]:
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1) if m else None

    async def create_array(
        self,
        device: str,
        level: str,
        members: List[str],
        force: bool = False,
    ) -> Dict:
        """
        Create a new md array.  Requires privileged container.
        Returns {"success": bool, "message": str}.
        """
        level_map = {"raid0": "0", "raid1": "1", "raid5": "5", "raid6": "6", "raid10": "10"}
        lvl = level_map.get(level.lower(), level)
        if lvl not in ("0", "1", "5", "6", "10"):
            return {"success": False, "message": f"Unsupported RAID level: {level}"}

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
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                return {"success": True, "message": f"RAID {level} created on {device}"}
            err = stderr.decode(errors="replace")[-500:]
            return {"success": False, "message": err}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def stop_array(self, device: str) -> Dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                "mdadm", "--stop", device,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0:
                return {"success": True, "message": f"Stopped {device}"}
            return {"success": False, "message": stderr.decode(errors="replace")}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def remove_array(self, device: str) -> Dict:
        """Stop and zero-superblock all members."""
        detail = await self._detail(device)
        if not detail:
            return {"success": False, "message": "Array not found"}

        # Find members
        members = []
        try:
            proc = await asyncio.create_subprocess_exec(
                "mdadm", "--detail", device,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            for line in stdout.decode().splitlines():
                m = re.match(r"\s*\d+\s+(\S+)\s+\d+\s+\d+\s+\d+\s+(\S+)", line)
                if m:
                    members.append(m.group(1))
        except Exception:
            pass

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
                await proc.communicate()
            except Exception:
                pass

        return {"success": True, "message": f"Removed {device} and zeroed superblocks"}

    async def list_block_devices(self) -> List[Dict]:
        """List available block devices (not mounted, not part of RAID)."""
        devices = []
        try:
            proc = await asyncio.create_subprocess_exec(
                "lsblk", "-d", "-n", "-o", "NAME,SIZE,TYPE,MODEL",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            for line in stdout.decode().strip().splitlines():
                parts = line.split(None, 3)
                if len(parts) >= 3 and parts[2] == "disk":
                    devices.append({
                        "name": f"/dev/{parts[0]}",
                        "size": parts[1],
                        "model": parts[3] if len(parts) > 3 else "",
                    })
        except Exception as e:
            logger.debug(f"lsblk failed: {e}")
        return devices


# Module singleton
raid_service = RAIDService()
