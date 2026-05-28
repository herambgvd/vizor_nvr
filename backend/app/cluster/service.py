# =============================================================================
# Cluster Service — N+1 Hot Standby with Postgres Leader Election
# =============================================================================
# Each NVR node attempts to acquire a Postgres advisory lock (ID = 42).
# The node that holds the lock is the active/leader.  Standby nodes poll.
# On promotion: register all cameras with go2rtc, start recording.
# On demotion: stop recording, unregister streams.
# =============================================================================

import asyncio
import logging
import os
import socket
from datetime import datetime, timezone
from typing import Optional, List, Dict

from app.database import async_session_maker
from app.config import settings

logger = logging.getLogger(__name__)

# Postgres advisory lock ID — arbitrary constant shared by all nodes
_LEADER_LOCK_ID = 42


class ClusterService:
    """Manages N+1 hot-standby clustering via Postgres advisory locks."""

    def __init__(self):
        self._node_id = os.getenv("NVR_NODE_ID", socket.gethostname())
        self._hostname = socket.gethostname()
        self._ip = os.getenv("NVR_NODE_IP", "")
        self._interval = 5  # heartbeat every 5s
        self._lease_ttl = 15  # lock TTL 15s
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._is_leader = False
        self._last_role_change: Optional[datetime] = None

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def node_id(self) -> str:
        return self._node_id

    async def start(self):
        if self._running:
            return
        self._running = True
        # Ensure node row exists
        await self._register_node()
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Cluster service started on node {self._node_id}")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Release leadership gracefully
        if self._is_leader:
            await self._demote("shutdown")
        logger.info("Cluster service stopped")

    async def _register_node(self):
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
                    logger.info(f"Registered cluster node {self._node_id}")
        except Exception as e:
            logger.warning(f"Cluster node registration failed: {e}")

    async def _loop(self):
        while self._running:
            try:
                await self._heartbeat()
            except Exception as e:
                logger.error(f"Cluster heartbeat error: {e}")
            await asyncio.sleep(self._interval)

    async def _heartbeat(self):
        async with async_session_maker() as db:
            # Try to acquire leader lock via pg_advisory_lock
            # pg_try_advisory_lock returns True if lock acquired, False if held by another session
            from sqlalchemy import text, select
            result = await db.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": _LEADER_LOCK_ID})
            got_lock = result.scalar()

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

    async def _promote(self, db):
        """Promote this node to active leader."""
        logger.warning(f"Node {self._node_id} PROMOTED to active leader")
        self._is_leader = True
        self._last_role_change = datetime.now(timezone.utc)

        from app.cluster.models import ClusterNode
        from sqlalchemy import select
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
        await db.commit()

        # Demote any other nodes that think they are leader (stale data)
        await db.execute(
            text("""
                UPDATE cluster_nodes
                SET role = 'standby', is_leader = false, demoted_at = NOW()
                WHERE node_id != :nid AND is_leader = true
            """),
            {"nid": self._node_id},
        )
        await db.commit()

        # Start all camera recordings
        try:
            from app.services.ffmpeg_manager import ffmpeg_manager
            from app.services.camera_monitor import camera_monitor
            await camera_monitor.start()
            logger.info("Camera monitor started after promotion")
        except Exception as e:
            logger.error(f"Failed to start cameras after promotion: {e}")

        # Notify via linkage engine
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
        logger.warning(f"Node {self._node_id} DEMOTED to standby ({reason})")
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
        except Exception as e:
            logger.warning(f"Failed to update demotion state: {e}")

        # Stop recordings to avoid split-brain
        try:
            from app.services.ffmpeg_manager import ffmpeg_manager
            await ffmpeg_manager.cleanup_all()
            logger.info("All FFmpeg processes stopped after demotion")
        except Exception as e:
            logger.error(f"Failed to stop recordings after demotion: {e}")

        # Stop camera monitor
        try:
            from app.services.camera_monitor import camera_monitor
            await camera_monitor.stop()
        except Exception:
            pass

    async def _update_heartbeat(self, db):
        from app.cluster.models import ClusterNode
        from sqlalchemy import select
        result = await db.execute(
            select(ClusterNode).where(ClusterNode.node_id == self._node_id)
        )
        node = result.scalar_one_or_none()
        if node:
            node.last_heartbeat_at = datetime.now(timezone.utc)
            await db.commit()

    async def get_status(self) -> Dict:
        nodes = []
        leader_node = None
        try:
            async with async_session_maker() as db:
                from app.cluster.models import ClusterNode
                from sqlalchemy import select
                result = await db.execute(
                    select(ClusterNode).order_by(ClusterNode.created_at)
                )
                for n in result.scalars().all():
                    nodes.append({
                        "node_id": n.node_id,
                        "hostname": n.hostname,
                        "role": n.role,
                        "is_leader": n.is_leader,
                        "last_heartbeat_at": n.last_heartbeat_at.isoformat() if n.last_heartbeat_at else None,
                        "ip_address": n.ip_address,
                    })
                    if n.is_leader:
                        leader_node = n.node_id
        except Exception as e:
            logger.debug(f"Cluster status query failed: {e}")

        camera_count = 0
        try:
            from app.cameras.models import Camera
            async with async_session_maker() as db:
                from sqlalchemy import func
                result = await db.execute(select(func.count(Camera.id)))
                camera_count = result.scalar() or 0
        except Exception:
            pass

        return {
            "this_node": self._node_id,
            "role": "active" if self._is_leader else "standby",
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
        # Release advisory lock
        try:
            async with async_session_maker() as db:
                from sqlalchemy import text
                await db.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": _LEADER_LOCK_ID})
                await db.commit()
        except Exception:
            pass
        return {"success": True, "message": "Failover triggered — standby will promote shortly"}


# Module singleton
cluster_service = ClusterService()
