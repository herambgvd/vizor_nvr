# =============================================================================
# NAS Service — NFS/SMB mount management for storage pools
# =============================================================================
# Handles kernel-level mounting of network shares for use as recording
# storage pools.  Requires the backend container to have:
#   - nfs-common  (for NFS mounts)
#   - cifs-utils  (for SMB/CIFS mounts)
#   - CAP_SYS_ADMIN or --privileged  (for mount(2) syscall)
#
# When privileges are insufficient, the service returns clear error messages
# so the operator can either:
#   1. Mount the share on the host and bind-mount into the container, or
#   2. Run the backend container with --privileged
# =============================================================================

import os
import re
import subprocess
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict

from app.core.crypto import encrypt_value, decrypt_value

logger = logging.getLogger(__name__)


class NASService:
    """Manage NAS mount/unmount/health for storage pools."""

    @staticmethod
    def _has_mount_privileges() -> bool:
        """Check if we can call mount(2) inside this container."""
        # Quick test: try to read /proc/self/mountinfo (works unprivileged)
        # Real test is attempting a no-op mount or checking CAP_SYS_ADMIN.
        # We do a lightweight check by looking at /proc/1/status for caps.
        try:
            with open("/proc/1/status", "r") as f:
                for line in f:
                    if line.startswith("CapEff:"):
                        cap_eff = int(line.split(":")[1].strip(), 16)
                        # CAP_SYS_ADMIN = bit 21
                        return (cap_eff >> 21) & 1 == 1
        except Exception:
            pass
        return False

    @staticmethod
    def _run_cmd(cmd: List[str], timeout: int = 15) -> tuple:
        """Run a shell command, return (rc, stdout, stderr)."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "command timed out"
        except FileNotFoundError as e:
            return -1, "", str(e)

    # ------------------------------------------------------------------
    # Connection test (before creating a pool)
    # ------------------------------------------------------------------

    @staticmethod
    def test_nfs_reachable(server: str) -> Dict:
        """Test if an NFS server is reachable via showmount."""
        rc, out, err = NASService._run_cmd(["showmount", "-e", server], timeout=10)
        if rc != 0:
            return {"ok": False, "message": f"NFS server unreachable: {err or out}"}
        exports = [line.split()[0] for line in out.strip().splitlines()[1:] if line.strip()]
        return {"ok": True, "message": "NFS server reachable", "exports": exports}

    @staticmethod
    def test_smb_reachable(server: str, username: str = "", password: str = "", domain: str = "") -> Dict:
        """Test if an SMB server is reachable and list shares."""
        # smbclient -L //server -U user%pass -W domain
        creds = f"{username}%{password}" if username else "guest%"
        cmd = ["smbclient", "-L", f"//{server}", "-U", creds, "-g"]
        if domain:
            cmd.extend(["-W", domain])
        rc, out, err = NASService._run_cmd(cmd, timeout=10)
        if rc != 0:
            return {"ok": False, "message": f"SMB server unreachable: {err or out}"}
        # Parse -g output: share names are lines like "Disk|sharename|comment"
        shares = []
        for line in out.strip().splitlines():
            if line.startswith("Disk|"):
                parts = line.split("|")
                if len(parts) >= 2:
                    shares.append(parts[1])
        return {"ok": True, "message": "SMB server reachable", "shares": shares}

    @staticmethod
    def test_connection(server: str, protocol: str, **kwargs) -> Dict:
        """Generic connection test dispatch."""
        if protocol == "nfs":
            return NASService.test_nfs_reachable(server)
        elif protocol == "smb":
            return NASService.test_smb_reachable(
                server,
                kwargs.get("username", ""),
                kwargs.get("password", ""),
                kwargs.get("domain", ""),
            )
        return {"ok": False, "message": f"Unsupported protocol: {protocol}"}

    # ------------------------------------------------------------------
    # Mount / Unmount
    # ------------------------------------------------------------------

    @staticmethod
    def mount_pool(pool) -> Dict:
        """Attempt to mount a NAS pool. Returns {ok, message}."""
        if pool.pool_type == "local":
            return {"ok": True, "message": "Local pool — no mount needed"}

        if not NASService._has_mount_privileges():
            return {
                "ok": False,
                "message": (
                    "Container lacks CAP_SYS_ADMIN (mount privileges). "
                    "Mount the share on the host and bind-mount the path into the container, "
                    "or run the backend container with --privileged."
                ),
            }

        # Ensure mount point exists
        os.makedirs(pool.path, exist_ok=True)

        # Check if already mounted
        if NASService._is_mounted(pool.path):
            return {"ok": True, "message": "Already mounted"}

        if pool.pool_type == "nfs":
            return NASService._mount_nfs(pool)
        elif pool.pool_type == "smb":
            return NASService._mount_smb(pool)
        return {"ok": False, "message": f"Unknown pool type: {pool.pool_type}"}

    @staticmethod
    def unmount_pool(path: str) -> Dict:
        """Unmount a pool path. Returns {ok, message}."""
        if not NASService._is_mounted(path):
            return {"ok": True, "message": "Not mounted"}
        rc, out, err = NASService._run_cmd(["umount", path], timeout=15)
        if rc != 0:
            # Try lazy unmount
            rc2, out2, err2 = NASService._run_cmd(["umount", "-l", path], timeout=15)
            if rc2 != 0:
                return {"ok": False, "message": f"Unmount failed: {err or err2}"}
        return {"ok": True, "message": "Unmounted"}

    @staticmethod
    def _mount_nfs(pool) -> Dict:
        cmd = [
            "mount",
            "-t", "nfs",
            f"{pool.nas_server}:{pool.nas_share}",
            pool.path,
        ]
        if pool.mount_options:
            cmd.extend(["-o", pool.mount_options])
        else:
            # Safe defaults
            cmd.extend(["-o", "nolock,soft,timeo=30,retrans=2"])

        rc, out, err = NASService._run_cmd(cmd, timeout=30)
        if rc != 0:
            return {"ok": False, "message": f"NFS mount failed: {err or out}"}
        return {"ok": True, "message": "NFS mounted"}

    @staticmethod
    def _mount_smb(pool) -> Dict:
        opts = []
        if pool.mount_options:
            opts.append(pool.mount_options)

        # Build credentials
        cred_parts = []
        if pool.nas_username:
            # Decrypt if encrypted
            username = pool.nas_username
            if username.startswith("enc:"):
                username = decrypt_value(username) or username
            cred_parts.append(f"username={username}")
        else:
            cred_parts.append("guest")

        if pool.nas_password:
            password = pool.nas_password
            if password.startswith("enc:"):
                password = decrypt_value(password) or password
            cred_parts.append(f"password={password}")

        if pool.nas_domain:
            cred_parts.append(f"domain={pool.nas_domain}")

        if cred_parts:
            opts.append(",".join(cred_parts))

        # Safe defaults
        opts.append("uid=1001,gid=1001,file_mode=0644,dir_mode=0755")
        opts.append("vers=3.0")

        cmd = [
            "mount",
            "-t", "cifs",
            f"//{pool.nas_server}/{pool.nas_share}",
            pool.path,
            "-o", ",".join(opts),
        ]

        rc, out, err = NASService._run_cmd(cmd, timeout=30)
        if rc != 0:
            return {"ok": False, "message": f"SMB mount failed: {err or out}"}
        return {"ok": True, "message": "SMB mounted"}

    @staticmethod
    def _is_mounted(path: str) -> bool:
        """Check if a path is currently a mount point."""
        rc, _, _ = NASService._run_cmd(["mountpoint", "-q", path], timeout=5)
        return rc == 0

    # ------------------------------------------------------------------
    # Auto-mount on startup
    # ------------------------------------------------------------------

    @staticmethod
    async def auto_mount_all_pools(db):
        """Mount all active NAS pools with auto_mount=True on startup."""
        from sqlalchemy import select
        from app.storage.models import StoragePool

        result = await db.execute(
            select(StoragePool).where(
                StoragePool.pool_type.in_(["nfs", "smb"]),
                StoragePool.is_active.is_(True),
                StoragePool.nas_auto_mount.is_(True),
            )
        )
        pools = result.scalars().all()
        for pool in pools:
            try:
                res = NASService.mount_pool(pool)
                pool.nas_mount_state = "mounted" if res["ok"] else "error"
                pool.nas_last_mount_error = None if res["ok"] else res["message"]
                # naive UTC — matches the TIMESTAMP WITHOUT TIME ZONE column type
                pool.nas_last_mount_at = datetime.now(timezone.utc).replace(tzinfo=None)
                if res["ok"]:
                    logger.info(f"[NAS] Auto-mounted {pool.name} ({pool.pool_type}) at {pool.path}")
                else:
                    logger.warning(f"[NAS] Auto-mount failed for {pool.name}: {res['message']}")
            except Exception as e:
                pool.nas_mount_state = "error"
                pool.nas_last_mount_error = str(e)
                logger.error(f"[NAS] Auto-mount exception for {pool.name}: {e}")
        await db.commit()

    # ------------------------------------------------------------------
    # Health check (beyond the generic pool writable check)
    # ------------------------------------------------------------------

    @staticmethod
    def check_mount_health(pool) -> Dict:
        """Deep health check for a mounted NAS pool.

        Returns dict with keys: healthy, mounted, writable, latency_ms, message
        """
        import time

        info = {
            "pool_id": pool.id,
            "pool_name": pool.name,
            "healthy": False,
            "mounted": False,
            "writable": False,
            "latency_ms": None,
            "message": None,
        }

        # 1. Check if path is a mountpoint
        if not NASService._is_mounted(pool.path):
            info["message"] = "Not mounted"
            return info
        info["mounted"] = True

        # 2. Write latency test (small sentinel file)
        t0 = time.time()
        try:
            sentinel = os.path.join(pool.path, ".gvd_nvr_nas_health")
            with open(sentinel, "w") as f:
                f.write("ok")
            os.remove(sentinel)
            info["writable"] = True
            info["latency_ms"] = round((time.time() - t0) * 1000, 1)
        except OSError as e:
            info["message"] = f"Write test failed: {e}"
            return info

        # 3. If latency is very high, warn but still mark healthy
        if info["latency_ms"] and info["latency_ms"] > 5000:
            info["message"] = f"High latency ({info['latency_ms']} ms) — possible network congestion"
            info["healthy"] = True
        else:
            info["healthy"] = True
            info["message"] = "OK"

        return info


# Module singleton
nas_service = NASService()
