#!/usr/bin/env python3
"""
Inject synthetic Metropolis events into the Redis Stream the bridge
consumes. Use for:

  - Smoke-testing the bridge → /api/events/ingest path without a real
    Perception Microservice running (i.e. RTX 4050 dev machine).
  - Load-testing the bridge under bursty conditions.
  - Reproducing customer issues from a saved event trace.

Usage:
  python scripts/inject_test_events.py \\
      --count 50 \\
      --scenario frs \\
      --camera-id 69f0bd47919e7a382375ce2b

  python scripts/inject_test_events.py \\
      --count 200 \\
      --scenario people_counting \\
      --rps 10

Reads existing camera IDs from Postgres when --camera-id not specified.

Env:
  METROPOLIS_REDIS_URL    default redis://redis:6379/0
  METROPOLIS_STREAM       default "metropolis:events"
"""

import argparse
import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from typing import List

import redis.asyncio as aioredis

# Make `app` importable when invoked as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import async_session_maker  # noqa: E402
from sqlalchemy import text  # noqa: E402


REDIS_URL = os.environ.get("METROPOLIS_REDIS_URL", "redis://redis:6379/0")
STREAM = os.environ.get("METROPOLIS_STREAM", "metropolis:events")


# ---------------------------------------------------------------------------
# Event factories — one per scenario. Match the schema the bridge
# translator (`metropolis_to_ingest_event`) understands.
# ---------------------------------------------------------------------------


def _now_ms() -> int:
    return int(time.time() * 1000)


def make_frs_event(camera_id: str, idx: int) -> dict:
    """Face Match or Face Detected event."""
    # 30% chance the face matches an enrolled person
    is_match = random.random() < 0.3
    return {
        "sensorId": camera_id,
        "timestamp": _now_ms(),
        "type": "FaceMatch" if is_match else "FaceDetected",
        "analyticsModule": "frs",
        "confidence": round(random.uniform(0.55, 0.99), 3),
        "personId": f"test-person-{random.randint(1, 5)}" if is_match else None,
        "object": {
            "id": f"track-{idx}-{random.randint(100, 999)}",
            "bbox": [
                random.randint(50, 800),
                random.randint(50, 600),
                random.randint(60, 200),
                random.randint(80, 240),
            ],
            "confidence": round(random.uniform(0.55, 0.99), 3),
        },
    }


def make_people_counting_event(camera_id: str, idx: int) -> dict:
    """Person count / line crossing / overcrowding events."""
    event_types = ["PersonDetected", "LineCrossing", "Overcrowding"]
    weights = [0.6, 0.3, 0.1]
    et = random.choices(event_types, weights=weights, k=1)[0]
    payload = {
        "sensorId": camera_id,
        "timestamp": _now_ms(),
        "type": et,
        "analyticsModule": "people_counting",
        "object": {
            "id": f"track-{idx}",
            "bbox": [
                random.randint(50, 800),
                random.randint(50, 600),
                random.randint(40, 100),
                random.randint(100, 200),
            ],
            "confidence": round(random.uniform(0.5, 0.95), 3),
        },
        "attributes": {},
    }
    if et == "LineCrossing":
        payload["attributes"] = {
            "line_id": 0,
            "direction": random.choice(["in", "out"]),
        }
    elif et == "Overcrowding":
        payload["attributes"] = {
            "zone_id": 0,
            "occupancy": random.randint(10, 30),
        }
    return payload


FACTORIES = {
    "frs": make_frs_event,
    "people_counting": make_people_counting_event,
}


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


async def _resolve_camera_ids() -> List[str]:
    """Pull camera IDs from Postgres so injected events FK-link cleanly."""
    async with async_session_maker() as db:
        result = await db.execute(text("SELECT id FROM cameras LIMIT 50"))
        return [row[0] for row in result.fetchall()]


# ---------------------------------------------------------------------------
# Injection loop
# ---------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    if args.scenario not in FACTORIES:
        print(f"Unknown scenario: {args.scenario}. Choices: {list(FACTORIES)}")
        return 1

    # Resolve camera IDs
    if args.camera_id:
        camera_ids = [args.camera_id]
    else:
        camera_ids = await _resolve_camera_ids()
        if not camera_ids:
            print(
                "No cameras in Postgres — pass --camera-id explicitly or "
                "add a camera via NVR UI first."
            )
            return 1
        print(f"Spreading events across {len(camera_ids)} cameras")

    factory = FACTORIES[args.scenario]
    r = aioredis.from_url(REDIS_URL, decode_responses=True)

    sleep_per_event = 1.0 / args.rps if args.rps > 0 else 0
    sent = 0
    start = time.monotonic()

    try:
        for i in range(args.count):
            cam = random.choice(camera_ids)
            payload = factory(cam, i)
            await r.xadd(STREAM, {"payload": json.dumps(payload)})
            sent += 1

            if sent % 50 == 0:
                elapsed = time.monotonic() - start
                rate = sent / elapsed if elapsed > 0 else 0
                print(f"  Sent {sent}/{args.count}  ({rate:.1f} ev/s)")

            if sleep_per_event > 0:
                await asyncio.sleep(sleep_per_event)
    finally:
        await r.aclose()

    elapsed = time.monotonic() - start
    print(
        f"\nDone. {sent} events injected to {STREAM} in {elapsed:.1f}s "
        f"({sent / elapsed:.1f} ev/s)"
    )
    print(f"Bridge should pick them up within {args.count // 50 + 2}s")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject synthetic Metropolis events for bridge testing")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument(
        "--scenario",
        default="frs",
        help=f"Event factory: {','.join(FACTORIES.keys())}",
    )
    parser.add_argument(
        "--camera-id",
        help="Pin all events to one camera. Default: spread across all cameras in Postgres.",
    )
    parser.add_argument(
        "--rps",
        type=float,
        default=0,
        help="Throttle to N events/sec. 0 = no throttle.",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
