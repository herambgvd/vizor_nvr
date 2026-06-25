"""Async inference engine — fully-async mirror of TritonEngine for the worker.

vizor-gpu's pipeline awaits every Triton call so decode + recognition cooperate on
the event loop (and a native NVDEC decoder never starves). nvr's TritonEngine is
100% sync, which stalled the cpp decoder. This engine wraps the SAME nvr pre/post
processing (scrfd / arcface / antispoofing / fairface) but runs the Triton infer
through the async worker TritonClient (gRPC, hard timeout). CPU pre/post is light
(<1ms) so it stays inline; the network infer is a true `await`.

Only the worker (async path) uses this. The legacy sync TritonEngine/OnnxEngine and
the in-app supervisor path are untouched.
"""
from __future__ import annotations

import numpy as np

from .scrfd import names_for, postprocess_scrfd, preprocess_scrfd
from .preprocess import (
    postprocess_arcface, preprocess_arcface,
    postprocess_antispoofing, preprocess_antispoofing,
)
from .triton_engine import (
    _DET_MODEL, _EMB_MODEL, _FF_MODEL, _AS_MODEL,
    _DET_IN, _EMB_IN, _FF_IN, _AS_IN,
    _EMB_OUT, _FF_OUT, _AS_OUT, _DET_OUTS,
)


class AsyncEngine:
    """Async inference surface (detect/embed/liveness/age_gender) over the async
    worker TritonClient. Same outputs as the sync TritonEngine."""

    def __init__(self, triton, has_fairface: bool = True, has_antispoof: bool = True):
        self._triton = triton  # vizor_sdk.worker.TritonClient (async infer)
        self._has_fairface = has_fairface
        self._has_antispoof = has_antispoof

    async def detect_faces(self, frame_bgr: np.ndarray, conf_thresh: float = 0.5,
                           nms_thresh: float = 0.4) -> list[dict]:
        tensor, scale = preprocess_scrfd(frame_bgr)
        try:
            raw = await self._triton.infer(_DET_MODEL, {_DET_IN: tensor.astype(np.float32)}, _DET_OUTS)
        except Exception:  # noqa: BLE001 — timeout / triton blip: drop the frame
            return []
        if not raw:
            return []
        names = names_for()
        logical = {k: raw[t] for k, t in names.items() if t in raw}
        if len(logical) < 9:
            order = ["score_8", "score_16", "score_32", "bbox_8", "bbox_16",
                     "bbox_32", "kps_8", "kps_16", "kps_32"]
            logical = {order[i]: raw[_DET_OUTS[i]] for i in range(9)}
        h, w = frame_bgr.shape[:2]
        return postprocess_scrfd(logical, w, h, scale, conf_thresh=conf_thresh, nms_thresh=nms_thresh)

    async def embed_face(self, aligned_bgr: np.ndarray) -> np.ndarray | None:
        try:
            raw = await self._triton.infer(_EMB_MODEL, {_EMB_IN: preprocess_arcface(aligned_bgr)}, [_EMB_OUT])
        except Exception:  # noqa: BLE001
            return None
        if not raw:
            return None
        return postprocess_arcface(raw[_EMB_OUT])

    async def liveness(self, crop_bgr: np.ndarray) -> float | None:
        if not self._has_antispoof:
            return None
        try:
            raw = await self._triton.infer(_AS_MODEL, {_AS_IN: preprocess_antispoofing(crop_bgr)}, [_AS_OUT])
        except Exception:  # noqa: BLE001
            return None
        if not raw:
            return None
        return postprocess_antispoofing(raw[_AS_OUT])

    async def age_gender(self, crop_bgr: np.ndarray):
        if not self._has_fairface:
            return None
        from .fairface import postprocess_fairface, preprocess_fairface
        try:
            raw = await self._triton.infer(_FF_MODEL, {_FF_IN: preprocess_fairface(crop_bgr)}, [_FF_OUT])
        except Exception:  # noqa: BLE001
            return None
        if not raw:
            return None
        return postprocess_fairface(raw[_FF_OUT])
