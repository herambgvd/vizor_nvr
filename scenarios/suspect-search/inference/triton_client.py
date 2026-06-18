"""Thin Triton HTTP inference client for suspect-search.

All models (yolo26 detector, person-reid embedder, clothing_yolos attribute
detector) run on the shared Triton server. The plugin only does pre/post
processing — same pattern as the FRS plugin's TritonEngine.
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np

try:
    import tritonclient.http as triton_http
except Exception:  # noqa: BLE001
    triton_http = None

TRITON_URL = os.getenv("TRITON_URL", "triton:8000")

_client = None


def _conn():
    global _client
    if _client is not None or triton_http is None:
        return _client
    try:
        url = TRITON_URL.replace("http://", "").replace("https://", "")
        _client = triton_http.InferenceServerClient(url=url, verbose=False)
    except Exception:  # noqa: BLE001
        _client = None
    return _client


def model_ready(name: str) -> bool:
    c = _conn()
    if c is None:
        return False
    try:
        return bool(c.is_model_ready(name))
    except Exception:  # noqa: BLE001
        return False


def infer(model: str, inputs: dict[str, np.ndarray], out_names: list[str],
          timeout: float = 30.0) -> dict[str, np.ndarray] | None:
    """Run one inference. `inputs` maps tensor name → fp32 ndarray. Returns
    {out_name: ndarray} or None on failure."""
    c = _conn()
    if c is None or triton_http is None:
        return None
    try:
        tin = []
        for name, arr in inputs.items():
            a = arr.astype(np.float32)
            t = triton_http.InferInput(name, list(a.shape), "FP32")
            t.set_data_from_numpy(a)
            tin.append(t)
        outs = [triton_http.InferRequestedOutput(n) for n in out_names]
        res = c.infer(model_name=model, inputs=tin, outputs=outs, timeout=int(timeout))
        return {n: res.as_numpy(n) for n in out_names}
    except Exception as exc:  # noqa: BLE001
        print(f"[suspect-search] triton infer '{model}' failed: {exc}", flush=True)
        return None
