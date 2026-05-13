# =============================================================================
# Disk Health Service — S.M.A.R.T polling + alerting
# =============================================================================
#
# Background job: every 6 hours, run `smartctl --scan` + `smartctl -A -j` per
# discovered drive. Persist a snapshot row and fire DiskWarning / DiskFail
# events if thresholds are exceeded.
#
# Requires `smartctl` (smartmontools) on the host. On Linux installs this
# usually means running the backend container with --privileged, or mounting
# /dev and using a host-side helper. The service degrades gracefully if
# smartctl is missing: it just logs a warning and skips the poll cycle.
# =============================================================================

import asyncio
import json
import logging
import shutil
import subprocess
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# Thresholds — operator can tune via DB settings later.
TEMP_WARN_C = 50
TEMP_FAIL_C = 65
REALLOC_WARN = 1
REALLOC_FAIL = 50
PENDING_WARN = 1
PENDING_FAIL = 10


class DiskHealthService:
    def __init__(self, interval_seconds: int = 6 * 3600):
        self._interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._running:
            return
        if shutil.which("smartctl") is None:
            logger.warning("smartctl not found in PATH — disk health monitoring disabled")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Disk health service started (interval={self._interval}s)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        # First poll after 60s so startup costs don't double up.
        await asyncio.sleep(60)
        while self._running:
            try:
                await self.poll_once()
            except Exception as e:
                logger.error(f"disk_health poll failed: {e}")
            await asyncio.sleep(self._interval)

    # ------------------------------------------------------------------
    # Public — one poll cycle
    # ------------------------------------------------------------------

    async def poll_once(self) -> List[dict]:
        """Discover drives, poll S.M.A.R.T attrs, persist snapshots, fire alerts.
        Returns the list of snapshot dicts produced this cycle."""
        devices = await asyncio.to_thread(self._scan_devices)
        snapshots = []
        for dev in devices:
            snap = await asyncio.to_thread(self._read_smart, dev)
            if snap:
                snapshots.append(snap)
        if snapshots:
            await self._persist(snapshots)
            await self._dispatch_alerts(snapshots)
        return snapshots

    # ------------------------------------------------------------------
    # smartctl wrappers
    # ------------------------------------------------------------------

    @staticmethod
    def _scan_devices() -> List[str]:
        try:
            out = subprocess.run(
                ["smartctl", "--scan", "-j"], capture_output=True, timeout=15, check=False,
            )
            if out.returncode != 0:
                return []
            data = json.loads(out.stdout)
            return [d["name"] for d in data.get("devices", []) if d.get("name")]
        except Exception as e:
            logger.debug(f"smartctl --scan failed: {e}")
            return []

    @staticmethod
    def _read_smart(device: str) -> Optional[dict]:
        try:
            out = subprocess.run(
                ["smartctl", "-A", "-H", "-i", "-j", device],
                capture_output=True, timeout=30, check=False,
            )
            data = json.loads(out.stdout) if out.stdout else {}
        except Exception as e:
            logger.debug(f"smartctl read {device} failed: {e}")
            return None

        attrs = {}
        for a in data.get("ata_smart_attributes", {}).get("table", []):
            attrs[a.get("name")] = a.get("raw", {}).get("value", a.get("value"))

        temp_c = data.get("temperature", {}).get("current")
        if temp_c is None:
            temp_c = attrs.get("Temperature_Celsius")

        return {
            "device": device,
            "model": data.get("model_name") or data.get("model_family"),
            "serial": data.get("serial_number"),
            "passed": data.get("smart_status", {}).get("passed", True),
            "temperature_c": temp_c,
            "power_on_hours": data.get("power_on_time", {}).get("hours")
                or attrs.get("Power_On_Hours"),
            "reallocated_sectors": attrs.get("Reallocated_Sector_Ct", 0),
            "pending_sectors": attrs.get("Current_Pending_Sector", 0),
            "captured_at": datetime.now(timezone.utc),
            "raw": data,
        }

    # ------------------------------------------------------------------
    # Persistence + alerts
    # ------------------------------------------------------------------

    async def _persist(self, snapshots: List[dict]):
        from sqlalchemy import text
        from app.database import async_session_maker
        import uuid

        async with async_session_maker() as db:
            for s in snapshots:
                try:
                    await db.execute(
                        text("""
                            INSERT INTO disk_health_snapshots
                            (id, device, model, serial, passed, temperature_c,
                             power_on_hours, reallocated_sectors, pending_sectors,
                             captured_at)
                            VALUES (:id, :device, :model, :serial, :passed,
                                    :temp, :poh, :realloc, :pending, :captured_at)
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "device": s["device"], "model": s["model"], "serial": s["serial"],
                            "passed": bool(s["passed"]),
                            "temp": s["temperature_c"],
                            "poh": s["power_on_hours"],
                            "realloc": s["reallocated_sectors"],
                            "pending": s["pending_sectors"],
                            "captured_at": s["captured_at"],
                        },
                    )
                except Exception as e:
                    logger.warning(f"disk_health snapshot insert failed for {s['device']}: {e}")
            await db.commit()

    async def _dispatch_alerts(self, snapshots: List[dict]):
        from app.events.linkage_service import linkage_engine
        for s in snapshots:
            severity, reason = self._evaluate(s)
            if severity is None:
                continue
            try:
                await linkage_engine.fire_event(
                    camera_id=None,
                    event_type="disk_warning" if severity == "warning" else "disk_failure",
                    severity=severity,
                    title=f"Disk {severity}: {s['device']}",
                    description=reason,
                    metadata={"device": s["device"], "model": s["model"],
                              "serial": s["serial"], "summary": reason},
                )
            except Exception as e:
                logger.debug(f"disk_health alert dispatch failed: {e}")

    @staticmethod
    def _evaluate(s: dict):
        """Decide severity for one snapshot. Returns (severity, reason)
        or (None, None) if healthy."""
        reasons = []
        sev = None
        # Hard SMART status takes precedence
        if not s.get("passed"):
            return "critical", "S.M.A.R.T overall-health check FAILED"

        temp = s.get("temperature_c") or 0
        realloc = s.get("reallocated_sectors") or 0
        pending = s.get("pending_sectors") or 0

        if temp >= TEMP_FAIL_C or realloc >= REALLOC_FAIL or pending >= PENDING_FAIL:
            sev = "critical"
        elif temp >= TEMP_WARN_C or realloc >= REALLOC_WARN or pending >= PENDING_WARN:
            sev = "warning"

        if temp:
            reasons.append(f"temp={temp}°C")
        if realloc:
            reasons.append(f"reallocated={realloc}")
        if pending:
            reasons.append(f"pending={pending}")
        return sev, ", ".join(reasons) if sev else (None, None)


disk_health_service = DiskHealthService()
