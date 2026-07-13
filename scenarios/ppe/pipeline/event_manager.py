"""Event lifecycle — client-proven POC EventManager
(gvd_ppe_poc/utils/event_manager.py) ported, adapted to emit ACTIONS instead of doing
DB writes / disk I/O.

Converts frame-by-frame violations into enterprise lifecycle events keyed on the
worker's ReID identity (not the flapping ByteTrack id): OBSERVED → NEW → ACTIVE →
RESOLVED → EXPIRED. This prevents duplicate alerts from continuous detections and gives
one incident per real violation.

In the POC this class wrote to SQLite + saved evidence JPGs. In vizor the plugin SHELL
owns persistence (worker._emit_v2 → db.events.record_event) and snapshots, and the
processor must NOT do I/O. So this port keeps the exact state machine + timing
(VIOLATION_PERSISTENCE_FRAMES, EVENT_RESOLVE_AFTER_SECONDS, EVENT_EXPIRE_AFTER_SECONDS,
DUPLICATE_COOLDOWN_SECONDS) but, on each transition, returns an ACTION dict:
  * {"action":"create","violation_type","required_ppe","confidence","person_bbox"} when
    a violation first persists past VIOLATION_PERSISTENCE_FRAMES (→ INSERT one event);
  * {"action":"update","event_id","observation_count","duration_s","confidence"} while
    the same incident continues (→ UPDATE in place; the live worker no-ops this, the
    video job upserts — same split as today);
  * None otherwise.
RESOLVED / EXPIRED run purely IN-MEMORY (no vizor "resolved" column) to free the
incident and re-arm the DUPLICATE_COOLDOWN so a genuine re-offence fires a fresh event.

Uses a monotonic ``now`` (seconds, e.g. time.monotonic) supplied by the caller, matching
the rest of the vizor pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import config


@dataclass
class _EventMemory:
    key: Tuple[str, str, str]                 # (camera_id, identity, violation_type)
    event_id: Optional[str] = None            # vizor PPEEvent uuid once created
    first_seen: float = 0.0
    last_seen: float = 0.0
    observation_count: int = 0
    state: str = "OBSERVED"
    confidence: float = 0.0
    last_violation: Optional[Dict] = None
    cooldown_until: float = -1e12             # re-offence suppressed until this time


class EventManager:
    """POC EventManager state machine, emitting actions for the shell to persist."""

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.events: Dict[Tuple[str, str, str], _EventMemory] = {}

    def update(self, violations: List[Dict], now: float) -> Dict[Tuple[str, str, str], Dict]:
        """Feed this frame's confirmed violations (POC compliance dicts). Returns a map
        {event_key -> action dict} for keys that transitioned this frame."""
        seen_keys: set = set()
        actions: Dict[Tuple[str, str, str], Dict] = {}

        for v in violations:
            v["camera_id"] = self.camera_id
            identity_id = v.get("reid_global_id") or f"track_{v.get('track_id')}"
            key = (self.camera_id, identity_id, v["violation_type"])
            seen_keys.add(key)

            mem = self.events.get(key)
            if mem is None:
                mem = _EventMemory(key=key, first_seen=now, last_seen=now)
                self.events[key] = mem

            mem.last_seen = now
            mem.observation_count += 1
            mem.confidence = max(mem.confidence, float(v.get("confidence", 0.0)))
            mem.last_violation = v

            # CREATE — violation has persisted long enough, and not inside a cooldown.
            if (mem.event_id is None and mem.state in ("OBSERVED",)
                    and mem.observation_count >= config.VIOLATION_PERSISTENCE_FRAMES
                    and now >= mem.cooldown_until):
                mem.state = "NEW"
                actions[key] = {
                    "action": "create",
                    "violation_type": v["violation_type"],
                    "required_ppe": v.get("required_ppe"),
                    "confidence": mem.confidence,
                    "person_bbox": v.get("person_bbox"),
                }
            # ACTIVE — incident continues; the shell may upsert (video job) or no-op (live).
            elif mem.event_id is not None:
                mem.state = "ACTIVE"
                actions[key] = {
                    "action": "update",
                    "event_id": mem.event_id,
                    "observation_count": mem.observation_count,
                    "duration_s": max(0.0, now - mem.first_seen),
                    "confidence": mem.confidence,
                }

        # RESOLVE / EXPIRE incidents not seen this frame (in-memory only).
        for key, mem in list(self.events.items()):
            if key in seen_keys:
                continue
            missing_for = now - mem.last_seen
            if (mem.state in ("NEW", "ACTIVE")
                    and missing_for >= config.EVENT_RESOLVE_AFTER_SECONDS):
                mem.state = "RESOLVED"
                # Re-arm the duplicate cooldown so a genuine re-offence fires a fresh event.
                mem.cooldown_until = now + config.DUPLICATE_COOLDOWN_SECONDS
            if missing_for >= config.EVENT_EXPIRE_AFTER_SECONDS:
                self.events.pop(key, None)

        return actions

    def set_event_id(self, key: Tuple[str, str, str], event_id: str) -> None:
        mem = self.events.get(key)
        if mem is not None:
            mem.event_id = event_id
            mem.state = "ACTIVE"

    def purge(self, now: float) -> None:
        for key, mem in list(self.events.items()):
            if now - mem.last_seen >= config.EVENT_EXPIRE_AFTER_SECONDS:
                self.events.pop(key, None)
