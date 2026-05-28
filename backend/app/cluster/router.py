# =============================================================================
# Cluster Router — N+1 Hot Standby status & control
# =============================================================================

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_admin_user, get_current_user
from app.cluster.service import cluster_service

router = APIRouter(prefix="/cluster", tags=["Cluster"])


@router.get("/status")
async def cluster_status(user: dict = Depends(get_admin_user)):
    """Return full cluster status including all known nodes and camera count."""
    return await cluster_service.get_status()


@router.get("/nodes")
async def list_cluster_nodes(user: dict = Depends(get_current_user)):
    """
    Return list of known cluster nodes.

    Safe on a fresh single-node install — never returns 500.
    Each entry: {node_id, hostname, role, is_leader, last_heartbeat_at,
                 ip_address, version, promoted_at}.
    """
    return await cluster_service.get_nodes()


@router.post("/failover")
async def force_failover(user: dict = Depends(get_admin_user)):
    """
    Trigger a manual failover.  The current leader releases its advisory lock
    so a standby node can acquire it on the next heartbeat tick.
    """
    result = await cluster_service.force_failover()
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result
