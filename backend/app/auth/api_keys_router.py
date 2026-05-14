# =============================================================================
# API Keys Router — admin CRUD for machine-to-machine API keys.
#
# All routes require an authenticated user with admin role. Listing exposes
# only key metadata (prefix + scopes), never the plaintext value. The
# plaintext is returned exactly once at creation time.
# =============================================================================

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_keys import (
    APIKeyCreate,
    APIKeyCreateResponse,
    APIKeyResponse,
    APIKeyService,
)
from app.core.dependencies import get_admin_user
from app.database import get_db


router = APIRouter(prefix="/api/admin/api-keys", tags=["admin-api-keys"])


@router.post(
    "",
    response_model=APIKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new API key (plaintext shown once)",
)
async def create_key(
    data: APIKeyCreate,
    admin=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> APIKeyCreateResponse:
    key, plaintext = await APIKeyService.create(
        db, data, created_by=admin.get("id")
    )
    return APIKeyCreateResponse(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        scopes=key.scopes,
        enabled=key.enabled,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        last_used_ip=key.last_used_ip,
        expires_at=key.expires_at,
        plaintext_key=plaintext,
    )


@router.get(
    "",
    response_model=List[APIKeyResponse],
    summary="List all API keys (metadata only, no plaintext)",
)
async def list_keys(
    admin=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> List[APIKeyResponse]:
    keys = await APIKeyService.list_all(db)
    return [APIKeyResponse.model_validate(k) for k in keys]


@router.post(
    "/{key_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key (soft delete, history preserved)",
)
async def revoke_key(
    key_id: str,
    admin=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not await APIKeyService.revoke(db, key_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or already revoked",
        )


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete an API key",
)
async def delete_key(
    key_id: str,
    admin=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not await APIKeyService.delete(db, key_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
