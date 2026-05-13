# =============================================================================
# Recording Router — list, timeline, playback, export, download, delete
# =============================================================================

import os
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.recordings.models import (
    RecordingResponse, TimelineResponse, RecordingStatsResponse,
    ExportRequest, ExportResponse, BulkDeleteRequest, MultiSegmentExportRequest,
)
from app.recordings.service import RecordingService
from app.recordings.export_service import export_service
from app.core.dependencies import require_permission
from app.core.permissions import get_accessible_camera_ids
from app.core.audit_logger import write_audit, client_ip
from app.core.security import verify_token
from app.core.rate_limiter import api_limiter

import subprocess

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recordings", tags=["Recordings"])
svc = RecordingService()


# ══════════════════════════════════════════════════════════════════════
# Listing (base path - must come first)
# ══════════════════════════════════════════════════════════════════════

@router.get("", response_model=List[RecordingResponse])
async def list_recordings(
    camera_id: Optional[str] = None,
    start_after: Optional[datetime] = None,
    end_before: Optional[datetime] = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
    _rate_limit = Depends(api_limiter.limit),
):
    allowed = await get_accessible_camera_ids(db, user)
    if camera_id:
        if allowed is not None and camera_id not in allowed:
            raise HTTPException(403, "No access to this camera")
        return await svc.get_by_camera(db, camera_id, start_after, end_before, limit, offset)
    return await svc.search(db, allowed, start_after, end_before, limit, offset)


# ══════════════════════════════════════════════════════════════════════
# Timeline (specific paths - must come BEFORE /{recording_id})
# ══════════════════════════════════════════════════════════════════════

@router.get("/timeline/{camera_id}", response_model=TimelineResponse)
async def recording_timeline(
    camera_id: str,
    day: date = Query(default=None, description="YYYY-MM-DD, defaults to today"),
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
    _rate_limit = Depends(api_limiter.limit),
):
    if day is None:
        day = date.today()
    return await svc.timeline(db, camera_id, day)


@router.get("/dates/{camera_id}")
async def available_dates(
    camera_id: str,
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
):
    dates = await svc.available_dates(db, camera_id)
    return {"camera_id": camera_id, "dates": dates}


# ══════════════════════════════════════════════════════════════════════
# Stats
# ══════════════════════════════════════════════════════════════════════

@router.get("/stats/{camera_id}", response_model=RecordingStatsResponse)
async def recording_stats(
    camera_id: str,
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
):
    return await svc.stats(db, camera_id)


# ══════════════════════════════════════════════════════════════════════
# Playback — redirect to correct segment
# ══════════════════════════════════════════════════════════════════════

@router.get("/playback/{camera_id}")
async def seek_playback(
    camera_id: str,
    timestamp: datetime = Query(..., description="Seek to this moment"),
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
):
    """
    Find the recording that contains the given timestamp.
    Returns the segment and a seek offset (seconds from segment start).
    """
    rec = await svc.find_segment_at(db, camera_id, timestamp)
    if not rec:
        raise HTTPException(404, "No recording at that timestamp")
    offset = (timestamp - rec.start_time).total_seconds()
    return {
        "recording_id": rec.id,
        "file_path": rec.file_path,
        "seek_offset": round(offset, 2),
        "start_time": rec.start_time,
        "end_time": rec.end_time,
        "duration": rec.duration,
    }


@router.get("/playback/{camera_id}/continuous")
async def continuous_playback(
    camera_id: str,
    start_time: datetime = Query(...),
    end_time: Optional[datetime] = None,
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
):
    """
    Return ordered list of segments for continuous playback across segment boundaries.
    Frontend can preload the next segment while playing the current one.
    """
    if not end_time:
        end_time = start_time + timedelta(hours=1)
    segments = await svc.find_segments_in_range(db, camera_id, start_time, end_time)
    if not segments:
        raise HTTPException(404, "No recordings in range")

    result = []
    for rec in segments:
        # Calculate seek offset for the first segment
        offset = max(0, (start_time - rec.start_time).total_seconds()) if rec == segments[0] else 0
        result.append({
            "recording_id": rec.id,
            "file_path": rec.file_path,
            "seek_offset": round(offset, 2),
            "start_time": rec.start_time,
            "end_time": rec.end_time,
            "duration": rec.duration,
        })
    return {"camera_id": camera_id, "segments": result}


# ══════════════════════════════════════════════════════════════════════
# Clip Export (specific paths)
# ══════════════════════════════════════════════════════════════════════

