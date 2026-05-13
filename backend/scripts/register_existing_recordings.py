#!/usr/bin/env python3
"""
Script to scan for existing recording files and register them in the database.
Run from backend directory: python scripts/register_existing_recordings.py
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import async_session_maker
from sqlalchemy import text


async def probe_duration(path: str) -> int:
    """Get duration of video file using ffprobe."""
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


async def register_recordings():
    recordings_dir = Path(__file__).parent.parent / "data" / "recordings"
    
    if not recordings_dir.exists():
        print(f"Recordings directory not found: {recordings_dir}")
        return
    
    registered = 0
    skipped = 0
    
    async with async_session_maker() as db:
        # Scan each camera directory
        for camera_dir in recordings_dir.iterdir():
            if not camera_dir.is_dir():
                continue
            
            camera_id = camera_dir.name
            print(f"\nScanning camera: {camera_id}")
            
            # Scan MP4 files
            for mp4_file in camera_dir.glob("*.mp4"):
                # Check if already registered
                result = await db.execute(
                    text("SELECT id FROM recordings WHERE file_path = :path"),
                    {"path": str(mp4_file)}
                )
                if result.scalar_one_or_none():
                    print(f"  Already registered: {mp4_file.name}")
                    skipped += 1
                    continue
                
                # Parse timestamp from filename: 20260309_204628.mp4
                try:
                    ts_str = mp4_file.stem
                    start_time = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
                except ValueError:
                    print(f"  Invalid filename format: {mp4_file.name}")
                    continue
                
                # Get file info
                file_size = mp4_file.stat().st_size
                duration = await probe_duration(str(mp4_file))
                end_time = start_time + timedelta(seconds=duration) if duration else None
                
                # Insert using raw SQL to avoid ORM import issues
                rec_id = str(uuid.uuid4())
                await db.execute(
                    text("""
                        INSERT INTO recordings (id, camera_id, file_path, start_time, end_time, duration, 
                                                file_size, stream_type, codec, trigger_type, locked)
                        VALUES (:id, :camera_id, :file_path, :start_time, :end_time, :duration, 
                                :file_size, :stream_type, :codec, :trigger_type, :locked)
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
                        "codec": "h264",
                        "trigger_type": "continuous",
                        "locked": False
                    }
                )
                print(f"  Registered: {mp4_file.name} ({duration}s, {file_size / 1_048_576:.1f} MB)")
                registered += 1
        
        await db.commit()
    
    print(f"\n✓ Done! Registered: {registered}, Skipped: {skipped}")


if __name__ == "__main__":
    asyncio.run(register_recordings())
