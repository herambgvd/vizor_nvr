# =============================================================================
# Cluster Service — N+1 Hot Standby with Postgres Leader Election
# =============================================================================
#
# LEADER ELECTION PROTOCOL
# ────────────────────────
# Each NVR node runs a periodic heartbeat task (default every 5 s).  On each
# tick the node executes:
#
#   SELECT pg_try_advisory_lock(42)
#
# pg_try_advisory_lock is session-scoped: if the current DB *session* already
# holds the lock, the call returns TRUE without blocking.  If another session
# holds it, the call returns FALSE immediately (non-blocking).
#
# The node that successfully acquires the lock is the *active* (leader) node.
# All other nodes are *standby*.  The lock is implicitly released when the DB
# session ends (connection drop / process restart), so a dead leader is
# replaced within one heartbeat interval by the standby that next acquires it.
#
# Manual failover: the leader calls pg_advisory_unlock(42) and then demotes
# itself; the next heartbeat by a standby will acquire the freed lock.
#
# Single-node mode: the sole node always acquires the lock and runs as leader.
# No configuration needed — the cluster service degrades gracefully when the
# cluster_nodes table is not yet migrated (e.g. SQLite dev installs).
#
# IDEMPOTENCY
# ───────────
# start() is idempotent: calling it when _running=True is a no-op.
# stop() cancels the background task and gracefully demotes leadership.
#
# =============================================================================

import asyncio
import logging
import os
import socket
from datetime import datetime, timezone
from typing import Optional, Dict

from app.database import async_session_maker
from app.config import settings

logger = logging.getLogger(__name__)

# Postgres advisory lock ID — arbitrary constant shared by all nodes
_LEADER_LOCK_ID = 42


