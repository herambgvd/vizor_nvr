"""
Triton async gRPC client wrapper — used by FRS enrollment + recognition.

Tries the gRPC channel on settings.TRITON_URL; safe to call without
Triton running — `is_ready()` returns False and helpers raise clearly.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

try:
    import tritonclient.grpc as triton_grpc
    _HAS_TRITON = True
except ImportError:
    _HAS_TRITON = False


_executor: Optional[ThreadPoolExecutor] = None
_client = None
_lock = asyncio.Lock()


def _ensure_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="triton")
    return _executor


async def _get_client():
    """Lazy singleton. Re-tries on first call after disconnect."""
    global _client
    if not _HAS_TRITON:
        raise RuntimeError("tritonclient not installed")
    if not settings.TRITON_URL:
        raise RuntimeError("TRITON_URL not configured")
    async with _lock:
        if _client is not None:
            return _client
        url = settings.TRITON_URL
        _client = triton_grpc.InferenceServerClient(url=url, verbose=False)
        return _client


async def is_ready(model_name: Optional[str] = None) -> bool:
    """Return True if Triton is live (+ model loaded if specified)."""
    if not _HAS_TRITON or not settings.TRITON_URL:
        return False
    try:
        client = await _get_client()
        loop = asyncio.get_running_loop()
        ex = _ensure_executor()
        live = await loop.run_in_executor(ex, client.is_server_live)
        if not live:
            return False
        if model_name:
            ready = await loop.run_in_executor(
                ex, client.is_model_ready, model_name,
            )
            return bool(ready)
        return True
    except Exception as e:
        logger.debug("Triton not ready: %s", e)
        return False


async def infer(
    model_name: str,
    inputs: List[tuple[str, np.ndarray]],
    output_names: List[str],
    timeout_sec: float = 5.0,
) -> dict:
    """Run inference. Returns {output_name: ndarray}.

    `inputs` = list of (tensor_name, ndarray). Triton infers dtype from
    the array (FP32 / FP16 / INT8 etc.).
    """
    client = await _get_client()
    loop = asyncio.get_running_loop()
    ex = _ensure_executor()

    def _call():
        triton_inputs = []
        for name, arr in inputs:
            tin = triton_grpc.InferInput(
                name, arr.shape, _np_to_triton_dtype(arr.dtype),
            )
            tin.set_data_from_numpy(arr)
            triton_inputs.append(tin)
        triton_outputs = [triton_grpc.InferRequestedOutput(o) for o in output_names]
        result = client.infer(
            model_name=model_name,
            inputs=triton_inputs,
            outputs=triton_outputs,
            client_timeout=timeout_sec,
        )
        return {o: result.as_numpy(o) for o in output_names}

    return await loop.run_in_executor(ex, _call)


def _np_to_triton_dtype(np_dtype) -> str:
    mp = {
        "float32": "FP32",
        "float16": "FP16",
        "uint8": "UINT8",
        "int8": "INT8",
        "int32": "INT32",
        "int64": "INT64",
    }
    name = np.dtype(np_dtype).name
    return mp.get(name, "FP32")
