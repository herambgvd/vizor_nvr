# =============================================================================
# Backup / Restore Router
# =============================================================================

import logging
import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.core.dependencies import get_admin_user
from app.settings.backup_service import backup_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings/backup", tags=["Backup & Restore"])


class BackupRequest(BaseModel):
    password: str


class BackupResponse(BaseModel):
    file_path: str
    file_size: int
    created_at: str


@router.post("/create")
async def create_backup(
    data: BackupRequest,
    user: dict = Depends(get_admin_user),
):
    """Create an encrypted backup of all NVR configuration."""
    if len(data.password) < 8:
        raise HTTPException(400, "Backup password must be at least 8 characters")

    path = await backup_service.create_backup(data.password)
    size = os.path.getsize(path)
    return {
        "file_path": path,
        "file_size": size,
        "created_at": __import__("datetime").datetime.utcnow().isoformat(),
    }


@router.post("/restore")
async def restore_backup(
    data: BackupRequest,
    user: dict = Depends(get_admin_user),
):
    """Restore NVR configuration from an encrypted backup."""
    # For security, restore only accepts file path, not upload
    # Use /settings/backup/upload first, then /restore with path
    raise HTTPException(400, "Use /restore-file endpoint with uploaded file")


@router.post("/restore-file")
async def restore_backup_file(
    password: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_admin_user),
):
    """Upload and restore a backup file."""
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        ok = await backup_service.restore_backup(tmp_path, password)
        if not ok:
            raise HTTPException(400, "Restore failed — wrong password or corrupted backup")
        return {"success": True, "message": "Configuration restored successfully"}
    finally:
        os.remove(tmp_path)
