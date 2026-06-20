"""Triton-backed PP-OCRv6 plate recognition (model ``ppocr_v6``).

Thin client over the shared SDK TritonClient. Owns the PP-OCRv6 pre-processing +
CTC greedy decode — Triton runs the raw recognition graph:

  * preprocess (PORTED VERBATIM from final_poc/ocr_ppocr.py._preprocess):
      resize the BGR crop to H=48 keeping aspect ratio (width = ceil(48*w/h),
      capped at OCR_MAX_W), CHW, normalize (x/255 - 0.5) / 0.5. BGR order — NO
      channel swap (matches the POC + the rasp_poc C++ reference exactly).
  * infer: input "x" [N,3,48,W] fp32 (dynamic batch + width) → output
      "fetch_name_0" [N,T,18710] CTC logits.
  * decode (PORTED VERBATIM): blank=index 0 run-length collapse — argmax per
      timestep, emit char on (c != prev and c != 0); conf = mean of the per-emit
      max value over the row (the POC's `out.max(1)`, not softmaxed).

dict_v6.txt (18707 lines; ships in the image): chars = ["blank"] + file_lines +
[" "], so model index i maps to chars[i]. read(bgr) -> (text, conf_0_100)."""
from __future__ import annotations

import logging
import math
import os
from typing import Any

import numpy as np

import config

logger = logging.getLogger(__name__)


def _load_dict(path: str) -> list[str]:
    """Build the char table the way the POC does: index 0 = CTC blank, then the
    file lines, then a trailing space (PP-OCRv6 use_space_char)."""
    chars = ["blank"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            chars += f.read().split("\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("anpr ocr dict load failed (%s): %s", path, exc)
    chars.append(" ")
    return chars


class PlateOCR:
    """Stateless PP-OCRv6 recognizer running on the shared Triton server."""

    def __init__(self) -> None:
        from vizor_sdk import TritonClient

        self.client = TritonClient(config.TRITON_URL)
        self.model = config.OCR_MODEL_NAME
        self.input = config.OCR_MODEL_INPUT
        self.output = config.OCR_MODEL_OUTPUT
        self.rec_h = config.OCR_REC_H
        self.max_w = config.OCR_MAX_W
        self.chars = _load_dict(config.OCR_DICT_PATH)
        self.dict_ok = len(self.chars) > 3 and os.path.exists(config.OCR_DICT_PATH)

    # ── readiness ──────────────────────────────────────────────────────────
    def ready(self) -> bool:
        return self.client.model_ready(self.model) and self.dict_ok

    def status(self) -> dict[str, Any]:
        st = self.client.status({self.model: True})
        st["dict_chars"] = len(self.chars)
        st["dict_ok"] = self.dict_ok
        return st

    # ── preprocess (ported verbatim) ────────────────────────────────────────
    def _preprocess(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        rw = int(math.ceil(self.rec_h * w / max(1, h)))
        rw = max(1, min(rw, self.max_w))
        import cv2

        img = cv2.resize(bgr, (rw, self.rec_h)).astype("float32")
        img = img.transpose(2, 0, 1) / 255.0   # CHW, BGR order preserved
        img -= 0.5
        img /= 0.5
        return img[None]                         # [1,3,48,rw]

    # ── decode (ported verbatim) ────────────────────────────────────────────
    def _decode(self, out: np.ndarray) -> tuple[str, float]:
        """CTC greedy decode of one [T,C] logits row. Run-length collapse with
        blank=0; conf = mean of the per-emitted-char max value (POC parity)."""
        idx = out.argmax(1)
        conf = out.max(1)
        res, confs, prev = [], [], -1
        for t, c in enumerate(idx):
            if c != prev and c != 0 and c < len(self.chars):
                res.append(self.chars[c])
                confs.append(conf[t])
            prev = c
        text = "".join(res)
        return text, (float(np.mean(confs) * 100) if confs else 0.0)

    # ── read ────────────────────────────────────────────────────────────────
    def read(self, bgr_crop: np.ndarray) -> tuple[str, float]:
        """OCR one BGR plate crop → (text, conf_0_100). Returns ("", 0.0) on any
        failure (empty crop / Triton down / bad output)."""
        if bgr_crop is None or getattr(bgr_crop, "size", 0) == 0:
            return "", 0.0
        try:
            x = self._preprocess(bgr_crop)
        except Exception as exc:  # noqa: BLE001
            logger.warning("anpr ocr preprocess failed: %s", exc)
            return "", 0.0
        res = self.client.infer_one(self.model, self.input, x, [self.output])
        if not res or self.output not in res:
            return "", 0.0
        out = np.asarray(res[self.output])
        if out.ndim == 3:
            out = out[0]                          # [T,C]
        if out.ndim != 2:
            return "", 0.0
        try:
            return self._decode(out)
        except Exception as exc:  # noqa: BLE001
            logger.warning("anpr ocr decode failed: %s", exc)
            return "", 0.0


# Module-level singleton (lazy Triton connect inside TritonClient).
ocr = PlateOCR()
