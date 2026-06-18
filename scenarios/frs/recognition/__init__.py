"""Recognition package — ONNX engine + embed/detect/recognize service.

The face inference primitives live in `recognition/inference/` (SCRFD, ArcFace,
alignment, quality, augmentation, ONNX engine); `service.py` composes them into
the plugin's domain calls.
"""
from .service import (  # noqa: F401
    analyze_frame,
    augment_points,
    detect_faces,
    embed_largest_face,
    engine,
    engine_ready,
    onnx_status,
    query_embedding,
    recognize,
)
