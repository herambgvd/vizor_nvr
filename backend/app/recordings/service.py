# =============================================================================
# Recording Service — queries, timeline, stats, deletion
# =============================================================================

import os
import logging
from typing import Optional, List
from datetime import datetime, date, timedelta, timezone

from sqlalchemy import select, func, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.recordings.models import Recording

logger = logging.getLogger(__name__)


def _to_naive_utc(dt: datetime) -> datetime:
    """Convert timezone-aware datetime to naive UTC for PostgreSQL TIMESTAMP WITHOUT TIME ZONE."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        # Convert to UTC then remove tzinfo
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class RecordingService:

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @staticmethod
    async def get_by_camera(
        db: AsyncSession,
        camera_id: str,
        start_after: Optional[datetime] = None,
        end_before: Optional[datetime] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[Recording]:
        q = select(Recording).where(Recording.camera_id == camera_id)
        if start_after:
            q = q.where(Recording.start_time >= _to_naive_utc(start_after))
        if end_before:
            q = q.where(Recording.start_time <= _to_naive_utc(end_before))
        q = q.order_by(Recording.start_time.desc()).limit(limit).offset(offset)
        result = await db.execute(q)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(db: AsyncSession, recording_id: str) -> Optional[Recording]:
        result = await db.execute(select(Recording).where(Recording.id == recording_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def search(
        db: AsyncSession,
        camera_ids: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Recording]:
        q = select(Recording)
        if camera_ids:
            q = q.where(Recording.camera_id.in_(camera_ids))
        if start_time:
            q = q.where(Recording.start_time >= _to_naive_utc(start_time))
        if end_time:
            q = q.where(Recording.start_time <= _to_naive_utc(end_time))
        q = q.order_by(Recording.start_time.desc()).limit(limit).offset(offset)
        result = await db.execute(q)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    @staticmethod
    async def timeline(db: AsyncSession, camera_id: str, day: date) -> dict:
        """
        Return a timeline of recording segments for a specific camera and day.
        Used by the frontend timeline scrubber.
        """
        day_start = datetime(day.year, day.month, day.day)
        day_end = day_start + timedelta(days=1)

        result = await db.execute(
            select(Recording)
            .where(
                Recording.camera_id == camera_id,
                Recording.start_time < day_end,
                Recording.end_time > day_start,
            )
            .order_by(Recording.start_time)
        )
        recordings = result.scalars().all()

        segments = []
        total_seconds = 0
        for rec in recordings:
            seg_start = max(rec.start_time, day_start)
            seg_end = min(rec.end_time, day_end) if rec.end_time else day_end
            seg_dur = int((seg_end - seg_start).total_seconds())
            total_seconds += seg_dur
            segments.append({
                "start": seg_start,
                "end": seg_end,
                "recording_id": rec.id,
            })

        return {
            "camera_id": camera_id,
            "date": day.isoformat(),
            "segments": segments,
            "total_seconds": total_seconds,
        }

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @staticmethod
    async def stats(db: AsyncSession, camera_id: str) -> dict:
        result = await db.execute(
            select(
                func.count(Recording.id),
                func.coalesce(func.sum(Recording.file_size), 0),
                func.min(Recording.start_time),
                func.max(Recording.start_time),
                func.coalesce(func.sum(Recording.duration), 0),
            ).where(Recording.camera_id == camera_id)
        )
        row = result.one()
        return {
            "camera_id": camera_id,
            "total_recordings": row[0],
            "total_size_bytes": row[1],
            "oldest_recording": row[2],
            "newest_recording": row[3],
            "total_duration_seconds": row[4],
        }

    # ------------------------------------------------------------------
    # Segment lookup — for playback at specific timestamp
    # ------------------------------------------------------------------

    @staticmethod
    async def find_segment_at(
        db: AsyncSession, camera_id: str, timestamp: datetime,
    ) -> Optional[Recording]:
        """Find the recording segment that contains a specific timestamp."""
        ts = _to_naive_utc(timestamp)
        result = await db.execute(
            select(Recording).where(
                Recording.camera_id == camera_id,
                Recording.start_time <= ts,
                Recording.end_time >= ts,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def find_segments_in_range(
        db: AsyncSession, camera_id: str, start: datetime, end: datetime,
    ) -> List[Recording]:
        """Find all segments overlapping a time range (for export)."""
        start_naive = _to_naive_utc(start)
        end_naive = _to_naive_utc(end)
        result = await db.execute(
            select(Recording)
            .where(
                Recording.camera_id == camera_id,
                Recording.start_time < end_naive,
                Recording.end_time > start_naive,
            )
            .order_by(Recording.start_time)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    @staticmethod
    async def delete_recording(db: AsyncSession, recording_id: str) -> bool:
        rec = await RecordingService.get_by_id(db, recording_id)
        if not rec:
            return False
        # Delete the file from disk
        if rec.file_path and os.path.exists(rec.file_path):
            try:
                os.unlink(rec.file_path)
            except Exception as e:
                logger.warning(f"Could not delete file {rec.file_path}: {e}")
        await db.delete(rec)
        await db.commit()
        return True

    @staticmethod
    async def bulk_delete(db: AsyncSession, recording_ids: List[str]) -> int:
        result = await db.execute(
            select(Recording).where(Recording.id.in_(recording_ids))
        )
        recordings = list(result.scalars().all())
        count = 0
        for rec in recordings:
            if rec.file_path and os.path.exists(rec.file_path):
                try:
                    os.unlink(rec.file_path)
                except Exception:
                    pass
            await db.delete(rec)
            count += 1
        await db.commit()
        return count

    @staticmethod
    async def delete_by_camera(db: AsyncSession, camera_id: str) -> int:
        result = await db.execute(
            select(Recording).where(Recording.camera_id == camera_id)
        )
        recordings = list(result.scalars().all())
        count = 0
        for rec in recordings:
            if rec.file_path and os.path.exists(rec.file_path):
                try:
                    os.unlink(rec.file_path)
                except Exception:
                    pass
            await db.delete(rec)
            count += 1
        await db.commit()
        return count

    # ------------------------------------------------------------------
    # Register new segment (called by FFmpeg manager)
    # ------------------------------------------------------------------

    @staticmethod
    async def register_segment(
        db: AsyncSession,
        camera_id: str,
        file_path: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        duration: Optional[int] = None,
        file_size: Optional[int] = None,
        stream_type: str = "main",
        storage_pool_id: Optional[str] = None,
        checksum: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Register a recording segment using raw SQL to avoid ORM import issues."""
        import uuid
        from sqlalchemy import text

        rec_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO recordings (id, camera_id, file_path, start_time, end_time, duration,
                                        file_size, stream_type, storage_pool_id, trigger_type, locked,
                                        checksum, integrity_status)
                VALUES (:id, :camera_id, :file_path, :start_time, :end_time, :duration,
                        :file_size, :stream_type, :storage_pool_id, :trigger_type, :locked,
                        :checksum, :integrity_status)
            """),
            {
                "id": rec_id,
                "camera_id": camera_id,
                "file_path": file_path,
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration,
                "file_size": file_size,
                "stream_type": stream_type,
                "storage_pool_id": storage_pool_id,
                "trigger_type": "continuous",
                "locked": False,
                "checksum": checksum,
                "integrity_status": "verified" if checksum else "unchecked",
            }
        )
        await db.commit()
        return rec_id

    @staticmethod
    def compute_sha256(file_path: str, chunk_size: int = 1024 * 1024) -> Optional[str]:
        """Stream-hash a file. Returns hex digest or None on read error.
        Used by integrity verification and by ffmpeg_manager after each segment."""
        import hashlib, os
        if not os.path.exists(file_path):
            return None
        h = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(chunk_size), b""):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return None

    @staticmethod
    async def verify_recording(db: AsyncSession, recording_id: str) -> dict:
        """Recompute SHA-256 of a recording and compare with stored checksum.
        Updates integrity_status: verified | corrupted | unchecked."""
        from sqlalchemy import text
        row = (await db.execute(
            text("SELECT id, file_path, checksum FROM recordings WHERE id = :id"),
            {"id": recording_id},
        )).fetchone()
        if not row:
            return {"recording_id": recording_id, "status": "not_found"}
        current = RecordingService.compute_sha256(row[1])
        if current is None:
            status = "missing_file"
        elif not row[2]:
            # No stored checksum (legacy row) — record it now.
            status = "verified"
            await db.execute(
                text("UPDATE recordings SET checksum=:c, integrity_status=:s WHERE id=:id"),
                {"c": current, "s": status, "id": recording_id},
            )
            await db.commit()
            return {"recording_id": recording_id, "status": status, "checksum": current}
        else:
            status = "verified" if current == row[2] else "corrupted"
        await db.execute(
            text("UPDATE recordings SET integrity_status=:s WHERE id=:id"),
            {"s": status, "id": recording_id},
        )
        await db.commit()
        return {
            "recording_id": recording_id,
            "status": status,
            "expected": row[2],
            "actual": current,
        }

    # ------------------------------------------------------------------
    # Available recording dates (for calendar widget)
    # ------------------------------------------------------------------

    @staticmethod
    async def available_dates(db: AsyncSession, camera_id: str) -> List[str]:
        """Return list of dates (YYYY-MM-DD) that have recordings."""
        result = await db.execute(
            select(func.date(Recording.start_time))
            .where(Recording.camera_id == camera_id)
            .group_by(func.date(Recording.start_time))
            .order_by(func.date(Recording.start_time).desc())
        )
        return [row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]) for row in result.fetchall()]

    @staticmethod
    async def get_latest_segment(db: AsyncSession, camera_id: str):
        """Return the most recently completed recording segment for a camera."""
        result = await db.execute(
            select(Recording)
            .where(Recording.camera_id == camera_id, Recording.end_time.is_not(None))
            .order_by(Recording.end_time.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
