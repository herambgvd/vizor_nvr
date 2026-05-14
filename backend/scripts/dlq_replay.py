#!/usr/bin/env python3
"""
DLQ Replay CLI — inspect and replay events stuck in the Metropolis bridge
dead-letter queue.

The Metropolis bridge writes failed events to a Redis Stream
(METROPOLIS_DLQ_STREAM, default "metropolis:events:dlq") after exhausting
retries. This CLI lets ops:

  - list      Show DLQ entries (id, reason, payload preview)
  - inspect   Pretty-print one entry by id
  - replay    Re-publish payload to the main stream so the bridge picks
              it up again. Optional filter by reason or id range.
  - purge     Remove a DLQ entry (e.g. after manual fix).
  - clear     Remove all DLQ entries (irreversible, asks for confirmation).

Usage:
  python scripts/dlq_replay.py list [--limit N]
  python scripts/dlq_replay.py inspect <entry_id>
  python scripts/dlq_replay.py replay <entry_id|--reason X|--all>
  python scripts/dlq_replay.py purge <entry_id>
  python scripts/dlq_replay.py clear --yes

Env:
  METROPOLIS_REDIS_URL    default redis://redis:6379/0
  METROPOLIS_STREAM       default "metropolis:events"
  METROPOLIS_DLQ_STREAM   default "metropolis:events:dlq"
"""

import argparse
import asyncio
import json
import os
import sys
from typing import Any

import redis.asyncio as aioredis


REDIS_URL = os.environ.get("METROPOLIS_REDIS_URL", "redis://redis:6379/0")
MAIN_STREAM = os.environ.get("METROPOLIS_STREAM", "metropolis:events")
DLQ_STREAM = os.environ.get("METROPOLIS_DLQ_STREAM", "metropolis:events:dlq")


def _truncate(s: Any, n: int = 80) -> str:
    txt = str(s)
    return txt if len(txt) <= n else txt[: n - 1] + "…"


async def cmd_list(r: aioredis.Redis, limit: int) -> int:
    entries = await r.xrevrange(DLQ_STREAM, count=limit)
    if not entries:
        print(f"(DLQ {DLQ_STREAM} is empty)")
        return 0
    print(f"{'Entry ID':<25}  {'Reason':<20}  Payload preview")
    print("-" * 100)
    for entry_id, data in entries:
        reason = data.get("reason", "?")
        payload = data.get("payload", "")
        print(f"{entry_id:<25}  {reason:<20}  {_truncate(payload, 60)}")
    print(f"\n{len(entries)} entries shown")
    return 0


async def cmd_inspect(r: aioredis.Redis, entry_id: str) -> int:
    entries = await r.xrange(DLQ_STREAM, min=entry_id, max=entry_id, count=1)
    if not entries:
        print(f"Entry {entry_id} not found")
        return 1
    _, data = entries[0]
    print(f"Entry: {entry_id}")
    print(f"Reason: {data.get('reason', '?')}")
    print(f"Timestamp: {data.get('ts', '?')}")
    print(f"Original ID: {data.get('original_id', '?')}")
    print("\nPayload:")
    payload = data.get("payload", "{}")
    try:
        print(json.dumps(json.loads(payload), indent=2))
    except (ValueError, TypeError):
        print(payload)
    return 0


async def cmd_replay(
    r: aioredis.Redis,
    entry_id: str | None,
    reason_filter: str | None,
    replay_all: bool,
) -> int:
    # Resolve which entries to replay
    if entry_id:
        entries = await r.xrange(DLQ_STREAM, min=entry_id, max=entry_id, count=1)
    elif replay_all or reason_filter:
        entries = await r.xrange(DLQ_STREAM, count=10_000)
        if reason_filter:
            entries = [(eid, d) for eid, d in entries if d.get("reason") == reason_filter]
    else:
        print("Specify <entry_id>, --reason X, or --all")
        return 2

    if not entries:
        print("No entries match")
        return 0

    print(f"Replaying {len(entries)} entries to {MAIN_STREAM}…")
    replayed = 0
    failed = 0
    for eid, data in entries:
        payload = data.get("payload")
        if not payload:
            print(f"  {eid} — skipped (empty payload)")
            failed += 1
            continue
        try:
            # Re-publish as {payload: <original json>} so bridge decodes it
            # the same way as a fresh nvmsgbroker event.
            await r.xadd(MAIN_STREAM, {"payload": payload})
            # Remove from DLQ once replayed so we don't loop on it
            await r.xdel(DLQ_STREAM, eid)
            replayed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  {eid} — replay failed: {e}")
            failed += 1

    print(f"Done. Replayed: {replayed}, failed: {failed}")
    return 0 if failed == 0 else 1


async def cmd_purge(r: aioredis.Redis, entry_id: str) -> int:
    deleted = await r.xdel(DLQ_STREAM, entry_id)
    if deleted == 0:
        print(f"Entry {entry_id} not found")
        return 1
    print(f"Deleted {entry_id} from {DLQ_STREAM}")
    return 0


async def cmd_clear(r: aioredis.Redis) -> int:
    count = await r.xlen(DLQ_STREAM)
    if count == 0:
        print("DLQ already empty")
        return 0
    await r.delete(DLQ_STREAM)
    print(f"Cleared {count} entries from {DLQ_STREAM}")
    return 0


async def main_async(args: argparse.Namespace) -> int:
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        if args.cmd == "list":
            return await cmd_list(r, args.limit)
        if args.cmd == "inspect":
            return await cmd_inspect(r, args.entry_id)
        if args.cmd == "replay":
            return await cmd_replay(r, args.entry_id, args.reason, args.all)
        if args.cmd == "purge":
            return await cmd_purge(r, args.entry_id)
        if args.cmd == "clear":
            if not args.yes:
                print("clear is destructive. Re-run with --yes to confirm.")
                return 2
            return await cmd_clear(r)
        return 2
    finally:
        await r.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Metropolis bridge DLQ replay tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List DLQ entries")
    p_list.add_argument("--limit", type=int, default=50)

    p_inspect = sub.add_parser("inspect", help="Pretty-print one DLQ entry")
    p_inspect.add_argument("entry_id")

    p_replay = sub.add_parser("replay", help="Replay DLQ entry(ies) to main stream")
    p_replay.add_argument("entry_id", nargs="?")
    p_replay.add_argument("--reason", help="Replay all entries with this reason")
    p_replay.add_argument("--all", action="store_true", help="Replay every entry")

    p_purge = sub.add_parser("purge", help="Delete one DLQ entry without replaying")
    p_purge.add_argument("entry_id")

    p_clear = sub.add_parser("clear", help="Delete entire DLQ")
    p_clear.add_argument("--yes", action="store_true", required=False)

    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
