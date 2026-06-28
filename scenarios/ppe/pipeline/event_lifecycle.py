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


@dataclass
class EventLifecycle:
    """One worker = one evolving incident; emit only on confirmed status transitions.

    enter_frames: how many consecutive frames a NEW status must hold before it commits
                  (absorbs a 1-2 frame blink). expire_s: drop a worker not seen this long.
    """
    enter_frames: int = 3
    expire_s: float = 8.0
    _state: dict = field(default_factory=dict)        # gid -> _WorkerState

    def update(self, gid, *, compliant: bool, missing, now: float):
        """Feed one worker's current-frame verdict. Returns an event dict to emit, or None.

        event dict: {"type": "compliant"|"violation", "missing": [...]}
        Only returned on a CONFIRMED transition (status actually changed)."""
        st = self._state.get(gid)
        if st is None:
            st = _WorkerState()
            self._state[gid] = st
        st.last_seen = now
        miss = tuple(missing or ())

        # has the candidate changed from what's pending?
        if st.pending is None or st.pending != compliant or st.pending_missing != miss:
            st.pending = compliant
            st.pending_missing = miss
            st.pending_count = 1
        else:
            st.pending_count += 1

        # commit the pending status once it has persisted enough frames AND it differs
        # from the currently committed status — that's the transition we emit on.
        if st.pending_count >= self.enter_frames:
            changed = (st.status != st.pending) or (
                st.pending is False and st.missing != st.pending_missing)
            if changed:
                st.status = st.pending
                st.missing = st.pending_missing
                if st.status:
                    return {"type": "compliant", "missing": []}
                return {"type": "violation", "missing": list(st.missing)}
        return None

    def purge(self, now: float):
        """Drop workers not seen recently (incident closed / left frame)."""
        for gid in [g for g, s in self._state.items() if now - s.last_seen > self.expire_s]:
            self._state.pop(gid, None)
