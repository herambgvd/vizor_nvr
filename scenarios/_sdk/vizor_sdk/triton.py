"""Shared Triton HTTP inference client for every scenario plugin.

One Triton server runs all models (face, person, vehicle, object, pose). Plugins
are thin clients: they own pre/post-processing, Triton runs the raw graph and
batches across cameras. This is the generic transport — `infer()` takes a tensor
dict and returns an output dict; the plugin's own engine wraps it with model
names + pre/post.

Extracted from the proven FRS TritonEngine + SS triton_client (identical core).
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

try:
    import tritonclient.http as triton_http
except Exception:  # noqa: BLE001 — tritonclient[http] is an optional extra
    triton_http = None

logger = logging.getLogger(__name__)


class TritonClient:
    """Generic shared-Triton client. Lazy-connects, fails soft (returns None /
    False rather than raising) so a plugin degrades instead of crashing when
    Triton is briefly unavailable."""

    def __init__(self, url: str, timeout: float = 30.0):
        # Accept "http://triton:8000" or "triton:8000" — the http client wants
        # the bare host:port.
        self.url = url.replace("http://", "").replace("https://", "")
        self.timeout = timeout
        self._client = None
        self.load_errors: dict[str, str] = {}
        # Per-model infer-failure throttle. A Triton outage at live FPS would log
        # every frame (10×/s) — log once, then ≤ every 30s while it persists, and
        # one recovery line when inference returns. Keeps an outage visible without
        # drowning the log.
        self._infer_fail: dict[str, dict] = {}

    # ── connection ──────────────────────────────────────────────────────────
    def _conn(self):
        if self._client is not None or triton_http is None:
            return self._client
        try:
            self._client = triton_http.InferenceServerClient(url=self.url, verbose=False)
        except Exception as exc:  # noqa: BLE001
            self.load_errors["client"] = str(exc)
            self._client = None
        return self._client

    @property
    def available(self) -> bool:
        """True if the tritonclient lib is installed and a connection opened."""
        return triton_http is not None and self._conn() is not None

    def model_ready(self, name: str) -> bool:
        c = self._conn()
        if c is None:
            return False
        try:
            return bool(c.is_model_ready(name))
        except Exception as exc:  # noqa: BLE001
            self.load_errors[name] = str(exc)
            return False

    def all_ready(self, *names: str) -> bool:
        return all(self.model_ready(n) for n in names)

    # ── inference ───────────────────────────────────────────────────────────
    def infer(
        self,
        model: str,
        inputs: dict[str, np.ndarray],
        out_names: list[str],
        timeout: float | None = None,
    ) -> dict[str, np.ndarray] | None:
        """Run one inference. `inputs` maps tensor name -> fp32 ndarray (any number
        of inputs). Returns {out_name: ndarray}, or None on any failure."""
        c = self._conn()
        if c is None or triton_http is None:
            return None
        try:
            tin = []
            for name, arr in inputs.items():
                a = np.ascontiguousarray(arr.astype(np.float32))
                t = triton_http.InferInput(name, list(a.shape), "FP32")
                t.set_data_from_numpy(a)
                tin.append(t)
            outs = [triton_http.InferRequestedOutput(n) for n in out_names]
            res = c.infer(
                model_name=model,
                inputs=tin,
                outputs=outs,
                timeout=int(timeout if timeout is not None else self.timeout),
            )
            result = {n: res.as_numpy(n) for n in out_names}
            self._note_infer_ok(model)
            return result
        except Exception as exc:  # noqa: BLE001
            self.load_errors[model] = str(exc)
            self._note_infer_fail(model, exc)
            return None

    def _note_infer_fail(self, model: str, exc: Exception) -> None:
        import time
        st = self._infer_fail.setdefault(
            model, {"failing": False, "last_log": 0.0, "count": 0})
        st["count"] += 1
        now = time.monotonic()
        if not st["failing"] or (now - st["last_log"]) > 30.0:
            logger.warning("triton infer '%s' failing (x%d): %s",
                           model, st["count"], exc)
            st["last_log"] = now
        st["failing"] = True

    def _note_infer_ok(self, model: str) -> None:
        st = self._infer_fail.get(model)
        if st and st["failing"]:
            logger.info("triton infer '%s' recovered after %d failures",
                        model, st["count"])
            st["failing"] = False
            st["count"] = 0

    def infer_one(
        self,
        model: str,
        inp_name: str,
        tensor: np.ndarray,
        out_names: list[str],
        timeout: float | None = None,
    ) -> dict[str, np.ndarray] | None:
        """Single-input convenience wrapper (the common case)."""
        return self.infer(model, {inp_name: tensor}, out_names, timeout)

    def status(self, models: dict[str, bool] | None = None) -> dict[str, Any]:
        """Health snapshot. `models` optionally maps model-name -> required(bool)
        so the plugin can report per-model readiness in /health."""
        out: dict[str, Any] = {
            "backend": "triton",
            "triton_url": self.url,
            "available": self.available,
            "load_errors": self.load_errors,
        }
        if models:
            out["models"] = {n: self.model_ready(n) for n in models}
            out["ready"] = all(self.model_ready(n) for n, req in models.items() if req)
        return out
