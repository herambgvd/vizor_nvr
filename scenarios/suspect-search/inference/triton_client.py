"""Thin Triton client for suspect-search — now backed by the shared Vizor SDK.

Keeps the original module-level `infer()` / `model_ready()` API so the callers
(detect_reid, attributes) are unchanged; the implementation delegates to the
SDK's TritonClient (one shared, fail-soft client). The plugin still owns all
pre/post-processing for yolo26 / person_reid / clothing_yolos.
"""
from __future__ import annotations

import os

import numpy as np

from vizor_sdk import TritonClient

TRITON_URL = os.getenv("TRITON_URL", "triton:8000")

# One shared client for the whole plugin.
_sdk_client = TritonClient(TRITON_URL)


def _conn():
    """Back-compat: expose the underlying client connection."""
    return _sdk_client._conn()


def model_ready(name: str) -> bool:
    return _sdk_client.model_ready(name)


def infer(model: str, inputs: dict[str, np.ndarray], out_names: list[str],
          timeout: float = 30.0) -> dict[str, np.ndarray] | None:
    """Run one inference. `inputs` maps tensor name -> fp32 ndarray. Returns
    {out_name: ndarray} or None on failure."""
    return _sdk_client.infer(model, inputs, out_names, timeout)
