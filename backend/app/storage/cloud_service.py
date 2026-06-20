# =============================================================================
# Cloud Storage Service — S3-compatible storage (RustFS, MinIO, AWS S3)
# =============================================================================
# Handles uploading recordings to S3-compatible cloud storage.
# RustFS is fully S3-compatible, so we use boto3 for all operations.
# =============================================================================

import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import CloudStorageConfig
from app.database import async_session_maker

logger = logging.getLogger(__name__)

# boto3 is optional - graceful degradation
try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import ClientError, EndpointConnectionError
    _HAS_BOTO3 = True
except ImportError:
    _HAS_BOTO3 = False
    logger.info("boto3 not installed — cloud storage disabled. pip install boto3")


class CloudStorageService:
    """
    Manages uploads/downloads to S3-compatible storage (RustFS, MinIO, AWS S3).
    
    RustFS Configuration Example:
        endpoint: http://localhost:9000  (or your RustFS server URL)
        bucket: nvr-recordings
        access_key: your_access_key
        secret_key: your_secret_key
    """

    def __init__(self):
        self._clients: Dict[str, Any] = {}  # Cache S3 clients per config ID

    def _get_client(self, config: CloudStorageConfig):
        """Get or create an S3 client for the given config."""
        if not _HAS_BOTO3:
            raise RuntimeError("boto3 not installed. pip install boto3")

        if config.id in self._clients:
            return self._clients[config.id]

        # Build boto3 client for S3-compatible storage. The secret key is stored
        # encrypted at rest; decrypt it only here when constructing the client.
        from app.core.crypto import decrypt_value
        client_kwargs = {
            "service_name": "s3",
            "aws_access_key_id": config.access_key,
            "aws_secret_access_key": decrypt_value(config.secret_key),
            "region_name": config.region or "us-east-1",
        }

        # Custom endpoint for RustFS/MinIO
        if config.endpoint:
            client_kwargs["endpoint_url"] = config.endpoint
            # For self-signed certs or local testing
            client_kwargs["config"] = BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},  # Path-style for compatibility
            )

        client = boto3.client(**client_kwargs)
        self._clients[config.id] = client
        return client

    def clear_client_cache(self, config_id: Optional[str] = None):
        """Clear cached S3 clients (useful after config update)."""
        if config_id:
            self._clients.pop(config_id, None)
        else:
            self._clients.clear()

    # ------------------------------------------------------------------
    # Upload Operations
    # ------------------------------------------------------------------

    async def upload_file(
        self,
        config: CloudStorageConfig,
        local_path: str,
        remote_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upload a file to cloud storage.
        
        Args:
            config: Cloud storage configuration
            local_path: Path to local file
            remote_key: Optional custom key (default: prefix + filename)
            
        Returns:
            {"success": True, "key": "...", "size": 123} or error dict
        """
        if not os.path.exists(local_path):
            return {"success": False, "error": f"File not found: {local_path}"}

        if not remote_key:
            filename = os.path.basename(local_path)
            prefix = config.prefix.rstrip("/")
            remote_key = f"{prefix}/{filename}" if prefix else filename

        def _upload():
            try:
                client = self._get_client(config)
                file_size = os.path.getsize(local_path)

                # Use multipart upload for large files (>100MB)
                if file_size > 100 * 1024 * 1024:
                    from boto3.s3.transfer import TransferConfig
                    transfer_config = TransferConfig(
                        multipart_threshold=100 * 1024 * 1024,
                        multipart_chunksize=50 * 1024 * 1024,
                        max_concurrency=4,
                    )
                    client.upload_file(
                        local_path, config.bucket, remote_key,
                        Config=transfer_config,
                    )
                else:
                    client.upload_file(local_path, config.bucket, remote_key)

                return {
                    "success": True,
                    "key": remote_key,
                    "bucket": config.bucket,
                    "size": file_size,
                }
            except ClientError as e:
                logger.error(f"S3 upload error: {e}")
                return {"success": False, "error": str(e)}
            except EndpointConnectionError as e:
                logger.error(f"S3 connection error: {e}")
                return {"success": False, "error": "Connection failed - check endpoint"}
            except Exception as e:
                logger.error(f"Upload error: {e}")
                return {"success": False, "error": str(e)}

        return await asyncio.to_thread(_upload)

    async def upload_recording(
        self,
        db: AsyncSession,
        recording_id: str,
        config_id: str,
    ) -> Dict[str, Any]:
        """
        Upload a recording to cloud storage.
        
        Args:
            db: Database session
            recording_id: Recording ID
            config_id: Cloud config ID
            
        Returns:
            Upload result dict
        """
        from app.recordings.models import Recording

        # Get recording
        result = await db.execute(
            select(Recording).where(Recording.id == recording_id)
        )
        recording = result.scalar_one_or_none()
        if not recording:
            return {"success": False, "error": "Recording not found"}

        # Get cloud config
        config = await self.get_config(db, config_id)
        if not config:
            return {"success": False, "error": "Cloud config not found"}
        if not config.is_active:
            return {"success": False, "error": "Cloud config is disabled"}

        # Build remote key: prefix/camera_id/date/filename
        filename = os.path.basename(recording.file_path)
        date_str = recording.start_time.strftime("%Y-%m-%d")
        prefix = config.prefix.rstrip("/")
        remote_key = f"{prefix}/{recording.camera_id}/{date_str}/{filename}"

        return await self.upload_file(config, recording.file_path, remote_key)

    # ------------------------------------------------------------------
    # Download Operations
    # ------------------------------------------------------------------

    async def download_file(
        self,
        config: CloudStorageConfig,
        remote_key: str,
        local_path: str,
    ) -> Dict[str, Any]:
        """Download a file from cloud storage."""
        def _download():
            try:
                client = self._get_client(config)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                client.download_file(config.bucket, remote_key, local_path)
                return {"success": True, "path": local_path}
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                if error_code == "404":
                    return {"success": False, "error": "File not found in cloud"}
                return {"success": False, "error": str(e)}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return await asyncio.to_thread(_download)

    # ------------------------------------------------------------------
    # List & Delete Operations
    # ------------------------------------------------------------------

    async def list_objects(
        self,
        config: CloudStorageConfig,
        prefix: Optional[str] = None,
        max_keys: int = 1000,
    ) -> Dict[str, Any]:
        """List objects in cloud storage."""
        def _list():
            try:
                client = self._get_client(config)
                kwargs = {"Bucket": config.bucket, "MaxKeys": max_keys}
                if prefix:
                    kwargs["Prefix"] = prefix
                elif config.prefix:
                    kwargs["Prefix"] = config.prefix

                response = client.list_objects_v2(**kwargs)
                objects = []
                for obj in response.get("Contents", []):
                    objects.append({
                        "key": obj["Key"],
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat(),
                    })
                return {
                    "success": True,
                    "objects": objects,
                    "count": len(objects),
                    "truncated": response.get("IsTruncated", False),
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

        return await asyncio.to_thread(_list)

    async def delete_object(
        self,
        config: CloudStorageConfig,
        remote_key: str,
    ) -> Dict[str, Any]:
        """Delete an object from cloud storage."""
        def _delete():
            try:
                client = self._get_client(config)
                client.delete_object(Bucket=config.bucket, Key=remote_key)
                return {"success": True, "key": remote_key}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return await asyncio.to_thread(_delete)

    # ------------------------------------------------------------------
    # Connection Test
    # ------------------------------------------------------------------

    async def test_connection(self, config: CloudStorageConfig) -> Dict[str, Any]:
        """Test connection to cloud storage."""
        def _test():
            try:
                client = self._get_client(config)
                
                # Try to head the bucket
                client.head_bucket(Bucket=config.bucket)
                
                # Try to list (limited)
                response = client.list_objects_v2(
                    Bucket=config.bucket, 
                    MaxKeys=1,
                    Prefix=config.prefix or "",
                )
                
                return {
                    "success": True,
                    "bucket": config.bucket,
                    "endpoint": config.endpoint or "AWS S3",
                    "message": "Connection successful",
                }
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                error_msg = e.response.get("Error", {}).get("Message", str(e))
                logger.warning(f"[cloud] connection test failed: {error_code}: {error_msg}")
                return {
                    "success": False,
                    "error": "Could not connect. Check the bucket, region, endpoint and credentials.",
                }
            except EndpointConnectionError:
                return {
                    "success": False,
                    "error": "Could not connect. Check the endpoint URL and network.",
                }
            except Exception as e:
                logger.warning(f"[cloud] connection test error: {e}")
                return {"success": False, "error": "Could not connect to cloud storage. Please try again."}

        return await asyncio.to_thread(_test)

    # ------------------------------------------------------------------
    # Config CRUD (delegates to storage service)
    # ------------------------------------------------------------------

    @staticmethod
    async def get_all_configs(db: AsyncSession) -> List[CloudStorageConfig]:
        result = await db.execute(
            select(CloudStorageConfig).order_by(CloudStorageConfig.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_config(db: AsyncSession, config_id: str) -> Optional[CloudStorageConfig]:
        result = await db.execute(
            select(CloudStorageConfig).where(CloudStorageConfig.id == config_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_active_sync_configs(db: AsyncSession) -> List[CloudStorageConfig]:
        """Get all configs with sync_enabled=True."""
        result = await db.execute(
            select(CloudStorageConfig).where(
                CloudStorageConfig.is_active.is_(True),
                CloudStorageConfig.sync_enabled.is_(True),
            )
        )
        return list(result.scalars().all())


# Module singleton
cloud_storage_service = CloudStorageService()