@router.post("/export", response_model=ExportResponse)
async def create_export(
    body: ExportRequest,
    request: Request,
    user: dict = Depends(require_permission("export_clips")),
    db: AsyncSession = Depends(get_db),
):
    """
    Export a clip by concatenating + trimming segments.
    Returns an export job ID — poll /export/{id} for status.
    """
    segments = await svc.find_segments_in_range(db, body.camera_id, body.start_time, body.end_time)
    if not segments:
        raise HTTPException(404, "No recordings in the requested time range")

    job = await export_service.create_export(
        camera_id=body.camera_id,
        start_time=body.start_time,
        end_time=body.end_time,
        segments=segments,
        fmt=body.format,
        db=db,
        user_id=user["id"],
    )

    await write_audit(
        db, action="clip_export", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="recording",
        description=f"Export requested: {body.camera_id} {body.start_time}—{body.end_time}",
        details={"export_id": job.id, "format": body.format},
    )
    await db.commit()

    return ExportResponse(export_id=job.id, status=job.status, progress=job.progress)


@router.get("/export/{export_id}", response_model=ExportResponse)
async def get_export_status(
    export_id: str,
    user: dict = Depends(require_permission("export_clips")),
):
    job = export_service.get_job(export_id)
    if not job:
        raise HTTPException(404, "Export not found")
    return ExportResponse(
        export_id=job.id, status=job.status, progress=job.progress,
        file_path=job.file_path, file_size=job.file_size,
    )


@router.get("/export/{export_id}/download")
async def download_export(
    export_id: str,
    user: dict = Depends(require_permission("export_clips")),
):
    job = export_service.get_job(export_id)
    if not job or job.status != "done" or not job.file_path:
        raise HTTPException(404, "Export not ready")
    return FileResponse(
        job.file_path,
        media_type="video/mp4",
        filename=f"export_{export_id}.{job.format}",
    )


@router.post("/export/multi-segment", response_model=ExportResponse)
async def multi_segment_export(
    body: MultiSegmentExportRequest,
    request: Request,
    user: dict = Depends(require_permission("export_clips")),
    db: AsyncSession = Depends(get_db),
):
    """
    Export multiple clip segments (possibly from different cameras) into a
    single concatenated file. Segments are stitched in order.
    """
    all_recording_segments = []
    for clip in body.segments:
        segs = await svc.find_segments_in_range(
            db, clip.camera_id, clip.start_time, clip.end_time,
        )
        if not segs:
            raise HTTPException(
                404,
                f"No recordings for camera {clip.camera_id} "
                f"between {clip.start_time} and {clip.end_time}",
            )
        all_recording_segments.extend(segs)

    if not all_recording_segments:
        raise HTTPException(404, "No recordings matched any segment")

    # Use the first segment's camera_id as the primary
    job = await export_service.create_export(
        camera_id=body.segments[0].camera_id,
        start_time=body.segments[0].start_time,
        end_time=body.segments[-1].end_time,
        segments=all_recording_segments,
        fmt=body.format,
        db=db,
        user_id=user["id"],
    )

    await write_audit(
        db, action="multi_segment_export", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="recording",
        description=f"Multi-segment export: {len(body.segments)} clips",
        details={"export_id": job.id, "segment_count": len(body.segments)},
    )
    await db.commit()

    return ExportResponse(export_id=job.id, status=job.status, progress=job.progress)


# ══════════════════════════════════════════════════════════════════════
# Bulk Delete (specific path)
# ══════════════════════════════════════════════════════════════════════

@router.post("/bulk-delete")
async def bulk_delete(
    body: BulkDeleteRequest,
    request: Request,
    user: dict = Depends(require_permission("delete_recordings")),
    db: AsyncSession = Depends(get_db),
):
    count = await svc.bulk_delete(db, body.recording_ids)
    await write_audit(
        db, action="recording_bulk_delete", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="recording",
        details={"count": count, "ids": body.recording_ids},
    )
    await db.commit()
    return {"deleted": count}


# ══════════════════════════════════════════════════════════════════════
# Thumbnail scrubbing
# ══════════════════════════════════════════════════════════════════════

