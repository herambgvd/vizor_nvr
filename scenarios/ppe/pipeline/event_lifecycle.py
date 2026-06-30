"""Event lifecycle — ported from the AI-Powered PPE Detection System's EventManager,
adapted to vizor + the client's state-transition requirement.

Problem it solves: detecting per-frame produced one event per frame for the same worker
(worker #98862 appearing dozens of times seconds apart). The client wants ONE event per
real state change instead:
  worker enters wearing helmet+vest      → 1 COMPLIANT event
  ...stays compliant...                  → no events
  helmet removed 10s later               → 1 "no helmet" VIOLATION event
  ...stays non-compliant...              → no events
  helmet put back on                     → 1 COMPLIANT event
  worker leaves                          → incident closed

So events fire only on a CONFIRMED transition of a worker's compliance status, keyed by
the worker's stable Re-ID identity (not the flickering ByteTrack id). A short persistence
(`enter_frames`) before a transition commits absorbs detection blinks.

This is a pure state machine: the caller feeds it, per frame, each worker's current
worn/missing set; it returns the events to emit (with the snapshot/bbox the caller then
records). No I/O here.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _WorkerState:
    # committed status: True=compliant, False=violation, None=not yet decided
    status: bool | None = None
    missing: tuple = ()                 # committed missing items (canonical) when violation
    # pending (candidate) status awaiting persistence frames before it commits
    pending: bool | None = None
    pending_missing: tuple = ()
    pending_count: int = 0
    last_seen: float = 0.0
    # last time we EMITTED each event kind for this worker — for duplicate suppression
    last_emit: dict = field(default_factory=dict)   # "compliant"/("violation",miss) -> ts
    # the DB event id + first-seen of the CURRENTLY-active incident, so the caller can
    # UPDATE that row (AI-Powered upsert) instead of inserting a new one each frame.
    active_event_id: str | None = None
    active_kind = None
    active_since: float = 0.0
    obs_count: int = 0


@dataclass
class EventLifecycle:
    """One worker = one evolving incident; emit only on confirmed status transitions.

    enter_frames: how many consecutive frames a NEW status must hold before it commits
                  (absorbs a 1-2 frame blink). expire_s: drop a worker not seen this long.
    """
    enter_frames: int = 3
    expire_s: float = 8.0
    dup_cooldown_s: float = 30.0      # same worker+kind not re-emitted within this window
    _state: dict = field(default_factory=dict)        # gid -> _WorkerState

    def update(self, gid, *, compliant: bool, missing, now: float):
        """Feed one worker's current-frame verdict. Returns one of:
          {"action":"create","type":...,"missing":[...]}  → caller inserts a NEW event,
              then calls set_event_id(gid, new_id) so future frames UPDATE that row.
          {"action":"update","event_id":id,"obs_count":n,"duration_s":s} → caller UPDATES
              the existing incident row in place (AI-Powered upsert; no new row).
          None → nothing to do this frame.
        One incident per worker-status; a confirmed status transition opens a new incident."""
        st = self._state.get(gid)
        if st is None:
            st = _WorkerState()
            self._state[gid] = st
        st.last_seen = now
        miss = tuple(missing or ())

        # candidate (pending) status — persist enter_frames before committing (blink absorb).
        # Debounce on the BOOLEAN compliance status only. Resetting the counter whenever the
        # exact missing-item SET changed meant a worker whose missing set flickered between
        # e.g. {Hardhat} and {Hardhat, Safety_Vest} never reached enter_frames → the
        # violation NEVER committed (observed at SMCC). Now the counter only resets on a
        # status flip (compliant<->violation); the missing set just settles in place and we
        # take the most-recent set at commit time.
        if st.pending is None or st.pending != compliant:
            st.pending = compliant
            st.pending_missing = miss
            st.pending_count = 1
        else:
            st.pending_missing = miss   # keep the latest missing set without resetting count
            st.pending_count += 1

        if st.pending_count >= self.enter_frames:
            changed = (st.status != st.pending) or (
                st.pending is False and st.missing != st.pending_missing)
            if changed:
                # CONFIRMED transition → close the old incident, open a new one.
                st.status = st.pending
                st.missing = st.pending_missing
                kind = "compliant" if st.status else ("violation", st.missing)
                last = st.last_emit.get(kind, -1e12)
                st.active_event_id = None
                st.active_kind = kind
                st.active_since = now
                st.obs_count = 1
                if now - last < self.dup_cooldown_s:
                    return None    # suppressed duplicate — no new incident row
                st.last_emit[kind] = now
                if st.status:
                    return {"action": "create", "type": "compliant", "missing": []}
                return {"action": "create", "type": "violation", "missing": list(st.missing)}

        # same committed status continues → UPDATE the active incident row, not a new one.
        if st.active_event_id is not None:
            st.obs_count += 1
            return {"action": "update", "event_id": st.active_event_id,
                    "obs_count": st.obs_count, "duration_s": now - st.active_since}
        return None

    def set_event_id(self, gid, event_id: str) -> None:
        """Caller reports the DB id of the row it just inserted for this worker's current
        incident, so subsequent frames update that row instead of inserting."""
        st = self._state.get(gid)
        if st is not None:
            st.active_event_id = event_id

    def purge(self, now: float):
        """Drop workers not seen recently (incident closed / left frame)."""
        for gid in [g for g, s in self._state.items() if now - s.last_seen > self.expire_s]:
            self._state.pop(gid, None)
