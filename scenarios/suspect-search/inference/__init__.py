"""Triton-backed inference for suspect-search: detection, ReID, attributes."""
from .triton_client import infer, model_ready  # noqa: F401
from .detect_reid import (  # noqa: F401
    detect, reid_embedding, detector_ready, reid_ready,
)
from .attributes import extract_attributes  # noqa: F401