@router.get("/thumbnail/{camera_id}")
async def get_thumbnail_at(
    camera_id: str,
    timestamp: datetime = Query(..., description="Moment to extract thumbnail"),
    token: Optional[str] = Query(None, description="JWT token for authentication"),
    db: AsyncSession = Depends(get_db),
):
    """
    Extract a JPEG thumbnail from the recording at the given timestamp.
    Uses FFmpeg to seek into the file and grab a single frame.
    Accepts token via query param for <img> tag compatibility.
    """
    # Verify token from query string
    if not token:
        raise HTTPException(401, "Token required")
    
    payload = verify_token(token, expected_type="access")
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    
    # Convert timezone-aware timestamp to naive UTC (DB stores naive UTC)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.replace(tzinfo=None)
    
    rec = await svc.find_segment_at(db, camera_id, timestamp)
    if not rec or not rec.file_path or not os.path.exists(rec.file_path):
        raise HTTPException(404, "No recording at that timestamp")

    offset = max(0, (timestamp - rec.start_time).total_seconds())
    thumb_dir = os.path.join(settings.THUMBNAIL_PATH, camera_id)
    os.makedirs(thumb_dir, exist_ok=True)
    thumb_path = os.path.join(thumb_dir, f"thumb_{int(timestamp.timestamp())}.jpg")

    if not os.path.exists(thumb_path):
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(round(offset, 2)),
                    "-i", rec.file_path,
                    "-frames:v", "1",
                    "-q:v", "8",
                    "-vf", "scale=320:-1",
                    thumb_path,
                ],
                capture_output=True,
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"Thumbnail generation failed: {e}")
            raise HTTPException(500, "Thumbnail generation failed")

    if not os.path.exists(thumb_path):
        raise HTTPException(500, "Thumbnail generation failed")

    return FileResponse(thumb_path, media_type="image/jpeg")


# ══════════════════════════════════════════════════════════════════════
# Single Recording by ID (dynamic paths - MUST come LAST)
# ══════════════════════════════════════════════════════════════════════

@router.get("/{recording_id}", response_model=RecordingResponse)
async def get_recording(
    recording_id: str,
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
):
    rec = await svc.get_by_id(db, recording_id)
    if not rec:
        raise HTTPException(404)
    return rec


@router.post("/purge")
async def purge_recordings(
    body: dict,
    request: Request,
    user: dict = Depends(require_permission("delete_recordings")),
    db: AsyncSession = Depends(get_db),
):
    """GDPR right-to-erasure (Phase 5.7). Body: {camera_id?, before?} where
    *before* is an ISO date. Deletes matching recordings + files. Locked
    recordings are skipped — operator must unlock first."""
    from sqlalchemy import text
    camera_id = body.get("camera_id")
    before_raw = body.get("before")
    where = ["locked = 0"]
    params = {}
    if camera_id:
        where.append("camera_id = :cid")
        params["cid"] = camera_id
    if before_raw:
        where.append("start_time < :before")
        params["before"] = before_raw
    if not where:
        raise HTTPException(400, "camera_id or before is required")
    sql = f"SELECT id, file_path FROM recordings WHERE {' AND '.join(where)}"
    rows = (await db.execute(text(sql), params)).fetchall()
    deleted = 0
    for rid, fp in rows:
        try:
            if fp and os.path.exists(fp):
                os.remove(fp)
        except OSError:
            pass
        await db.execute(text("DELETE FROM recordings WHERE id = :id"), {"id": rid})
        deleted += 1
    await write_audit(
        db, action="recordings_purge",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="recording",
        description=f"GDPR purge deleted {deleted} recording(s) "
                    f"(camera={camera_id}, before={before_raw})",
        severity="warning",
    )
    await db.commit()
    return {"deleted": deleted}


@router.post("/{recording_id}/export-evidence")
async def export_evidence(
    recording_id: str,
    request: Request,
    user: dict = Depends(require_permission("export_clips")),
    db: AsyncSession = Depends(get_db),
):
    """Build a signed evidence zip (chain of custody + RSA-PSS signature)
    and return the path. Use GET /exports/<filename> to download via nginx."""
    from app.recordings.evidence_export import build_evidence_zip
    from app.cameras.service import CameraService
    rec = await svc.get_by_id(db, recording_id)
    if not rec:
        raise HTTPException(404)
    camera = await CameraService.get_by_id(db, rec.camera_id)
    payload = {
        "id": rec.id, "camera_id": rec.camera_id,
        "camera_name": camera.name if camera else None,
        "file_path": rec.file_path, "start_time": rec.start_time,
        "end_time": rec.end_time, "duration": rec.duration,
        "checksum": rec.checksum,
    }
    try:
        zip_path = build_evidence_zip(payload, user, settings.EXPORT_PATH)
    except FileNotFoundError:
        raise HTTPException(404, "Recording file missing on disk")
    await write_audit(
        db, action="recording_evidence_export",
        user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="recording", resource_id=recording_id,
        description=f"Evidence bundle exported: {os.path.basename(zip_path)}",
    )
    await db.commit()
    return {"path": zip_path, "filename": os.path.basename(zip_path),
            "download_url": f"/exports/{os.path.basename(zip_path)}"}


