"""Track-based recognition consensus voting.

Ported from portal/common/frs_orch/processors/frs.py — track vote buffers,
consensus resolver, GC. Pure in-process state, no Redis dependency.
"""
from __future__ import annotations

import time

import numpy as np


TRACK_VOTE_MIN_FRAMES = 5
TRACK_VOTE_MAX_SECS = 2.5
TRACK_VOTE_TTL = 6.0
TRACK_STATE_TTL = 60.0

import os as _os

# Quality-weighted consensus bars (cosine similarity of the per-frame match).
# A person vote only exists if that frame already cleared the camera's
# min_confidence in _match_vector, so these gate how much corroboration the
# consensus needs:
#   STRONG — one frame this confident is enough on its own (a clean look beats
#            any number of weak/unknown frames from a steep angle).
#   NORMAL — a weaker frame needs a second frame above this to be accepted.
STRONG_VOTE_SCORE = float(_os.getenv("FRS_STRONG_VOTE_SCORE", "0.55"))
NORMAL_VOTE_SCORE = float(_os.getenv("FRS_NORMAL_VOTE_SCORE", "0.40"))


class TrackVoteBuffer:
    """Per-camera track vote buffers + post-fire track state, with GC."""

    def __init__(
        self,
        min_frames: int = TRACK_VOTE_MIN_FRAMES,
        max_secs: float = TRACK_VOTE_MAX_SECS,
        vote_ttl: float = TRACK_VOTE_TTL,
        state_ttl: float = TRACK_STATE_TTL,
    ):
        self.min_frames = min_frames
        self.max_secs = max_secs
        self.vote_ttl = vote_ttl
        self.state_ttl = state_ttl

        # (camera_id, track_id) -> {"votes": [...], "first_ts": float, "last_ts": float}
        self._votes: dict[tuple[str, int], dict] = {}
        # (camera_id, track_id) -> {"status", "person_id", "person_name", "score", ...}
        self._state: dict[tuple[str, int], dict] = {}

    # ── Votes ──────────────────────────────────────────────────────────────

    def record(
        self,
        camera_id: str,
        track_id: int,
        person_id: str | None,
        score: float,
        embedding: np.ndarray,
        person_name: str | None,
        now_ts: float | None = None,
    ) -> None:
        now_ts = now_ts if now_ts is not None else time.time()
        key = (camera_id, int(track_id))
        entry = self._votes.get(key)
        if entry is None:
            entry = {"votes": [], "first_ts": now_ts, "last_ts": now_ts}
            self._votes[key] = entry
        entry["votes"].append((person_id, float(score), embedding, person_name))
        entry["last_ts"] = now_ts

    def count(self, camera_id: str, track_id: int) -> int:
        entry = self._votes.get((camera_id, int(track_id)))
        return len(entry["votes"]) if entry else 0

    def should_fire(
        self, camera_id: str, track_id: int, now_ts: float | None = None,
        min_frames: int | None = None,
    ) -> bool:
        entry = self._votes.get((camera_id, int(track_id)))
        if entry is None:
            return False
        now_ts = now_ts if now_ts is not None else time.time()
        min_frames = self.min_frames if min_frames is None else min_frames
        n = len(entry["votes"])
        if n >= min_frames:
            return True
        if n >= 2 and (now_ts - entry["first_ts"]) >= self.max_secs:
            return True
        return False

    def consensus(
        self, camera_id: str, track_id: int,
    ) -> tuple[str | None, float, np.ndarray, str | None] | None:
        """Resolve votes to `(person_id|None, score, rep_embedding, name)`.

        QUALITY-WEIGHTED, not raw count. The old resolver ranked groups by vote
        COUNT first, so on a top-down/angled camera where most frames produce a
        weak/garbage embedding (which Qdrant returns as an Unknown vote), a handful
        of unknown votes out-voted the one or two clean frames that genuinely
        matched a person — the camera reported Unknown even when the person was
        clearly recognised in those clean frames. This is exactly the failure
        enterprise FRS avoids by fusing the best evidence rather than counting
        frames.

        New rule: a person is accepted when at least ONE vote for them clears a
        strong-evidence bar (score >= STRONG_VOTE_SCORE) OR at least two votes for
        them clear the normal match threshold. A strong single match beats any
        number of unknowns; weak single matches still need corroboration so a stray
        mis-bind can't fire. The returned score is the BEST (not averaged) so a
        clean frame isn't dragged down by the noisy ones in the same track."""
        entry = self._votes.get((camera_id, int(track_id)))
        if entry is None or not entry["votes"]:
            return None
        votes = entry["votes"]

        groups: dict[str | None, list] = {}
        for pid, score, emb, name in votes:
            groups.setdefault(pid, []).append((score, emb, name))

        # Person groups only (drop the None/unknown bucket from the contest).
        person_groups = {pid: m for pid, m in groups.items() if pid is not None}

        best_pid = None
        best_member = None
        for pid, members in person_groups.items():
            top = max(members, key=lambda m: m[0])           # best frame for this person
            n_strong = sum(1 for s, _, _ in members if s >= STRONG_VOTE_SCORE)
            n_ok = sum(1 for s, _, _ in members if s >= NORMAL_VOTE_SCORE)
            # Accept on one strong match, or two normal matches.
            if n_strong >= 1 or n_ok >= 2:
                if best_member is None or top[0] > best_member[0]:
                    best_pid, best_member = pid, top

        if best_pid is not None and best_member is not None:
            score, rep_emb, rep_name = best_member
            return best_pid, float(score), rep_emb, rep_name

        # No accepted person → report the strongest evidence as Unknown (for the
        # event snapshot / debugging), preferring the unknown bucket's best frame.
        unknown_members = groups.get(None, [])
        if unknown_members:
            best = max(unknown_members, key=lambda m: m[0])
            score, rep_emb, _ = best
            return None, float(score), rep_emb, None

        score, rep_emb, _name = max(
            ((s, e, n) for members in groups.values() for s, e, n in members),
            key=lambda m: m[0],
        )
        return None, float(score), rep_emb, None

    def clear(self, camera_id: str, track_id: int) -> None:
        self._votes.pop((camera_id, int(track_id)), None)

    # ── Post-fire track state ──────────────────────────────────────────────

    def state(self, camera_id: str, track_id: int) -> dict | None:
        return self._state.get((camera_id, int(track_id)))

    def set_state(
        self,
        camera_id: str,
        track_id: int,
        status: str,
        person_id: str | None,
        person_name: str | None,
        score: float,
        now_ts: float | None = None,
    ) -> None:
        now_ts = now_ts if now_ts is not None else time.time()
        self._state[(camera_id, int(track_id))] = {
            "status": status,
            "person_id": person_id,
            "person_name": person_name,
            "score": float(score),
            "fired_at": now_ts,
            "last_seen_ts": now_ts,
        }

    def touch_state(self, camera_id: str, track_id: int, now_ts: float | None = None) -> None:
        st = self._state.get((camera_id, int(track_id)))
        if st:
            st["last_seen_ts"] = now_ts if now_ts is not None else time.time()

    # ── GC ─────────────────────────────────────────────────────────────────

    def gc(self, now_ts: float | None = None) -> None:
        now_ts = now_ts if now_ts is not None else time.time()
        if self._votes:
            stale = [k for k, v in self._votes.items() if (now_ts - v["last_ts"]) > self.vote_ttl]
            for k in stale:
                self._votes.pop(k, None)
        if self._state:
            stale = [k for k, v in self._state.items() if (now_ts - v.get("last_seen_ts", 0)) > self.state_ttl]
            for k in stale:
                self._state.pop(k, None)
