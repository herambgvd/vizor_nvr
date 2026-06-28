"""Person Re-ID embedding via Triton (the shared `person_reid` OSNet-style model).

Gives the PPE pipeline an appearance embedding per person crop so a worker keeps a
stable global identity across ByteTrack id changes (occlusion / turn / re-enter). The
embedding feeds ReIDMatcher (cosine + temporal memory). No torch — the model runs on
Triton exactly like the YOLO detector; this is a thin client over it.

Model IO (triton/model_repository/person_reid): input "input" [3,256,128] FP32,
output "output" [768,1,1]. Preprocess = ImageNet-normalised RGB CHW at 256x128.
"""
from __future__ import annotations

import logging

import numpy as np

import config

logger = logging.getLogger("ppe.reid")

_SIZE = (128, 256)  # (w, h) for cv2.resize
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)


class ReIDExtractor:
    """OSNet-style appearance embeddings over Triton. Fail-soft (returns None)."""

    def __init__(self):
        from vizor_sdk.triton import TritonClient
        import os
        grpc_url = os.environ.get("TRITON_GRPC_URL")
        if os.environ.get("VIZOR_TRITON_GRPC", "0").lower() in ("1", "true", "yes", "on") and grpc_url:
            self.client = TritonClient(grpc_url, grpc=True)
        else:
            self.client = TritonClient(config.TRITON_URL)
        self.model = config.PPE_REID_MODEL_NAME
        self.input = "input"
        self.output = "output"

    def ready(self) -> bool:
        try:
            return self.client.model_ready(self.model)
        except Exception:  # noqa: BLE001
            return False

    def warmup(self) -> None:
        try:
            self.client.load_model(self.model)
        except Exception as e:  # noqa: BLE001
            logger.warning("[reid] load_model %s failed: %s", self.model, e)

    def _preprocess(self, crop_bgr) -> np.ndarray | None:
        import cv2
        if crop_bgr is None or getattr(crop_bgr, "size", 0) == 0:
            return None
        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        rgb = cv2.resize(rgb, _SIZE, interpolation=cv2.INTER_LINEAR)
        x = (rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)
        x = (x - _MEAN) / _STD
        return x[np.newaxis, ...]            # (1,3,256,128)

    def extract(self, crop_bgr) -> np.ndarray | None:
        """Return an L2-normalised 768-d embedding for a person crop, or None."""
        tensor = self._preprocess(crop_bgr)
        if tensor is None:
            return None
        try:
            out = self.client.infer_one(self.model, self.input, tensor, [self.output])
            if not out or self.output not in out:
                return None
            emb = np.asarray(out[self.output], dtype=np.float32).reshape(-1)
            n = float(np.linalg.norm(emb))
            return emb / n if n > 1e-9 else emb
        except Exception as e:  # noqa: BLE001
            logger.debug("[reid] extract failed: %s", e)
            return None

    def extract_person(self, frame_bgr, box, pad: float = 0.05) -> np.ndarray | None:
        """Crop a person box (small padding) from the frame and embed it."""
        if frame_bgr is None:
            return None
        h, w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = box
        pw, ph = (x2 - x1) * pad, (y2 - y1) * pad
        cx1, cy1 = max(0, int(x1 - pw)), max(0, int(y1 - ph))
        cx2, cy2 = min(w, int(x2 + pw)), min(h, int(y2 + ph))
        crop = frame_bgr[cy1:cy2, cx1:cx2]
        return self.extract(crop)