@router.get("/evidence/public-key")
async def evidence_public_key():
    """Operator hands this PEM file to verifiers so they can confirm
    a chain_of_custody.json signature was produced by *this* NVR."""
    from app.recordings.evidence_export import public_key_pem
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(public_key_pem(), media_type="application/x-pem-file")


@router.post("/{recording_id}/download-token")
async def issue_download_token(
    recording_id: str,
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
):
    """Mint a 15-min single-use signed token for the download endpoint.
    Prevents hot-linking and link sharing — token is bound to (recording_id,
    user_id, expiry) via HMAC-SHA256 over the JWT secret."""
    from app.recordings.download_tokens import issue
    rec = await svc.get_by_id(db, recording_id)
    if not rec:
        raise HTTPException(404)
    return issue(recording_id, user["id"])


@router.get("/{recording_id}/download")
async def download_recording(
    recording_id: str,
    token: Optional[str] = Query(None, description="Signed download token or JWT access token"),
    db: AsyncSession = Depends(get_db),
):
    """Download a recording file. Two auth modes:
       1. Signed download token (preferred): single-use, 15-min TTL, bound
          to recording_id. Mint via POST /download-token.
       2. JWT access token (legacy): browser <a download> from an
          authenticated session.
    """
    if not token:
        raise HTTPException(401, "Token required")

    from app.recordings.download_tokens import verify as verify_download
    bound_user_id = verify_download(token, recording_id)
    if bound_user_id is None:
        # Fallback to JWT access token (legacy path)
        payload = verify_token(token, expected_type="access")
        if not payload:
            raise HTTPException(401, "Invalid or expired token")

    rec = await svc.get_by_id(db, recording_id)
    if not rec:
        raise HTTPException(404)
    if not os.path.exists(rec.file_path):
        raise HTTPException(404, "File not found on disk")
    return FileResponse(
        rec.file_path,
        media_type="video/mp4",
        filename=os.path.basename(rec.file_path),
    )


@router.delete("/{recording_id}", status_code=204)
async def delete_recording(
    recording_id: str,
    request: Request,
    user: dict = Depends(require_permission("delete_recordings")),
    db: AsyncSession = Depends(get_db),
):
    if not await svc.delete_recording(db, recording_id):
        raise HTTPException(404)
    await write_audit(
        db, action="recording_delete", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="recording", resource_id=recording_id,
    )
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# Lock / Protect
# ══════════════════════════════════════════════════════════════════════

@router.put("/{recording_id}/lock", response_model=RecordingResponse)
async def lock_recording(
    recording_id: str,
    request: Request,
    user: dict = Depends(require_permission("delete_recordings")),
    db: AsyncSession = Depends(get_db),
):
    """
    Lock (protect) a recording so it is never deleted by retention policies.
    Only an admin/operator with delete_recordings permission can lock/unlock.
    """
    rec = await svc.get_by_id(db, recording_id)
    if not rec:
        raise HTTPException(404)
    if rec.locked:
        return rec   # idempotent

    rec.locked = True
    rec.locked_by = user["username"]
    rec.locked_at = datetime.utcnow()
    await write_audit(
        db, action="recording_lock", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="recording", resource_id=recording_id,
    )
    await db.commit()
    await db.refresh(rec)
    return rec


@router.post("/{recording_id}/verify")
async def verify_recording(
    recording_id: str,
    request: Request,
    user: dict = Depends(require_permission("view_playback")),
    db: AsyncSession = Depends(get_db),
):
    """Recompute SHA-256 of a recording and compare with stored checksum.
    Returns {status: verified|corrupted|missing_file|not_found}."""
    result = await svc.verify_recording(db, recording_id)
    await write_audit(
        db, action="recording_verify", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="recording", resource_id=recording_id,
        description=f"Integrity check: {result.get('status')}",
    )
    await db.commit()
    return result


@router.put("/{recording_id}/unlock", response_model=RecordingResponse)
async def unlock_recording(
    recording_id: str,
    request: Request,
    user: dict = Depends(require_permission("delete_recordings")),
    db: AsyncSession = Depends(get_db),
):
    """Remove lock — recording becomes eligible for retention deletion again."""
    rec = await svc.get_by_id(db, recording_id)
    if not rec:
        raise HTTPException(404)
    if not rec.locked:
        return rec   # idempotent

    rec.locked = False
    rec.locked_by = None
    rec.locked_at = None
    await write_audit(
        db, action="recording_unlock", user_id=user["id"], username=user["username"],
        ip_address=client_ip(request), resource_type="recording", resource_id=recording_id,
    )
    await db.commit()
    await db.refresh(rec)
    return rec
