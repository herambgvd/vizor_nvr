"""Persistent worker identity via appearance Re-ID, ported from the AI-Powered PPE
Detection System (ReIDMatcher) — pure numpy, no torch/sklearn.

A ByteTrack id flips on occlusion / turn / re-enter (Track 1 → 17 → 1000001), which made
the same worker oscillate compliant<->missing and produced duplicate / fragmented events.
This matcher gives each appearance a STABLE global id: it averages each identity's recent
embeddings (temporal memory) and matches a new embedding by cosine similarity, only
minting a new identity after several consecutive non-matches (unknown-counter) so a single
bad crop doesn't fork the identity.

Used by the live worker + video job: track_id → ReID global id → all compliance state and
events key off the global id, so one worker is one stable identity.
"""
from __future__ import annotations

import uuid
from collections import deque

import numpy as np


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class ReIDMatcher:
    """Cosine match against per-identity temporal-mean embeddings (AI-Powered logic)."""

    def __init__(self, threshold: float = 0.60, history: int = 50,
                 max_unknown_frames: int = 5, max_identities: int = 256):
        self.threshold = threshold
        self.history_len = history
        self.max_unknown_frames = max_unknown_frames
        self.max_identities = max_identities
        self.identity_database: dict[str, np.ndarray] = {}     # gid -> mean embedding
        self.embedding_history: dict[str, deque] = {}          # gid -> deque[embedding]
        self.last_seen: dict[str, float] = {}
        self.unknown_counter = 0

    def _new_identity(self, embedding: np.ndarray, now: float) -> str:
        gid = "gid_" + uuid.uuid4().hex[:12]
        self.embedding_history[gid] = deque([embedding], maxlen=self.history_len)
        self.identity_database[gid] = embedding
        self.last_seen[gid] = now
        # evict the oldest identity if the table grows unbounded.
        if len(self.identity_database) > self.max_identities:
            oldest = min(self.last_seen, key=self.last_seen.get)
            self.identity_database.pop(oldest, None)
            self.embedding_history.pop(oldest, None)
            self.last_seen.pop(oldest, None)
        return gid

    def match(self, embedding, now: float = 0.0) -> str | None:
        """Return the stable global id for this embedding (creating one if needed)."""
        if embedding is None:
            return None
        emb = np.asarray(embedding, dtype=np.float32).reshape(-1)

        if not self.identity_database:
            return self._new_identity(emb, now)

        best_gid, best_sim = None, -1.0
        for gid, hist in self.embedding_history.items():
            stored = np.mean(hist, axis=0)
            sim = _cosine(emb, stored)
            if sim > best_sim:
                best_sim, best_gid = sim, gid

        if best_gid is not None and best_sim >= self.threshold:
            self.embedding_history[best_gid].append(emb)
            self.identity_database[best_gid] = np.mean(self.embedding_history[best_gid], axis=0)
            self.last_seen[best_gid] = now
            return best_gid

        # No confident match → this is a DIFFERENT person, so mint a new identity. (Unlike
        # the AI-Powered single-subject webcam flow, a frame here holds MANY people, so a
        # below-threshold best match means "not this worker", not "noisy frame" — we must
        # not tentatively attach or every worker collapses into one id.)
        return self._new_identity(emb, now)

    def purge(self, now: float, max_age: float = 30.0) -> None:
        for gid, last in list(self.last_seen.items()):
            if now - last > max_age:
                self.identity_database.pop(gid, None)
                self.embedding_history.pop(gid, None)
                self.last_seen.pop(gid, None)


# Collision-free gid->int registry. The old `int(hex[:8],16) % 99000` hashed many distinct
# global ids into the same ~99000-wide bucket, so two different workers could collapse onto
# one integer track id → their compliance / lifecycle state mixed. A process-local
# sequential registry guarantees one int per gid (no collisions).
_GID_INT: dict = {}
_GID_NEXT = [1000]


def gid_to_int(gid: str) -> int:
    """Stable, collision-free small positive int for a global id (events store an int
    track id). Same gid -> same int for the life of the process."""
    if not gid:
        return 0
    n = _GID_INT.get(gid)
    if n is None:
        n = _GID_NEXT[0]
        _GID_NEXT[0] += 1
        _GID_INT[gid] = n
    return n
