"""Triton-backed inference engine.

Drop-in replacement for OnnxEngine: exposes the SAME public methods
(detect_faces / embed_face / liveness / age_gender / ready / status) so the
recognition pipeline is byte-for-byte identical — only the transport changes
(local ONNX session → shared Triton server). All pre/post-processing stays here
in the plugin; Triton only runs the raw model graph.

One shared Triton serves every AI scenario, with dynamic batching across all
cameras — the throughput + GIL win for 64-channel scale.
"""
from __future__ import annotations

from typing import Any

import threading

import numpy as np

try:
    import tritonclient.http as triton_http
except Exception:  # noqa: BLE001
    triton_http = None

from .scrfd import names_for, postprocess_scrfd, preprocess_scrfd
from .preprocess import (
    postprocess_arcface, preprocess_arcface,
    postprocess_antispoofing, preprocess_antispoofing,
)

# Triton model names (match the model_repository dir names) + their IO tensor
# names (from the ONNX exports — see config.pbtxt).
import os as _os
# How long a positive Triton model-readiness is trusted before re-checking, so the
# /health probe doesn't network-ping Triton on every request.
_READY_TTL_S = float(_os.getenv("FRS_MODEL_READY_TTL_S", "30"))

_DET_MODEL = "scrfd_10g"
_EMB_MODEL = "arcface_r50"
_FF_MODEL = "fairface"
_AS_MODEL = "antispoofing"

_DET_IN, _EMB_IN, _FF_IN, _AS_IN = "input.1", "input.1", "input", "input"
_EMB_OUT, _FF_OUT, _AS_OUT = "683", "output", "output"
_DET_OUTS = ["448", "471", "494", "451", "474", "497", "454", "477", "500"]


class TritonEngine:
    """Shared-Triton inference engine with the OnnxEngine method surface."""

    def __init__(self, url: str, has_fairface: bool = True, has_antispoof: bool = True,
                 timeout: float = 30.0):
        self.url = url.replace("http://", "").replace("https://", "")
        self._has_fairface = has_fairface
        self._has_antispoof = has_antispoof
        self._timeout = timeout
        # The triton HTTP client (geventhttpclient) is NOT safe to share across
        # threads — FastAPI runs sync endpoints in a threadpool, so a client built on
        # one thread silently fails (returns nothing) on another, which surfaced as a
        # bogus "engine not ready" 503 on /investigate. Keep one client PER THREAD.
        self._tls = threading.local()
        self._load_errors: dict[str, str] = {}
        self._ready_cache: dict[str, tuple[bool, float]] = {}  # name -> (ok, monotonic_ts)

    # ── client (thread-local) ──────────────────────────────────────────────
    def _conn(self):
        if triton_http is None:
            return None
        c = getattr(self._tls, "client", None)
        if c is not None:
            return c
        try:
            c = triton_http.InferenceServerClient(url=self.url, verbose=False)
            self._tls.client = c
        except Exception as exc:  # noqa: BLE001
            self._load_errors["client"] = str(exc)
            c = None
        return c

    def _model_ready(self, name: str) -> bool:
        # Cache a positive readiness for a while. is_model_ready() is a network
        # round-trip to Triton; the /health probe (and ready/status) called it on
        # every request, so when Triton was busy serving inference the probe blocked
        # for seconds and the orchestrator flapped the container "unhealthy" — which
        # looked like events "holding". Models don't unload mid-run, so once ready
        # we trust it for _READY_TTL_S and only re-check after that or on a miss.
        import time as _t
        now = _t.monotonic()
        cached = self._ready_cache.get(name)
        if cached and cached[0] and (now - cached[1]) < _READY_TTL_S:
            return True
        c = self._conn()
        if c is None:
            return False
        try:
            ok = bool(c.is_model_ready(name))
            self._ready_cache[name] = (ok, now)
            return ok
        except Exception as exc:  # noqa: BLE001
            self._load_errors[name] = str(exc)
            # On a transient error, fall back to the last known-good within TTL so a
            # blip doesn't mark a working engine unready.
            if cached and cached[0] and (now - cached[1]) < _READY_TTL_S:
                return True
            return False

    def _infer(self, model: str, inp_name: str, tensor: np.ndarray,
               out_names: list[str]) -> dict[str, np.ndarray] | None:
        c = self._conn()
        if c is None:
            return None
        try:
            t = tensor.astype(np.float32)
            inp = triton_http.InferInput(inp_name, list(t.shape), "FP32")
            inp.set_data_from_numpy(t)
            outs = [triton_http.InferRequestedOutput(n) for n in out_names]
            res = c.infer(model_name=model, inputs=[inp], outputs=outs, timeout=int(self._timeout))
            return {n: res.as_numpy(n) for n in out_names}
        except Exception as exc:  # noqa: BLE001
            self._load_errors[model] = str(exc)
            return None

    # ── readiness / status (OnnxEngine parity) ─────────────────────────────
    @property
    def ready(self) -> bool:
        return self._model_ready(_DET_MODEL) and self._model_ready(_EMB_MODEL)

    def status(self) -> dict[str, Any]:
        return {
            "backend": "triton",
            "triton_url": self.url,
            "detector_loadable": self._model_ready(_DET_MODEL),
            "embed_loadable": self._model_ready(_EMB_MODEL),
            "fairface_loadable": self._has_fairface and self._model_ready(_FF_MODEL),
            "antispoof_loadable": self._has_antispoof and self._model_ready(_AS_MODEL),
            "load_errors": self._load_errors,
            "ready": self.ready,
        }

    # ── inference (identical pre/post-processing to OnnxEngine) ─────────────
    def detect_faces(self, frame_bgr: np.ndarray, conf_thresh: float = 0.5,
                     nms_thresh: float = 0.4) -> list[dict]:
        tensor, scale = preprocess_scrfd(frame_bgr)
        raw = self._infer(_DET_MODEL, _DET_IN, tensor, _DET_OUTS)
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

    def embed_face(self, aligned_bgr: np.ndarray) -> np.ndarray | None:
        raw = self._infer(_EMB_MODEL, _EMB_IN, preprocess_arcface(aligned_bgr), [_EMB_OUT])
        if not raw:
            return None
        return postprocess_arcface(raw[_EMB_OUT])

    def liveness(self, crop_bgr: np.ndarray) -> float | None:
        if not self._has_antispoof:
            return None
        raw = self._infer(_AS_MODEL, _AS_IN, preprocess_antispoofing(crop_bgr), [_AS_OUT])
        if not raw:
            return None
        return postprocess_antispoofing(raw[_AS_OUT])

    def age_gender(self, crop_bgr: np.ndarray):
        if not self._has_fairface:
            return None
        from .fairface import postprocess_fairface, preprocess_fairface
        raw = self._infer(_FF_MODEL, _FF_IN, preprocess_fairface(crop_bgr), [_FF_OUT])
        if not raw:
            return None
        return postprocess_fairface(raw[_FF_OUT])
