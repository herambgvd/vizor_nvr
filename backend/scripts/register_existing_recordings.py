#!/usr/bin/env python3
"""
Scan for existing recording files on disk and register any that are missing
from the database. Useful for backfilling segments that were written but
never registered (e.g. after a registration bug).

Run from the backend directory:
    python scripts/register_existing_recordings.py
"""

import asyncio
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.database import async_session_maker
from sqlalchemy import text

# Leading timestamp in segment filenames: 20260529_154723[...].mp4
# Anything after the second-resolution stamp (e.g. a stray "_%f") is ignored.
_TS_RE = re.compile(r"^(\d{8}_\d{6})")


async def probe_duration(path: str) -> int:
    """Get duration of a video file using ffprobe. Returns 0 on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        return int(float(stdout.decode().strip()))
    except Exception:
        return 0


def parse_start_time(filename: str):
    """Parse the naive-UTC start time from a segment filename, or None."""
    m = _TS_RE.match(filename)
    if not m:
        return None
    try:
        # Stored naive; UTC by convention (matches recordings.start_time column).
        return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
    except ValueError:
        return None


async def register_recordings():
    recordings_dir = Path(settings.STORAGE_PATH)

    if not recordings_dir.exists():
        print(f"Recordings directory not found: {recordings_dir}")
        return

    print(f"Scanning: {recordings_dir}")
    registered = 0
    skipped = 0
    invalid = 0

    async with async_session_maker() as db:
        for camera_dir in sorted(recordings_dir.iterdir()):
            if not camera_dir.is_dir():
                continue

            camera_id = camera_dir.name
            print(f"\nCamera: {camera_id}")

            for mp4_file in sorted(camera_dir.glob("*.mp4")):
                result = await db.execute(
                    text("SELECT id FROM recordings WHERE file_path = :path"),
                    {"path": str(mp4_file)},
                )
                if result.scalar_one_or_none():
                    skipped += 1
                    continue

                start_time = parse_start_time(mp4_file.name)
                if start_time is None:
                    print(f"  ! Unparseable filename, skipping: {mp4_file.name}")
                    invalid += 1
                    continue

                file_size = mp4_file.stat().st_size
                if file_size < 10240:
                    print(f"  - Empty/corrupt, skipping: {mp4_file.name} ({file_size} bytes)")
                    invalid += 1
                    continue

                duration = await probe_duration(str(mp4_file))
                end_time = start_time + timedelta(seconds=duration) if duration else None

                rec_id = str(uuid.uuid4())
                await db.execute(
                    text("""
                        INSERT INTO recordings (id, camera_id, file_path, start_time, end_time,
                                                duration, file_size, stream_type, trigger_type, locked)
                        VALUES (:id, :camera_id, :file_path, :start_time, :end_time,
                                :duration, :file_size, :stream_type, :trigger_type, :locked)
                    """),
                    {
                        "id": rec_id,
                        "camera_id": camera_id,
                        "file_path": str(mp4_file),
                        "start_time": start_time,
                        "end_time": end_time,
                        "duration": duration,
                        "file_size": file_size,
                        "stream_type": "main",
                        "trigger_type": "continuous",
                        "locked": False,
                    },
                )
                print(f"  + Registered: {mp4_file.name} ({duration}s, {file_size / 1_048_576:.1f} MB)")
                registered += 1

        await db.commit()

    print(f"\n✓ Done. Registered: {registered}, Already present: {skipped}, Invalid: {invalid}")


if __name__ == "__main__":
    asyncio.run(register_recordings())
