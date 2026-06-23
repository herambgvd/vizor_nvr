"""SigLIP second-stage PPE verifier — replaces the (untrained) DINOv2 head.

A SigLIP2-large image encoder (Triton model `siglip_ppe`) produces an L2-normalised
1024-d embedding of a body-region crop. The embedding is dotted with precomputed
text embeddings for each PPE item ("a person wearing a high-visibility safety
vest", …) and the SigLIP sigmoid (scale ~108, bias ~-16.35) turns the similarity
into a per-item probability. Heads + scale/bias live in `siglip_ppe_heads.npz`.

Why SigLIP, not DINOv2: the hosted DINOv2 vest head scored ~0.96 for EVERY torso
(it could neither veto a false vest nor rescue a real one). SigLIP discriminates —
on the client sample crops it agreed with the human label on 442/444 (the 89 YOLO
disagreements were 87 SigLIP-correct), recovering YOLO's missed vests AND vetoing
its false vests (a red/checked shirt read as a vest).

Fusion is symmetric and per-item: a YOLO positive the SigLIP head scores below the
item's confirm floor is VETOED; an item YOLO missed that SigLIP scores above the
rescue floor is ADDED. Region crops: helmet/goggles = head band, vest = torso,
boots = feet. Fail-soft — any error leaves the YOLO evidence untouched.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

import config

logger = logging.getLogger(__name__)

# SigLIP image preprocessing (matches the AutoProcessor used at export):
# resize to 256, scale to [-1,1] (mean .5 / std .5), CHW RGB.
_SIZE = 256
_MEAN = np.array([0.5, 0.5, 0.5], dtype=np.float32).reshape(3, 1, 1)
_STD = np.array([0.5, 0.5, 0.5], dtype=np.float32).reshape(3, 1, 1)

# canonical PPE label -> the head/torso/feet crop region it lives in.
_REGION = {
    "Hardhat": "head",
    "Goggles": "head",
    "Safety_Vest": "torso",
    "Boots": "feet",
}
# heads npz text key per canonical label.
_TEXT_KEY = {
    "Hardhat": "text_helmet",
    "Safety_Vest": "text_vest",
    "Goggles": "text_goggles",
    "Boots": "text_boots",
}


def _region_crop(frame, box, region: str):
    """Body-region crop from a person box. Bands tuned to the PPE location."""
    x1, y1, x2, y2 = box
    h, w = max(1, y2 - y1), max(1, x2 - x1)
    if region == "head":
        left, right = x1 - int(0.10 * w), x2 + int(0.10 * w)
        top, bottom = y1 - int(0.08 * h), y1 + int(0.42 * h)
    elif region == "feet":
        left, right = x1 - int(0.06 * w), x2 + int(0.06 * w)
        top, bottom = y1 + int(0.74 * h), y2
    else:  # torso
        left, right = x1 - int(0.06 * w), x2 + int(0.06 * w)
        top, bottom = y1 + int(0.16 * h), y1 + int(0.82 * h)
    fh, fw = frame.shape[:2]
    left, right = max(0, left), min(fw, right)
    top, bottom = max(0, top), min(fh, bottom)
    crop = frame[top:bottom, left:right]
    return crop if crop.size else None


class SiglipVerifier:
    """SigLIP image encoder (Triton) + precomputed text heads. Fail-soft."""

    def __init__(self, triton):
        self._triton = triton
        self._model = config.PPE_SIGLIP_MODEL_NAME
        self.enabled = False
        self._scale = 1.0
        self._bias = 0.0
        self._text = {}                       # canonical label -> (1024,) unit vec
        self._cache: dict[int, tuple[int, dict]] = {}
        self.interval = max(1, config.PPE_SIGLIP_INTERVAL)
        # per-item confirm (veto below) / rescue (add above) thresholds.
        self.confirm = config.PPE_SIGLIP_CONFIRM      # {item: float}
        self.rescue = config.PPE_SIGLIP_RESCUE        # {item: float}

        if not self._model:
            return
        artifact = Path(config.PPE_SIGLIP_ARTIFACT)
        if not artifact.exists():
            logger.warning("[ppe-siglip] heads %s missing — verifier disabled", artifact)
            return
        try:
            d = np.load(artifact, allow_pickle=False)
            self._scale = float(d["scale"])
            self._bias = float(d["bias"])
            for canon, key in _TEXT_KEY.items():
                if key in d:
                    v = d[key].astype(np.float32).reshape(-1)
                    self._text[canon] = v / max(np.linalg.norm(v), 1e-9)
            self.enabled = bool(self._text)
            logger.info("[ppe-siglip] verifier enabled (Triton %s, items=%s)",
                        self._model, list(self._text))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ppe-siglip] heads load failed: %s — verifier disabled", exc)

    # ── embedding via Triton ────────────────────────────────────────────────
    def _preprocess(self, crop_bgr) -> np.ndarray:
        import cv2

        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        rgb = cv2.resize(rgb, (_SIZE, _SIZE), interpolation=cv2.INTER_LINEAR)
        x = (rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)
        return (x - _MEAN) / _STD

    def _embed(self, crops: list) -> np.ndarray | None:
        # The exported SigLIP graph has a fixed batch of 1, so score each crop with
        # its own infer call and stack the results.
        feats = []
        for c in crops:
            x = self._preprocess(c)[None].astype(np.float32)   # [1,3,256,256]
            out = self._triton.client.infer(self._model, {"pixel_values": x}, ["image_embed"])
            if not out or "image_embed" not in out:
                return None
            feats.append(out["image_embed"].astype(np.float32).reshape(-1))
        f = np.stack(feats)                                    # [N,1024]
        return f / np.maximum(np.linalg.norm(f, axis=1, keepdims=True), 1e-9)

    def _sigmoid(self, sim: float) -> float:
        return float(1.0 / (1.0 + np.exp(-np.clip(self._scale * sim + self._bias, -30, 30))))

    # ── public: classify + fuse ─────────────────────────────────────────────
    def classify(self, frame, persons, frame_no: int, items=None) -> dict:
        """Return {track_id: {canonical: prob}} for the given PPE items, cached per
        track for `interval` frames. `items` defaults to all known heads."""
        if not self.enabled:
            return {}
        wanted = [c for c in (items or list(self._text)) if c in self._text]
        if not wanted:
            return {}
        crops, keys, due = [], [], []
        for p in persons:
            tid = p.track_id
            if tid is None:
                continue
            cached = self._cache.get(tid)
            if cached is not None and frame_no - cached[0] < self.interval:
                continue
            due.append(tid)
            for canon in wanted:
                crop = _region_crop(frame, p.box, _REGION.get(canon, "torso"))
                if crop is not None and min(crop.shape[:2]) >= 12:
                    crops.append(crop)
                    keys.append((tid, canon))
        fresh = {tid: {} for tid in due}
        if crops:
            try:
                feats = self._embed(crops)
                if feats is not None:
                    for (tid, canon), f in zip(keys, feats):
                        sim = float(f @ self._text[canon])
                        fresh[tid][canon] = self._sigmoid(sim)
            except Exception as exc:  # noqa: BLE001 — never break the pipeline
                logger.debug("[ppe-siglip] classify failed: %s", exc)
        for tid in due:
            self._cache[tid] = (frame_no, fresh[tid])
        active = {p.track_id for p in persons}
        self._cache = {k: v for k, v in self._cache.items() if k in active}
        return {tid: vals for tid, (_f, vals) in self._cache.items()}

    def fuse(self, linked: dict, scores: dict) -> None:
        """Mutate `linked` in place using the SigLIP per-item probabilities:
          * a YOLO positive scored below the item's CONFIRM floor is VETOED
            (kills the false vest / false helmet),
          * an item YOLO missed scored above the item's RESCUE floor is ADDED
            (recovers the vest/helmet YOLO dropped).
        Symmetric across all four items. Items without a SigLIP head are left as-is.
        """
        if not self.enabled:
            return
        from pipeline.engine import Detection  # local import (cycle)

        for tid, probs in scores.items():
            obs = linked.setdefault(tid, {})
            for canon, prob in probs.items():
                if prob is None:
                    continue
                current = obs.get(canon)
                confirm = self.confirm.get(canon, 0.0)
                rescue = self.rescue.get(canon, 1.1)
                if current is not None and prob < confirm:
                    obs.pop(canon, None)                       # veto false positive
                elif current is None and prob >= rescue:
                    obs[canon] = Detection(canon, float(prob), (0, 0, 0, 0))  # rescue
