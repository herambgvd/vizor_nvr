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
        """Resolve votes to `(person_id|None, avg_score, rep_embedding, name)`."""
        entry = self._votes.get((camera_id, int(track_id)))
        if entry is None or not entry["votes"]:
            return None
        votes = entry["votes"]

        groups: dict[str | None, list] = {}
        for pid, score, emb, name in votes:
            groups.setdefault(pid, []).append((score, emb, name))

        def _rank(item):
            pid, members = item
            return (
                len(members),
                sum(s for s, _, _ in members) / max(len(members), 1),
            )

        winner_pid, winner_members = max(groups.items(), key=_rank)
        winner_count = len(winner_members)
        total = len(votes)

        is_real_person = winner_pid is not None
        # Require at least 2 corroborating votes for an identity — a single
        # vote being a "majority" of 1 total is not evidence (one stray frame
        # could mis-bind a track to a wrong person). Majority only helps
        # once there are ≥2 votes total.
        is_majority = total >= 2 and winner_count * 2 > total
        accept_person = is_real_person and (winner_count >= 2 or is_majority)

        if accept_person:
            avg_score = sum(s for s, _, _ in winner_members) / winner_count
            best = max(winner_members, key=lambda m: m[0])
            _, rep_emb, rep_name = best
            return winner_pid, float(avg_score), rep_emb, rep_name

        unknown_members = groups.get(None, [])
        if unknown_members:
            avg_score = sum(s for s, _, _ in unknown_members) / len(unknown_members)
            best = max(unknown_members, key=lambda m: m[0])
            _, rep_emb, _ = best
            return None, float(avg_score), rep_emb, None

        score, rep_emb, _name = max(
            ((s, e, n) for pid, members in groups.items() for s, e, n in members),
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
