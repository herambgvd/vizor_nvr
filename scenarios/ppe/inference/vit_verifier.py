"""DINOv2 second-stage PPE verifier (Triton-backed).

The proven POC's accuracy layer: a frozen DINOv2-small backbone (served on Triton
as `dinov2_small`) produces a 384-d CLS embedding of a head/torso crop, which a
tiny camera-trained linear head (vit_ppe_dinov2_small.npz, kept client-side)
turns into a helmet/vest probability. Fusion is asymmetric (ported verbatim):

  * helmet — strong enough to VETO: an existing helmet positive below the confirm
    threshold (0.58) is removed.
  * helmet — RESCUE a missed helmet above the rescue threshold (0.82).
  * vest   — RESCUE-only above 0.92 (the vest head was not reliable enough to veto
    real reflective vests).

Runs once per `interval` frames per track (cached). Disabled (no-op) when
`PPE_VIT_MODEL_NAME` is empty or the npz artifact is absent — the pipeline then
runs the YOLO-only baseline unchanged.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

import config
from pipeline.engine import Detection  # the plugin's PPE Detection dataclass

logger = logging.getLogger(__name__)

# ImageNet normalization (DINOv2 / HF AutoImageProcessor defaults), 224x224.
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)
_SIZE = 224

# helmet/vest kind -> canonical PPE label the pipeline uses.
_LABEL = {"helmet": "Hardhat", "vest": "Safety_Vest"}


def body_crop(frame, box, kind: str):
    """Padded head (helmet) or torso (vest) crop from a person box. Verbatim POC."""
    x1, y1, x2, y2 = box
    h, w = max(1, y2 - y1), max(1, x2 - x1)
    if kind == "helmet":
        left, right = x1 - int(0.12 * w), x2 + int(0.12 * w)
        top, bottom = y1 - int(0.10 * h), y1 + int(0.38 * h)
    else:
        left, right = x1 - int(0.06 * w), x2 + int(0.06 * w)
        top, bottom = y1 + int(0.18 * h), y1 + int(0.78 * h)
    fh, fw = frame.shape[:2]
    left, right = max(0, left), min(fw, right)
    top, bottom = max(0, top), min(fh, bottom)
    crop = frame[top:bottom, left:right]
    return crop if crop.size else None


class VitVerifier:
    """Triton DINOv2 + client-side linear heads. Fail-soft: any error -> no fusion."""

    def __init__(self, triton):
        self._triton = triton
        self._model = config.PPE_VIT_MODEL_NAME
        self.enabled = False
        self._coef = {}
        self._intercept = {}
        self._mean = None
        self._scale = None
        self._cache: dict[int, tuple[int, dict]] = {}
        self.interval = max(1, config.PPE_VIT_INTERVAL)
        self.confirm = config.PPE_VIT_CONFIRM
        self.rescue = config.PPE_VIT_RESCUE
        self.vest_rescue = config.PPE_VIT_VEST_RESCUE

        if not self._model:
            return
        artifact = Path(config.PPE_VIT_ARTIFACT)
        if not artifact.exists():
            logger.warning("[ppe-vit] artifact %s missing — verifier disabled", artifact)
            return
        try:
            d = np.load(artifact, allow_pickle=False)
            self._coef = {k: d[f"{k}_coef"].astype(np.float32) for k in ("helmet", "vest")}
            self._intercept = {k: float(d[f"{k}_intercept"]) for k in ("helmet", "vest")}
            self._mean = d["feature_mean"].astype(np.float32)
            self._scale = np.maximum(d["feature_scale"].astype(np.float32), 1e-6)
            self.enabled = True
            logger.info("[ppe-vit] verifier enabled (Triton %s)", self._model)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ppe-vit] artifact load failed: %s — verifier disabled", exc)

    # ── embedding via Triton ────────────────────────────────────────────────
    def _preprocess(self, crop_bgr) -> np.ndarray:
        import cv2

        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        rgb = cv2.resize(rgb, (_SIZE, _SIZE), interpolation=cv2.INTER_LINEAR)
        x = rgb.astype(np.float32) / 255.0
        x = x.transpose(2, 0, 1)  # CHW
        return (x - _MEAN) / _STD

    def _embed(self, crops: list) -> np.ndarray | None:
        batch = np.stack([self._preprocess(c) for c in crops]).astype(np.float32)
        out = self._triton.client.infer(self._model, {"pixel_values": batch}, ["cls"])
        if not out:
            return None
        feats = out["cls"].astype(np.float32)  # [N,384]
        # L2-normalize (POC normalizes the CLS embedding before standardizing).
        norm = np.linalg.norm(feats, axis=1, keepdims=True)
        return feats / np.maximum(norm, 1e-9)

    def _probabilities(self, crops: list, kinds: list[str]) -> list[float]:
        feats = self._embed(crops)
        if feats is None:
            return [None] * len(crops)
        feats = (feats - self._mean) / self._scale
        out = []
        for f, kind in zip(feats, kinds):
            logit = float(f @ self._coef[kind] + self._intercept[kind])
            out.append(float(1.0 / (1.0 + np.exp(-np.clip(logit, -30, 30)))))
        return out

    # ── public: classify + fuse ─────────────────────────────────────────────
    def classify(self, frame, persons, frame_no: int) -> dict:
        """Return {track_id: {kind: prob}} for tracks due this interval (cached)."""
        if not self.enabled:
            return {}
        crops, kinds, keys, due = [], [], [], []
        for p in persons:
            tid = p.track_id
            if tid is None:
                continue
            cached = self._cache.get(tid)
            if cached is not None and frame_no - cached[0] < self.interval:
                continue
            due.append(tid)
            for kind in ("helmet", "vest"):
                crop = body_crop(frame, p.box, kind)
                if crop is not None and min(crop.shape[:2]) >= 12:
                    crops.append(crop)
                    kinds.append(kind)
                    keys.append((tid, kind))
        fresh = {tid: {} for tid in due}
        if crops:
            try:
                for (tid, kind), prob in zip(keys, self._probabilities(crops, kinds)):
                    if prob is not None:
                        fresh[tid][kind] = prob
            except Exception as exc:  # noqa: BLE001 — never break the pipeline
                logger.debug("[ppe-vit] classify failed: %s", exc)
        for tid in due:
            self._cache[tid] = (frame_no, fresh[tid])
        active = {p.track_id for p in persons}
        self._cache = {k: v for k, v in self._cache.items() if k in active}
        return {tid: vals for tid, (_f, vals) in self._cache.items()}

    def fuse(self, linked: dict, scores: dict) -> None:
        """Mutate `linked` in place: confirm helmet positives, rescue confident
        misses. Verbatim POC asymmetric policy."""
        if not self.enabled:
            return
        for tid, probs in scores.items():
            obs = linked.setdefault(tid, {})
            for kind, label in _LABEL.items():
                prob = probs.get(kind)
                if prob is None:
                    continue
                current = obs.get(label)
                if kind == "helmet" and current is not None and prob < self.confirm:
                    obs.pop(label, None)  # veto weak helmet
                elif (current is None
                      and prob >= (self.vest_rescue if kind == "vest" else self.rescue)
                      and not (kind == "helmet" and "NO_Hardhat" in obs)):
                    obs[label] = Detection(label, float(prob), (0, 0, 0, 0))  # rescue