class ClusterService:
    """Manages N+1 hot-standby clustering via Postgres advisory locks."""

    def __init__(self):
        self._node_id: str = (
            settings.NVR_NODE_ID or os.getenv("NVR_NODE_ID", "") or socket.gethostname()
        )
        self._hostname: str = socket.gethostname()
        self._ip: str = settings.NVR_NODE_IP or os.getenv("NVR_NODE_IP", "")
        self._interval: int = settings.CLUSTER_HEARTBEAT_INTERVAL
        self._lease_ttl: int = settings.CLUSTER_LEASE_TTL
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._is_leader: bool = False
        self._last_role_change: Optional[datetime] = None
        self._last_heartbeat_at: Optional[datetime] = None

    # ── Public properties ──────────────────────────────────────────────

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def role(self) -> str:
        return "active" if self._is_leader else "standby"

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self):
        """Start the cluster heartbeat task (idempotent)."""
        if self._running:
            logger.debug("Cluster service already running — start() is a no-op")
            return
        self._running = True
        await self._register_node()
        self._task = asyncio.create_task(self._loop(), name="cluster_heartbeat")
        logger.info(
            f"Cluster service started on node={self._node_id} "
            f"interval={self._interval}s lease_ttl={self._lease_ttl}s"
        )

    async def stop(self):
        """Stop the heartbeat task and release leadership gracefully."""
        if not self._running:
            return
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Release leadership so a standby can take over promptly
        if self._is_leader:
            await self._demote("shutdown")
            # Also release the advisory lock so the next heartbeat by a standby
            # can immediately acquire it (don't wait for session expiry).
            try:
                async with async_session_maker() as db:
                    from sqlalchemy import text
                    await db.execute(
                        text("SELECT pg_advisory_unlock(:id)"), {"id": _LEADER_LOCK_ID}
                    )
                    await db.commit()
            except Exception:
                pass
        self._update_metrics()
        logger.info("Cluster service stopped")

    # ── Internal heartbeat loop ────────────────────────────────────────

    async def _loop(self):
        while self._running:
            start = asyncio.get_event_loop().time()
            try:
                await self._heartbeat()
                self._last_heartbeat_at = datetime.now(timezone.utc)
            except Exception as exc:
                logger.error(f"[cluster] Heartbeat error on node {self._node_id}: {exc}")
            elapsed = asyncio.get_event_loop().time() - start
            sleep_for = max(0.0, self._interval - elapsed)
            await asyncio.sleep(sleep_for)

    async def _heartbeat(self):
        from sqlalchemy import text

        async with async_session_maker() as db:
            try:
                result = await db.execute(
                    text("SELECT pg_try_advisory_lock(:id)"), {"id": _LEADER_LOCK_ID}
                )
                got_lock = result.scalar()
            except Exception as exc:
                # Non-Postgres (SQLite dev install) — act as single-node leader
                logger.debug(f"[cluster] Advisory lock not available ({exc}); acting as leader")
                if not self._is_leader:
                    await self._promote(db)
                else:
                    await self._update_heartbeat(db)
                self._update_metrics()
                return

            if got_lock:
                if not self._is_leader:
                    await self._promote(db)
                else:
                    await self._update_heartbeat(db)
            else:
                if self._is_leader:
                    await self._demote("lost_lock")
                else:
                    await self._update_heartbeat(db)

        self._update_metrics()

    def _update_metrics(self):
        try:
            from app.core.metrics import GVD_CLUSTER_ROLE
            GVD_CLUSTER_ROLE.labels(node=self._node_id).set(1 if self._is_leader else 0)
        except Exception:
            pass

    # ── Node registration ──────────────────────────────────────────────

    async def _register_node(self):
        """Upsert this node row in cluster_nodes (idempotent)."""
        try:
            async with async_session_maker() as db:
                from app.cluster.models import ClusterNode
                from sqlalchemy import select
                result = await db.execute(
                    select(ClusterNode).where(ClusterNode.node_id == self._node_id)
                )
                node = result.scalar_one_or_none()
                if not node:
                    node = ClusterNode(
                        node_id=self._node_id,
                        hostname=self._hostname,
                        ip_address=self._ip,
                        version=getattr(settings, "VERSION", "2.0.0"),
                        role="standby",
                        is_leader=False,
                    )
                    db.add(node)
                    await db.commit()
                    logger.info(f"[cluster] Registered node {self._node_id}")
        except Exception as exc:
            logger.warning(f"[cluster] Node registration failed (non-fatal): {exc}")

    # ── Role transitions ───────────────────────────────────────────────

    async def _promote(self, db):
        """Promote this node to active leader."""
        logger.warning(f"[cluster] Node {self._node_id} PROMOTED to active leader")
        self._is_leader = True
        self._last_role_change = datetime.now(timezone.utc)

        try:
            from app.cluster.models import ClusterNode
            from sqlalchemy import select, text
            result = await db.execute(
                select(ClusterNode).where(ClusterNode.node_id == self._node_id)
            )
            node = result.scalar_one_or_none()
            if node:
                node.role = "active"
                node.is_leader = True
                node.promoted_at = self._last_role_change
                node.failover_reason = None
                node.last_heartbeat_at = self._last_role_change

            # Demote any stale leader rows
            await db.execute(
                text(
                    "UPDATE cluster_nodes "
                    "SET role = 'standby', is_leader = false, demoted_at = NOW() "
                    "WHERE node_id != :nid AND is_leader = true"
                ),
                {"nid": self._node_id},
            )
            await db.commit()
        except Exception as exc:
            logger.warning(f"[cluster] Failed to persist promotion state: {exc}")

        # Start camera services
        try:
            from app.services.camera_monitor import camera_monitor
            await camera_monitor.start()
            logger.info("[cluster] Camera monitor started after promotion")
        except Exception as exc:
            logger.error(f"[cluster] Failed to start camera monitor after promotion: {exc}")

        # Emit failover event
        try:
            from app.events.linkage_service import linkage_engine
            await linkage_engine.fire_event(
                camera_id=None,
                event_type="cluster_failover",
                severity="critical",
                title="NVR failover — node promoted to active",
                description=f"Node {self._node_id} became active leader",
            )
        except Exception:
            pass

    async def _demote(self, reason: str):
        """Demote this node to standby."""
        logger.warning(f"[cluster] Node {self._node_id} DEMOTED to standby (reason={reason})")
        self._is_leader = False
        self._last_role_change = datetime.now(timezone.utc)

        try:
            async with async_session_maker() as db:
                from app.cluster.models import ClusterNode
                from sqlalchemy import select
                result = await db.execute(
                    select(ClusterNode).where(ClusterNode.node_id == self._node_id)
                )
                node = result.scalar_one_or_none()
                if node:
                    node.role = "standby"
                    node.is_leader = False
                    node.demoted_at = self._last_role_change
                    node.failover_reason = reason
                await db.commit()
        except Exception as exc:
            logger.warning(f"[cluster] Failed to persist demotion state: {exc}")

        # Stop recordings to avoid split-brain
        try:
            from app.services.ffmpeg_manager import ffmpeg_manager
            await ffmpeg_manager.cleanup_all()
            logger.info("[cluster] All FFmpeg processes stopped after demotion")
        except Exception as exc:
            logger.error(f"[cluster] Failed to stop recordings after demotion: {exc}")

        # Stop camera monitor
        try:
            from app.services.camera_monitor import camera_monitor
            await camera_monitor.stop()
        except Exception:
            pass

    async def _update_heartbeat(self, db):
        try:
            from app.cluster.models import ClusterNode
            from sqlalchemy import select
            result = await db.execute(
                select(ClusterNode).where(ClusterNode.node_id == self._node_id)
            )
            node = result.scalar_one_or_none()
            if node:
                node.last_heartbeat_at = datetime.now(timezone.utc)
                await db.commit()
        except Exception as exc:
            logger.debug(f"[cluster] Heartbeat DB update failed: {exc}")

    # ── Public API ─────────────────────────────────────────────────────

    async def get_nodes(self) -> list:
        """
        Return list of known cluster nodes.

        On a fresh single-node install (cluster_nodes table empty or not yet
        created) this synthesises a single-node response from in-memory state
        so GET /api/cluster/nodes never returns 500.
        """
        try:
            async with async_session_maker() as db:
                from app.cluster.models import ClusterNode
                from sqlalchemy import select
                result = await db.execute(
                    select(ClusterNode).order_by(ClusterNode.created_at)
                )
                rows = result.scalars().all()
                if rows:
                    return [
                        {
                            "node_id": n.node_id,
                            "hostname": n.hostname,
                            "role": n.role,
                            "is_leader": n.is_leader,
                            "last_heartbeat_at": (
                                n.last_heartbeat_at.isoformat()
                                if n.last_heartbeat_at
                                else None
                            ),
                            "ip_address": n.ip_address,
                            "version": n.version,
                            "promoted_at": (
                                n.promoted_at.isoformat() if n.promoted_at else None
                            ),
                        }
                        for n in rows
                    ]
        except Exception as exc:
            logger.debug(f"[cluster] get_nodes DB query failed: {exc}")

        # Fallback: synthesise from in-memory state (single-node / pre-migration)
        return [
            {
                "node_id": self._node_id,
                "hostname": self._hostname,
                "role": self.role,
                "is_leader": self._is_leader,
                "last_heartbeat_at": (
                    self._last_heartbeat_at.isoformat()
                    if self._last_heartbeat_at
                    else None
                ),
                "ip_address": self._ip,
                "version": getattr(settings, "VERSION", "2.0.0"),
                "promoted_at": (
                    self._last_role_change.isoformat()
                    if self._is_leader and self._last_role_change
                    else None
                ),
            }
        ]

    async def get_status(self) -> Dict:
        nodes = await self.get_nodes()
        leader_node = next((n["node_id"] for n in nodes if n["is_leader"]), None)

        camera_count = 0
        try:
            from app.cameras.models import Camera
            from sqlalchemy import select, func
            async with async_session_maker() as db:
                result = await db.execute(select(func.count(Camera.id)))
                camera_count = result.scalar() or 0
        except Exception:
            pass

        return {
            "this_node": self._node_id,
            "role": self.role,
            "is_leader": self._is_leader,
            "leader_node": leader_node,
            "nodes": nodes,
            "camera_count": camera_count,
        }

    async def force_failover(self) -> Dict:
        """Manual failover — release lock so standby can take over."""
        if not self._is_leader:
            return {"success": False, "message": "This node is not the leader"}
        await self._demote("manual_failover")
        try:
            async with async_session_maker() as db:
                from sqlalchemy import text
                await db.execute(
                    text("SELECT pg_advisory_unlock(:id)"), {"id": _LEADER_LOCK_ID}
                )
                await db.commit()
        except Exception:
            pass
        self._update_metrics()
        return {
            "success": True,
            "message": "Failover triggered — standby will promote on next heartbeat",
        }


# Module singleton
cluster_service = ClusterService()
