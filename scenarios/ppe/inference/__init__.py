"""PPE inference package — thin Triton client + YOLO pre/post-processing."""
from .triton_engine import PPEDetector, detector  # noqa: F401
