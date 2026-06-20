"""Inference package — thin Triton clients for the three ANPR models.

  * plate_detector.detector — anpr_plate (YOLO plate boxes).
  * ocr.ocr                 — ppocr_v6 (PP-OCRv6 recognition + CTC decode).
  * vehicle.vehicle         — yolo26 (vehicle detect + type classification).
"""
from .ocr import ocr  # noqa: F401
from .plate_detector import detector  # noqa: F401
from .vehicle import vehicle  # noqa: F401
