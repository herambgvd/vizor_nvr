"""Local ONNX inference engine.

Replaces the vizor-gpu Triton client: instead of `triton.infer(model, inputs,
outputs)` over gRPC, we run the same ONNX models in-process with onnxruntime.
The `infer()` signature mirrors the Triton call so the ported FRS pipeline maps
across unchanged — inputs are {tensor_name: ndarray}, outputs is a list of output
tensor names, return is {tensor_name: ndarray}.

Models are plain ONNX files (the exact ones Triton served): SCRFD detector,
ArcFace embedder, optional antispoofing. Mount them into the container; if a
required model is absent the engine reports not-ready and the plugin falls back
to its deterministic histogram embedding so the API still works end to end.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

try:
    import onnxruntime as ort
except Exception:  # noqa: BLE001
    ort = None

from .scrfd import names_for, postprocess_scrfd, preprocess_scrfd, scrfd_output_list
from .preprocess import postprocess_arcface, preprocess_arcface


_PROVIDERS = ["CUDAExecutionProvider", "CPUExecutionProvider"]
# Production must run on GPU. With FRS_REQUIRE_GPU=true the engine refuses to load
# on CPU fallback rather than silently delivering single-digit aggregate fps.
_REQUIRE_GPU = os.environ.get("FRS_REQUIRE_GPU", "false").lower() in ("1", "true", "yes", "on")
# Bound ORT thread pools so 50 worker threads don't each spawn N_cpu intra-op
# threads and thrash every core. Tunable via env.
_INTRA = int(os.environ.get("FRS_ORT_INTRA_THREADS", "2"))
_INTER = int(os.environ.get("FRS_ORT_INTER_THREADS", "1"))


def _session_options():
    if ort is None:
        return None
    so = ort.SessionOptions()
    so.intra_op_num_threads = max(1, _INTRA)
    so.inter_op_num_threads = max(1, _INTER)
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return so


class OnnxEngine:
    """Lazy-loaded ONNX sessions for the FRS model set."""

    def __init__(
        self,
        detector_path: str | os.PathLike,
        embed_path: str | os.PathLike,
        antispoof_path: str | os.PathLike | None = None,
        fairface_path: str | os.PathLike | None = None,
    ) -> None:
        self.detector_path = Path(detector_path)
        self.embed_path = Path(embed_path)
        self.antispoof_path = Path(antispoof_path) if antispoof_path else None
        self.fairface_path = Path(fairface_path) if fairface_path else None
        self._sessions: dict[str, Any] = {}
        self._load_errors: dict[str, str] = {}
        self._detector_out_meta: list[str] | None = None

    # ── session management ────────────────────────────────────────────────
    def _session(self, key: str, path: Path):
        if key in self._sessions:
            return self._sessions[key]
        if ort is None or not path.exists():
            return None
        try:
            sess = ort.InferenceSession(str(path), sess_options=_session_options(),
                                        providers=_PROVIDERS)
            active = sess.get_providers()
            if _REQUIRE_GPU and "CUDAExecutionProvider" not in active:
                # Fail LOUD: GPU was required but ORT fell back to CPU (missing
                # CUDA libs / no GPU passthrough). Don't silently crawl.
                raise RuntimeError(
                    f"FRS_REQUIRE_GPU is set but CUDA provider is not active for "
                    f"{key} (providers={active}). Check GPU passthrough + CUDA libs.")
            if "CUDAExecutionProvider" not in active:
                print(f"[frs] WARNING: {key} running on CPU fallback (providers={active}) "
                      f"— not viable at scale; set GPU passthrough.", flush=True)
            self._sessions[key] = sess
            return sess
        except Exception as exc:  # noqa: BLE001
            self._load_errors[key] = str(exc)
            if _REQUIRE_GPU:
                raise
            return None

    def detector(self):
        return self._session("detector", self.detector_path)

    def embedder(self):
        return self._session("embed", self.embed_path)

    def fairface(self):
        if self.fairface_path is None:
            return None
        return self._session("fairface", self.fairface_path)

    def age_gender(self, crop_bgr):
        """Run FairFace on a face crop → {gender, gender_confidence, age, age_range}
        or None if no model."""
        sess = self.fairface()
        if sess is None:
            return None
        from .fairface import postprocess_fairface, preprocess_fairface
        inp = preprocess_fairface(crop_bgr)
        out_name = sess.get_outputs()[0].name
        result = sess.run([out_name], {sess.get_inputs()[0].name: inp})
        return postprocess_fairface(result[0])

    def antispoof(self):
        if self.antispoof_path is None:
            return None
        return self._session("antispoof", self.antispoof_path)

    @property
    def ready(self) -> bool:
        """True when both required models (detector + embedder) load."""
        return self.detector() is not None and self.embedder() is not None

    def status(self) -> dict[str, Any]:
        providers = ort.get_available_providers() if ort else []
        return {
            "runtime_available": ort is not None,
            "providers": providers,
            "cuda_provider": "CUDAExecutionProvider" in providers,
            "detector_model": str(self.detector_path),
            "detector_present": self.detector_path.exists(),
            "detector_loadable": self.detector() is not None,
            "embed_model": str(self.embed_path),
            "embed_present": self.embed_path.exists(),
            "embed_loadable": self.embedder() is not None,
            "antispoof_model": str(self.antispoof_path) if self.antispoof_path else None,
            "antispoof_loadable": self.antispoof() is not None,
            "fairface_model": str(self.fairface_path) if self.fairface_path else None,
            "fairface_loadable": self.fairface() is not None,
            "load_errors": self._load_errors,
            "ready": self.ready,
        }

    # ── inference ─────────────────────────────────────────────────────────
    def _run(self, session, inputs: dict[str, np.ndarray], outputs: list[str]) -> dict[str, np.ndarray]:
        # onnxruntime matches by exact input name; SCRFD/ArcFace exports use a
        # single input but its node name varies ("input.1", "input"). Bind by the
        # session's actual first input name to stay export-agnostic.
        sess_inputs = {i.name for i in session.get_inputs()}
        feed: dict[str, np.ndarray] = {}
        if len(inputs) == 1 and next(iter(inputs)) not in sess_inputs:
            only = next(iter(session.get_inputs())).name
            feed[only] = next(iter(inputs.values()))
        else:
            feed = {k: v for k, v in inputs.items() if k in sess_inputs}
        out_names = [o.name for o in session.get_outputs()]
        wanted = [o for o in outputs if o in out_names] or out_names
        results = session.run(wanted, feed)
        return dict(zip(wanted, results))

    def detect_faces(self, frame_bgr: np.ndarray, conf_thresh: float = 0.5, nms_thresh: float = 0.4) -> list[dict]:
        """Run SCRFD → list of {bbox, confidence, landmarks} in original image space."""
        sess = self.detector()
        if sess is None:
            return []
        tensor, scale = preprocess_scrfd(frame_bgr)
        out_names = [o.name for o in sess.get_outputs()]
        results = sess.run(out_names, {sess.get_inputs()[0].name: tensor})
        raw = dict(zip(out_names, results))
        # Map numeric output names → logical score_/bbox_/kps_ keys.
        names = names_for()
        logical = {}
        for k, tname in names.items():
            if tname in raw:
                logical[k] = raw[tname]
        # Fallback: if numeric names don't match this export, assume the model's
        # outputs come in the canonical 9-tensor order (score x3, bbox x3, kps x3).
        if len(logical) < 9 and len(results) >= 9:
            order = ["score_8", "score_16", "score_32", "bbox_8", "bbox_16",
                     "bbox_32", "kps_8", "kps_16", "kps_32"]
            logical = {order[i]: results[i] for i in range(9)}
        h, w = frame_bgr.shape[:2]
        return postprocess_scrfd(logical, w, h, scale, conf_thresh=conf_thresh, nms_thresh=nms_thresh)

    def embed_face(self, aligned_bgr: np.ndarray) -> np.ndarray | None:
        """Run ArcFace on a 112x112 aligned BGR crop → L2-normalised 512-d vector."""
        sess = self.embedder()
        if sess is None:
            return None
        arc_in = preprocess_arcface(aligned_bgr)
        out_name = sess.get_outputs()[0].name
        result = sess.run([out_name], {sess.get_inputs()[0].name: arc_in})
        return postprocess_arcface(result[0])

    def liveness(self, crop_bgr: np.ndarray) -> float | None:
        """Run antispoofing → live-class probability, or None if no model."""
        sess = self.antispoof()
        if sess is None:
            return None
        from .preprocess import postprocess_antispoofing, preprocess_antispoofing
        as_in = preprocess_antispoofing(crop_bgr)
        out_name = sess.get_outputs()[0].name
        result = sess.run([out_name], {sess.get_inputs()[0].name: as_in})
        return postprocess_antispoofing(result[0])
