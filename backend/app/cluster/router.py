# =============================================================================
# Cluster Router — N+1 Hot Standby status & control
# =============================================================================

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_admin_user
from app.cluster.service import cluster_service

router = APIRouter(prefix="/cluster", tags=["Cluster"])


@router.get("/status")
async def cluster_status(user: dict = Depends(get_admin_user)):
    return await cluster_service.get_status()


@router.post("/failover")
async def force_failover(user: dict = Depends(get_admin_user)):
    result = await cluster_service.force_failover()
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result
