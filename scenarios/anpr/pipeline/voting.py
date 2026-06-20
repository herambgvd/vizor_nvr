"""Per-track plate voting — the proven POC consensus core, fixed for multi-lane.

The POC (final_poc/tracker.py) ran ONE VehicleSession at a time (single lane/zone),
so two vehicles in frame together corrupted each other's vote. Here the voting
math is ported VERBATIM but keyed by the SDK ByteTracker track id, so EVERY
tracked vehicle accumulates its own reads and votes independently on exit.

VehicleSession.vote (ported verbatim):
  * pick the most common LENGTH across all reads,
  * per character position, take the majority char over reads of that length,
  * conf = mean conf of reads whose full text equals the voted plate (fallback:
    mean over all same-length reads).
A session closes when its plate has been gone for `exit_frames` consecutive
processed frames, OR on flush() at stream end; it only emits if it has at least
`min_reads` reads (ignores blips).
"""
from __future__ import annotations

from collections import Counter
from typing import Optional


class VehicleSession:
    """Accumulates reads for one tracked vehicle. Verbatim vote() from the POC."""

    def __init__(self):
        self.reads = []          # list of (text, conf)
        self.best_crop = None    # crop of the highest-conf frame
        self.best_conf = -1.0
        self.best_box = None     # plate box (x1,y1,x2,y2) of the highest-conf frame
        self.best_frame = None   # full BGR frame of the highest-conf read (for snapshot)
        self.frames = 0          # reads this vehicle contributed
        self.gap = 0             # consecutive processed frames with no read

    def add(self, text, conf, crop, box=None, frame=None):
        self.reads.append((text, conf))
        self.frames += 1
        self.gap = 0
        if conf > self.best_conf:
            self.best_conf = conf
            self.best_crop = crop
            self.best_box = box
            self.best_frame = frame

    def vote(self):
        """Per-position majority over the most common length. Returns (plate, conf)
        with conf on the 0..1 scale (POC stored 0..100; we divide by 100 at emit)."""
        if not self.reads:
            return None, 0.0
        texts = [t for t, _ in self.reads]
        length = Counter(len(t) for t in texts).most_common(1)[0][0]
        same = [(t, c) for t, c in self.reads if len(t) == length]
        if not same:
            return None, 0.0
        out = []
        for i in range(length):
            ch = Counter(t[i] for t, _ in same).most_common(1)[0][0]
            out.append(ch)
        plate = "".join(out)
        confs = [c for t, c in same if t == plate]
        conf = (sum(confs) / len(confs)) if confs else (sum(c for _, c in same) / len(same))
        return plate, conf


class TrackVoteManager:
    """Multi-track session manager (the single-lane bug fix).

    One VehicleSession per ByteTracker track id. Each processed frame:
      * call `add(track_id, text, conf, crop, box, frame)` for every track that
        produced a valid read this frame,
      * call `tick(active_track_ids)` once with the set of track ids seen this
        frame — sessions whose track produced no read advance their gap; a session
        gone `exit_frames` frames CLOSES and is returned as a finished result.
    `flush()` force-closes all open sessions (stream end / worker stop).

    A finished result is {track_id, plate, conf(0..1), crop, box, frame, frames}.
    """

    def __init__(self, exit_frames: int = 15, min_reads: int = 3):
        self.exit_frames = exit_frames
        self.min_reads = min_reads
        self._sessions: dict[int, VehicleSession] = {}

    def add(self, track_id: int, text: str, conf: float, crop=None, box=None, frame=None) -> None:
        sess = self._sessions.get(track_id)
        if sess is None:
            sess = VehicleSession()
            self._sessions[track_id] = sess
        sess.add(text, conf, crop, box, frame)

    def tick(self, active_track_ids) -> list[dict]:
        """Advance gaps + close sessions that have left. Returns finished results."""
        active = set(active_track_ids or [])
        finished: list[dict] = []
        for tid in list(self._sessions.keys()):
            sess = self._sessions[tid]
            if tid in active and sess.gap == 0:
                continue  # got a read this frame (add() reset gap)
            sess.gap += 1
            if sess.gap >= self.exit_frames:
                self._sessions.pop(tid, None)
                res = self._finish(tid, sess)
                if res is not None:
                    finished.append(res)
        return finished

    def flush(self) -> list[dict]:
        """Force-close every open session (call at stream end)."""
        finished: list[dict] = []
        for tid in list(self._sessions.keys()):
            sess = self._sessions.pop(tid)
            res = self._finish(tid, sess)
            if res is not None:
                finished.append(res)
        return finished

    def _finish(self, track_id: int, sess: VehicleSession) -> Optional[dict]:
        if len(sess.reads) < self.min_reads:
            return None
        plate, conf = sess.vote()
        if not plate:
            return None
        return {
            "track_id": track_id,
            "plate": plate,
            "conf": conf / 100.0 if conf > 1.0 else conf,  # POC conf is 0..100
            "crop": sess.best_crop,
            "box": sess.best_box,
            "frame": sess.best_frame,
            "frames": sess.frames,
        }
